from fastapi import FastAPI, HTTPException, Depends
from app import db
from app import schemas
from contextlib import asynccontextmanager
from argon2 import PasswordHasher

def get_db():
    conn = db.get_database_connection()
    try:
        yield conn
    finally:
        conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.get_database_connection()
    db.init_db(conn)
    yield
    # Tear down the civic Postgres pool on shutdown. It spawns worker threads when
    # opened lazily on first use; without this they leak (uvicorn logs "couldn't
    # stop thread pool-1-worker-N"). close_pool() is idempotent — a no-op if the
    # pool was never opened, so this stays safe for tests that never touch civic.
    try:
        from app.civic import db as civic_db
        civic_db.close_pool()
    except Exception:
        pass

app = FastAPI(lifespan=lifespan)
ph = PasswordHasher()

# --- Civic-intelligence slice (feat/civic-intel-slice) --------------------
# Additive wiring for the civic RAG routers. These mount POST /civic/ingest and
# POST /civic/ask alongside the existing tasks/auth/health routes above; they
# share none of the SQLite tables or connections. The civic Postgres schema is
# initialised lazily on first use by app.civic.db.init() (not in the SQLite
# lifespan above), so importing/mounting these routers requires no live Postgres.
from app.civic.routers import ingest as civic_ingest, ask as civic_ask

app.include_router(civic_ingest.router)   # POST /civic/ingest
app.include_router(civic_ask.router)      # POST /civic/ask
# --------------------------------------------------------------------------

@app.get("/health")
def get_health():
    return {"status": "ok"}

@app.post("/register", status_code=201, response_model=schemas.UserOut)
def add_user(user: schemas.UserCreate, conn = Depends(get_db)):
    user_payload = user.model_dump(mode="json")
    password = user_payload["password"]
    hashed_password = ph.hash(password)
    row = db.add_user(conn, {"email": user_payload["email"], "password_hash": hashed_password})
    if row is None:
        raise HTTPException(409, detail="Email already registered")
    return row

@app.post("/tasks", status_code=201, response_model=schemas.TaskOut)
def add_task(task: schemas.TaskCreate, conn = Depends(get_db)):
    task_payload = task.model_dump(mode="json")
    row = db.add_task(conn, task_payload)
    return row

@app.get("/tasks", response_model=list[schemas.TaskOut])
def get_tasks(conn = Depends(get_db)):
    rows = db.get_tasks(conn)
    return rows

@app.get("/tasks/{id}", response_model=schemas.TaskOut)
def get_task(id: int, conn = Depends(get_db)):
    row = db.get_task(conn, id)
    if row is None:
        raise HTTPException(404, detail=f"Task with ID {id} not found")
    return row

@app.patch("/tasks/{id}", response_model=schemas.TaskOut)
def update_task(id: int, task: schemas.TaskUpdate, conn = Depends(get_db)):
    updates_dict = task.model_dump(exclude_unset=True, mode="json")
    updated_row = db.update_task(conn, id, updates_dict)

    if updated_row is None:
        raise HTTPException(404, detail=f"Task with ID {id} not found")
    return updated_row

@app.delete("/tasks/{id}", response_model=schemas.TaskOut)
def delete_task(id: int, conn = Depends(get_db)):
    row = db.delete_task(conn, id)
    if row is None:
        raise HTTPException(404, detail=f"Task with ID {id} not found")
    return row