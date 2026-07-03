"""Ingest pipeline: fetch Legistar Matters -> normalize -> chunk -> embed -> upsert.

Source: the Legistar Web API for Philadelphia City Council. VERIFIED live
(2026-07) against the real endpoint before this module was written:

    Base:    https://webapi.legistar.com/v1/{client}/          (client = "phila")
    Matters: GET /v1/phila/Matters                             -> 200, JSON array.
             OData query options confirmed working against the live API:
                 $top      page size (server caps large values)
                 $skip     offset -> stable paging when combined with a TOTAL $orderby
                 $orderby  e.g. "MatterIntroDate desc,MatterId desc" (recent first,
                           MatterId tiebreak forces a total order for stable paging)
                 $filter   e.g. "MatterIntroDate ge datetime'2026-01-01'"

    A Matter looks like (fields we keep) -- confirmed against real records:
        MatterId          -> source_ref (upsert key)   e.g. 27386   (int)
        MatterFile        -> file_no                    e.g. "260633" (str, the
                                                        human bill number we cite)
        MatterName        -> (null on recent records; we fall back to MatterTitle)
        MatterTitle       -> title / chunk text         (the substantive text; on
                                                        real records this is a
                                                        multi-paragraph body, which
                                                        is why chunking earns its keep)
        MatterTypeName    -> doc_type                   e.g. "COMMUNICATION"
        MatterStatusName  -> status                     e.g. "PLACED ON FILE"
        MatterIntroDate   -> intro_date                 e.g. "2026-06-11T00:00:00"
        MatterBodyName    -> body_name                  e.g. "CITY COUNCIL"

The whole pipeline is idempotent: we upsert on ``source_ref`` (the MatterId) so
re-running refreshes rows in place rather than duplicating. Chunks are rebuilt
(delete-then-insert) on every upsert so a Matter whose text changed upstream can
never leave stale chunks behind.

Structure adapted from AwardGuard's ``backend/app/core/ingest.py`` (fetch /
parse / upsert / orchestrate), swapping the eCFR XML source for paginated
Legistar JSON and the single ``sections`` table for the
``civic_documents`` + ``civic_chunks`` split.

This module is LOAD-BEARING and is heavily commented on purpose.
"""

from __future__ import annotations

import html
import logging
import re
import time
import unicodedata
from datetime import date, datetime

import httpx

from ..config import settings
from .schemas import CivicChunk, CivicDocument

logger = logging.getLogger("civicscope")

# NOTE: ``pgvector``, ``psycopg`` (via ``app.civic.db``), and ``fastembed`` (via
# ``app.civic.embeddings``) are imported LAZILY inside ``upsert_documents``
# rather than at module top. That is deliberate: it keeps the pure
# pipeline functions -- ``fetch_matters``, ``normalize_matter``,
# ``chunk_document`` -- importable and unit-testable with none of the DB / ONNX
# stack installed, and it means importing this module (and therefore the whole
# FastAPI app, which mounts the civic router) never requires Postgres deps. Only
# an actual ingest run touches them.

# ---------------------------------------------------------------------------
# Constants (all load-bearing knobs live here so a reviewer can see them at once)
# ---------------------------------------------------------------------------

# Legistar Web API base. The concrete client slug is appended per-request from
# ``settings.legistar_client`` (default "phila") so the jurisdiction is config,
# not a literal buried in a URL.
LEGISTAR_BASE = "https://webapi.legistar.com/v1"

# A descriptive User-Agent is basic API etiquette: it identifies the project and
# a contact so the Legistar operators can reach us if our traffic misbehaves,
# rather than seeing an anonymous default python-httpx agent.
USER_AGENT = "civicscope-ingest/0.1 (portfolio project; contact cst0520@gmail.com)"

# OData page size. Legistar serves Matters in pages; we walk them with
# $top/$skip. 200 is a polite middle ground -- large enough to keep the request
# count (and the total ingest time) down, small enough not to hammer the API
# with huge responses.
PAGE_SIZE = 200

# Polite pause between successive page requests. The Legistar API is a shared
# public resource with no published rate limit, so we self-throttle: a short
# sleep keeps us well under any reasonable ceiling and is the neighbourly thing
# to do for an unauthenticated bulk read.
REQUEST_DELAY_SECONDS = 0.5

