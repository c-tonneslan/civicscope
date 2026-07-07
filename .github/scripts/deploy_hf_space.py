"""Sync the FastAPI backend to the Hugging Face Space on push. Staging (Dockerfile,
README, prod requirements, app/) is generated here so the repo stays a plain
monorepo. Requires the HF_TOKEN secret."""
import os, shutil, tempfile, pathlib
from huggingface_hub import HfApi

REPO = "CharlieTonneslan/docket-api"
root = pathlib.Path(__file__).resolve().parents[2]
stage = pathlib.Path(tempfile.mkdtemp())

shutil.copytree(root / "app", stage / "app")

req = [
    l for l in (root / "requirements.txt").read_text().splitlines()
    if l.strip() and not l.strip().startswith("#")
    and not any(x in l.lower() for x in ("pytest", "hypothesis", "cov"))
]
(stage / "requirements.txt").write_text("\n".join(req) + "\n")

(stage / "README.md").write_text(
    "---\ntitle: Docket API\nemoji: 🏛️\ncolorFrom: indigo\ncolorTo: blue\n"
    "sdk: docker\napp_port: 7860\npinned: false\n---\n\n"
    "Docket civic-intelligence API (FastAPI + pgvector + fastembed + Groq).\n"
)
(stage / "Dockerfile").write_text(
    "FROM python:3.12-slim\nWORKDIR /code\nCOPY requirements.txt .\n"
    "RUN pip install --no-cache-dir -r requirements.txt\nCOPY app ./app\n"
    "ENV FASTEMBED_CACHE_PATH=/tmp/fastembed_cache HF_HOME=/tmp/hf DATABASE_PATH=/tmp/tasks.db\n"
    'EXPOSE 7860\nCMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]\n'
)

HfApi(token=os.environ["HF_TOKEN"]).upload_folder(
    folder_path=str(stage), repo_id=REPO, repo_type="space",
    commit_message="sync backend from c-tonneslan/docket",
)
print("synced to", REPO)
