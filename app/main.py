from fastapi import FastAPI, HTTPException, Depends
from app import db
from app import schemas
from contextlib import asynccontextmanager
from datetime import datetime, timezone

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

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def get_health():
    return {"status": "ok"}

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