# Per-request network timeout. Legistar can be slow for large pages; 60s is
# generous without hanging the ingest forever on a stalled connection.
REQUEST_TIMEOUT_SECONDS = 60.0

# Resilience for long crawls. A multi-thousand-page backfill will occasionally hit
# a transient TRANSPORT error (connection reset, read timeout) mid-stream; without
# a retry, one blip aborts the whole ingest. We retry transient transport errors a
# few times with linear backoff. HTTP *status* errors still fail loud — a 4xx/5xx
# is a real problem (throttling, outage), not a blip, and a partial silent ingest
# would be worse than a visible, retryable error.
FETCH_RETRIES = 4
RETRY_BACKOFF_SECONDS = 2.0
_TRANSIENT_EXC_NAMES = frozenset(
    {
        "ConnectError", "ConnectTimeout", "ReadError", "ReadTimeout",
        "WriteError", "PoolTimeout", "RemoteProtocolError",
    }
)


def _is_transient(exc: Exception) -> bool:
    """True for transport errors worth retrying (not HTTP status errors)."""

    return type(exc).__name__ in _TRANSIENT_EXC_NAMES


def _get_with_retry(
    http: httpx.Client, url: str, params: dict | None = None
) -> httpx.Response:
    """GET with retry on transient transport errors (linear backoff)."""

    last: Exception | None = None
    for attempt in range(FETCH_RETRIES):
        try:
            return http.get(url, params=params)
        except Exception as exc:  # noqa: BLE001 - re-raised below if not transient
            if not _is_transient(exc):
                raise
            last = exc
            logger.warning(
                "transient fetch error %s (attempt %d/%d); retrying",
                type(exc).__name__, attempt + 1, FETCH_RETRIES,
            )
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    assert last is not None
    raise last

# Safety cap on how many pages we will ever walk in a single run. Philadelphia's
# full Matters history is tens of thousands of rows; for this thin slice we bound
# the crawl so a single /civic/ingest call is fast and predictable rather than a
# multi-minute full-history backfill. Raise this (or lift it entirely) when the
# slice graduates to a real backfill job.
MAX_PAGES = 10

# Chunking size (in characters). Today MatterTitle is often a single short line,
# but on real records it is a multi-paragraph body (see the module docstring),
# so we split into overlapping windows. The overlap keeps a sentence that
# straddles a boundary retrievable from either side. These are deliberately
# conservative for bge-small's short context; they are the stable extension
# point for when full Matter text / attachments are added.
CHUNK_SIZE_CHARS = 800
CHUNK_OVERLAP_CHARS = 100


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_matters(
    client: str | None = None,
    *,
    http: httpx.Client | None = None,
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """Paginate Philadelphia Matters from Legistar and return the raw JSON dicts.

    We order by ``MatterIntroDate desc`` so the newest legislation is ingested
    first -- for a bounded slice (``max_pages``) that means we capture the most
    relevant, recent Matters rather than the oldest historical ones. Paging is
    ``$top``/``$skip``; we stop as soon as a page comes back short (fewer rows
    than ``page_size``), which is the canonical "no more data" signal for OData
    offset paging.
    """

    client = client or settings.legistar_client

    # Reuse a single connection where possible; the caller may pass one in (tests
    # inject a mock transport), otherwise we own the client and must close it.
    own_client = http is None
    http = http or httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT},
    )

    matters: list[dict] = []
    url = f"{LEGISTAR_BASE}/{client}/Matters"

    try:
        for page in range(max_pages):
            params = {
                "$top": page_size,
                "$skip": page * page_size,
                # A TOTAL order is what makes $skip paging stable: MatterIntroDate
                # alone is far from unique (dozens of Matters share one date), and
                # SQL Server / OData does not guarantee a stable tiebreak among
                # equal sort keys across separate $top/$skip requests, so rows can
                # be silently skipped at page boundaries. MatterId is monotonic and
                # never null, so appending it as a tiebreaker forces determinism.
                "$orderby": "MatterIntroDate desc,MatterId desc",
            }

            resp = _get_with_retry(http, url, params)
            # Fail loud on a bad status -- a partial/garbage ingest is worse than
            # a visible error the operator can retry.
            resp.raise_for_status()
            batch = resp.json()

            # Legistar returns a bare JSON array. A 200 carrying a JSON OBJECT is
            # an OData/CDN error envelope, not data — and it is truthy, so blindly
            # extending would splice the dict's KEYS (strings) into ``matters`` and
            # crash normalize_matter later with an opaque 500. Turn that silent
            # corruption into a clear, retryable error.
            if not isinstance(batch, list):
                raise ValueError(
                    f"Legistar returned a non-list payload ({type(batch).__name__}); "
                    "expected a JSON array of Matters"
                )

            # An empty array means we have walked off the end of the data.
            if not batch:
                break

            matters.extend(batch)

            # A short page is the last page: there is nothing after it, so stop
            # rather than issuing a guaranteed-empty extra request.
            if len(batch) < page_size:
                break

            # Be a good citizen: pause before asking for the next page.
            time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        if own_client:
            http.close()

    return matters


# ---------------------------------------------------------------------------
# Full bill text (PDF attachments)
# ---------------------------------------------------------------------------

# Legistar exposes no plain-text body endpoint (the /Matters/{id}/Texts resource
# returns 405); the full bill text lives in a PDF attachment. We fetch a Matter's
# attachments, download the canonical text PDF, and extract it with pypdf. Every
# step is BEST-EFFORT: any failure — no attachment, HTTP error, or a scanned
# image-only PDF with no extractable text — yields None so ingest falls back to
# chunking the title. A Matter is always ingestable on its title alone.

# Legistar labels the canonical bill-text attachment "Text File N"; we prefer it
# and fall back to the first attachment when no name matches.
_TEXT_ATTACHMENT_HINT = "text file"

# Attachment PDFs are small (tens–hundreds of KB); 30s is generous.
PDF_TIMEOUT_SECONDS = 30.0

# Upper bound on extracted body length. A pathological multi-hundred-page PDF would
# otherwise explode chunk count and embedding cost; 40k chars (~10 pages of bill
# text) is far more than any answer needs and keeps a single Matter bounded.
MAX_BODY_CHARS = 40_000

# Polite pause between attachment downloads, same rationale as REQUEST_DELAY.
ATTACHMENT_DELAY_SECONDS = 0.2


def _pick_text_attachment(attachments: list[dict]) -> str | None:
    """Choose the best attachment URL to treat as the bill's full text.

    Prefers an attachment whose name contains "text file" (Legistar's label for
    the canonical bill text); otherwise falls back to the first attachment with a
    hyperlink. Returns None when there is nothing downloadable.
    """

    if not isinstance(attachments, list):
        return None
    linked = [a for a in attachments if isinstance(a, dict) and a.get("MatterAttachmentHyperlink")]
    for a in linked:
        name = (a.get("MatterAttachmentName") or "").lower()
        if _TEXT_ATTACHMENT_HINT in name:
            return a["MatterAttachmentHyperlink"]
    return linked[0]["MatterAttachmentHyperlink"] if linked else None


def _extract_pdf_text(data: bytes) -> str:
    """Extract text from PDF bytes; "" when the PDF has no extractable text.

    A scanned/image-only bill (no text layer) yields "" rather than raising, so the
    caller falls back to the title. pypdf is imported lazily to keep the pure
    pipeline functions importable without it.
    """

    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# Collapses the runs of spaces and blank lines that pdf text extraction leaves
# behind (Legistar bill PDFs are justified, so extraction yields ragged spacing).
_WS_RUN_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


def _clean_body(text: str) -> str:
    """Normalize extracted PDF text: unify whitespace, drop format chars, cap size."""

    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = _WS_RUN_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()[:MAX_BODY_CHARS]


def fetch_matter_text(
    matter_id: str, *, client: str | None = None, http: httpx.Client
) -> str | None:
    """Best-effort full bill text for one Matter, or None to fall back to the title.

    Fetches the Matter's attachments, downloads the canonical text PDF, and returns
    its cleaned extracted text. Swallows every failure (missing attachment, HTTP
    error, unreadable/scanned PDF) into None so one bad Matter never aborts ingest.
    """

    client = client or settings.legistar_client
    try:
        resp = http.get(
            f"{LEGISTAR_BASE}/{client}/Matters/{matter_id}/Attachments",
            timeout=PDF_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        url = _pick_text_attachment(resp.json())
        if not url:
            return None

        pdf = http.get(url, timeout=PDF_TIMEOUT_SECONDS)
        pdf.raise_for_status()
        body = _clean_body(_extract_pdf_text(pdf.content))
        # Treat an empty extraction (scanned/image PDF) as "no text" -> fall back.
        return body or None
    except Exception:  # noqa: BLE001 - full text is best-effort; fall back to title
        logger.warning("no full text for Matter %s; using title", matter_id, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------


def _parse_intro_date(value: str | None) -> date | None:
    """Parse Legistar's ISO-ish ``MatterIntroDate`` ("2026-06-11T00:00:00") to a date.

    Returns ``None`` for missing/unparseable values rather than raising -- a
    Matter with a malformed date is still worth ingesting; we just leave the
    date null.
    """

    if not value:
        return None
    try:
        # ``fromisoformat`` handles the "YYYY-MM-DDTHH:MM:SS" shape Legistar emits.
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _matter_url(client: str, matter: dict) -> str:
    """Best-effort canonical Legistar URL for a Matter.

    Legistar's public UI lives on ``{client}.legistar.com`` and addresses a
    Matter by its GUID via LegislationDetail. When the GUID is present we build
    that deep link; otherwise we fall back to the API resource URL, which always
    exists. Either way the stored ``url`` points a reviewer at the source record.
    """

    guid = matter.get("MatterGuid")
    if guid:
        return f"https://{client}.legistar.com/LegislationDetail.aspx?GUID={guid}"
    return f"{LEGISTAR_BASE}/{client}/Matters/{matter.get('MatterId')}"


# Strips HTML tags. Legistar titles routinely carry markup ("<b>An Ordinance</b>")
# and entities ("&amp;"); left raw they degrade the embedding (markup tokens),
# pollute the tsvector (indexed tag fragments), and produce ugly citation titles.
_TAG_RE = re.compile(r"<[^>]+>")

# Strips the administration's standard transmittal PREAMBLE. Legislation filed by
# the Mayor's office is wrapped in a boilerplate header that is IDENTICAL across
# hundreds of Matters: an optional date line, the fixed salutation "TO THE
# PRESIDENT AND MEMBERS OF THE COUNCIL OF THE CITY OF PHILADELPHIA:", a transmittal
# sentence ("I am transmitting ... entitled:"), and a bare document-type header
# ("AN ORDINANCE" / "RESOLUTION"). That shared prose dominates both the embedding
# and the tsvector — every wrapped Matter looks alike to the retriever, so the
# dense arm surfaces procedural cover-letters for topical questions — while the
# SUBSTANTIVE text (what the bill actually does) is buried after it. We remove the
# preamble span so each chunk leads with its own substance. Deliberately
# conservative: it only fires when the salutation is present, and only removes the
# fixed preamble prefix, so a plain title (no salutation) is returned untouched.
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October"
    "|November|December"
)
_PREAMBLE_RE = re.compile(
    r"^\s*(?:(?:" + _MONTHS + r")\s+\d{1,2},\s*\d{4}\s*)?"       # optional date line
    r"TO THE PRESIDENT AND MEMBERS OF THE COUNCIL OF THE CITY OF PHILADELPHIA\s*:\s*"
    r"(?:I am[^:]{0,200}:\s*)?"                                   # transmittal sentence
    r"(?:(?:AN?\s+ORDINANCE|A\s+RESOLUTION|RESOLUTION)\s*)?",     # bare doc-type header
    re.IGNORECASE,
)


def _strip_boilerplate(text: str) -> str:
    """Remove the shared administration transmittal preamble (see ``_PREAMBLE_RE``).

    Returns ``text`` unchanged when the salutation is absent (the common case for
    Council-introduced titles). Removes at most one leading preamble span.
    """

    return _PREAMBLE_RE.sub("", text, count=1).strip()


def _clean_title(raw: str) -> str:
    """Normalize a raw Legistar title for storage, chunking, and citation.

    Order matters: unescape entities first, strip HTML tags, drop Unicode format
    characters (category Cf, e.g. the zero-width space U+200B / U+FEFF that
    survives ``.strip()`` and would otherwise embed an effectively-empty ghost
    chunk), strip the shared transmittal preamble so the chunk leads with its own
    substance, then trim surrounding whitespace.
    """

    text = html.unescape(raw)
    text = _TAG_RE.sub("", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = _strip_boilerplate(text)
    return text.strip()


def normalize_matter(matter: dict, *, client: str | None = None) -> CivicDocument:
    """Map one raw Legistar Matter dict into a normalized ``CivicDocument``.

    The full original record is preserved in ``raw`` so nothing is lost -- later
    slices can mine additional Legistar fields without a re-fetch. ``source_ref``
    is the stringified ``MatterId`` (our upsert key); ``file_no`` is the human
    bill number we cite in answers.
    """

    client = client or settings.legistar_client

    # Title carries the substantive text. MatterName is usually null on recent
    # records, so MatterTitle is the primary source; we fall back to MatterName
    # only if the title is empty, and to "" so downstream code never sees None.
    # Legistar JSON is not schema-guaranteed: a truthy non-string title (e.g. a
    # numeric MatterTitle) would make ``.strip()`` raise, so coerce to str first.
    raw_title = matter.get("MatterTitle") or matter.get("MatterName") or ""
    if not isinstance(raw_title, str):
        raw_title = str(raw_title)
    title = _clean_title(raw_title)

    return CivicDocument(
        source_ref=str(matter.get("MatterId")),
        jurisdiction=client,
        doc_type=matter.get("MatterTypeName"),
        file_no=matter.get("MatterFile"),
        title=title,
        body_name=matter.get("MatterBodyName"),
        status=matter.get("MatterStatusName"),
        intro_date=_parse_intro_date(matter.get("MatterIntroDate")),
        url=_matter_url(client, matter),
        raw=matter,
    )


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    """Fixed-window character chunker with overlap.

    Deterministic (same input -> same chunks) so ``chunk_index`` is stable across
    re-ingests. We slide a ``size``-wide window forward by ``size - overlap`` each
    step; the overlap keeps content that straddles a boundary retrievable from
    either chunk. Whitespace-only windows are dropped.

    Zero-width/format characters (Unicode category Cf, e.g. U+200B/U+FEFF) are
    dropped before the emptiness test: they survive ``.strip()`` and would
    otherwise make an effectively-empty title chunk into a retrieval-polluting,
    un-citable ghost row. (normalize_matter already cleans titles; this keeps the
    "never embed an empty chunk" guarantee true for any direct caller too.)
    """

    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    step = max(1, size - overlap)  # guard against a zero/negative stride
    chunks: list[str] = []
    for start in range(0, len(text), step):
        window = text[start : start + size].strip()
        if window:
            chunks.append(window)
        # Once a window reaches the end of the string we are done -- further
        # windows would only re-emit the tail.
        if start + size >= len(text):
            break
    return chunks


def chunk_document(doc: CivicDocument) -> list[CivicChunk]:
    """Split a document's text into ordered ``CivicChunk`` records.

    Chunks the full bill ``body`` when it was extracted from the PDF attachment,
    else falls back to the ``title`` — so a Matter with no readable attachment is
    still retrievable on its title. Chunks back-reference their parent by
    ``source_ref`` and ``file_no`` so the upsert layer can attach them to the right
    document row and the answer layer can cite them. ``chunk_index`` is the
    deterministic ordinal within the document. Embeddings are filled in later, in
    one batch, by ``upsert_documents``.
    """

    source_text = doc.body or doc.title or ""
    pieces = _split_text(source_text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)
    return [
        CivicChunk(
            source_ref=doc.source_ref,
            file_no=doc.file_no,
            chunk_index=i,
            text=piece,
        )
        for i, piece in enumerate(pieces)
    ]


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def upsert_documents(docs: list[CivicDocument]) -> int:
    """Chunk, embed (one batch), and idempotently upsert documents + chunks.

    Returns the number of documents upserted. The heavy lifting a reviewer should
    note:

      * We compute ALL chunks across ALL documents first, then embed them in a
        single fastembed batch -- one ONNX call for the whole run is dramatically
        cheaper than one call per chunk (AwardGuard uses the same batching trick).
      * ``register_vector(conn)`` teaches psycopg to adapt Python lists <-> the
        pgvector ``vector`` type, so we can pass the embedding straight through.
      * Everything runs inside one transaction: either the whole page of Matters
        lands or none of it does, so an interrupted ingest never leaves a
        half-written document (a doc row with no chunks).
    """

    if not docs:
        return 0

    # Lazy imports (see the note at the top of the module): the DB / embedding
    # stack is only needed for a real ingest, not for importing or unit-testing
    # the pure pipeline functions.
    from pgvector.psycopg import register_vector

    from .db import get_conn, upsert_document
    from .embeddings import embed_texts

    # Build every chunk up front, remembering which doc each belongs to, so we can
    # embed the whole run in one batch and still map vectors back to their chunk.
    doc_chunks: list[list[CivicChunk]] = [chunk_document(d) for d in docs]
    flat_chunks: list[CivicChunk] = [c for chunks in doc_chunks for c in chunks]

    # One batched embed call for the entire run. Guard the empty case so we never
    # call the model with [] (some backends dislike it).
    if flat_chunks:
        vectors = embed_texts([c.text for c in flat_chunks])
        for chunk, vec in zip(flat_chunks, vectors):
            chunk.embedding = vec

    # One transaction + one register_vector for the whole run, then delegate each
    # per-document write to the single source of truth (db.upsert_document) so the
    # document/chunk upsert SQL is never duplicated or allowed to drift. Either the
    # whole page lands or none of it does (an interrupted ingest never leaves a doc
    # row with no chunks).
    with get_conn() as conn:
        register_vector(conn)
        for doc, chunks in zip(docs, doc_chunks):
            upsert_document(conn, doc, chunks)
        conn.commit()

    return len(docs)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def hydrate_bodies(
    docs: list[CivicDocument],
    *,
    client: str | None = None,
    http: httpx.Client | None = None,
) -> None:
    """Fill each document's ``body`` with its full bill text (best-effort, in place).

    One shared HTTP client walks the documents, downloading + extracting each
    Matter's PDF attachment (throttled). Any Matter whose text can't be fetched
    keeps ``body = None`` and is later chunked on its title. Separated from
    ``run_ingest`` so it is independently testable and so a caller can skip it
    (title-only ingest) when the network cost isn't wanted.
    """

    client = client or settings.legistar_client
    own_client = http is None
    http = http or httpx.Client(headers={"User-Agent": USER_AGENT})
    try:
        for i, doc in enumerate(docs):
            doc.body = fetch_matter_text(doc.source_ref, client=client, http=http)
            # Throttle between downloads, but not after the last one.
            if i < len(docs) - 1:
                time.sleep(ATTACHMENT_DELAY_SECONDS)
    finally:
        if own_client:
            http.close()


def run_ingest(
    client: str | None = None,
    *,
    full_text: bool = True,
    max_pages: int = MAX_PAGES,
) -> int:
    """Full pipeline: fetch -> normalize -> [full text] -> chunk -> embed -> upsert.

    Returns the number of documents ingested. This is the single entry point the
    ``POST /civic/ingest`` router calls. ``full_text`` (default True) fetches each
    Matter's PDF attachment for the real bill body; pass False for a fast,
    network-light title-only ingest. ``max_pages`` bounds how deep into a
    jurisdiction's history to crawl (each page is ``PAGE_SIZE`` Matters), so a
    backfill can reach far past the default recent-window cap.
    """

    client = client or settings.legistar_client

    raw_matters = fetch_matters(client, max_pages=max_pages)

    docs: list[CivicDocument] = []
    for m in raw_matters:
        # Skip id-less Matters: source_ref is the UNIQUE upsert key, so stringifying
        # a missing MatterId to the literal "None" would collapse ALL id-less rows
        # onto one record, each overwriting the last (silent data loss). MatterId is
        # present on every live record; this only guards a malformed source.
        if m.get("MatterId") is None:
            logger.warning(
                "skipping Matter with no MatterId (MatterFile=%r)", m.get("MatterFile")
            )
            continue
        # One malformed record must not abort the whole page: normalize per-record
        # and skip (log) any that raise, rather than failing the entire ingest.
        try:
            docs.append(normalize_matter(m, client=client))
        except Exception:  # noqa: BLE001 - a single bad record is skipped, not fatal
            logger.warning(
                "skipping malformed Matter (MatterId=%r)", m.get("MatterId"),
                exc_info=True,
            )

    # Drop Matters with no usable text: there is nothing to chunk, embed, or cite,
    # so they would only add empty rows that can never be retrieved.
    docs = [d for d in docs if d.title]

    # Enrich with full bill text from PDF attachments (best-effort; falls back to
    # the title per Matter). Done after the title filter so we never spend a
    # download on a Matter we're about to drop.
    if full_text:
        hydrate_bodies(docs, client=client)

    return upsert_documents(docs)
