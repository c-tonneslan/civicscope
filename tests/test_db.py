from app import db
from app.schemas import TaskStatus
from datetime import datetime, timezone
import pytest
import sqlite3

def test_add_task(db_conn):
    result = db.add_task(db_conn, {"title": "Title", "description": "Description", "status": TaskStatus.todo})
    assert result is not None   
    assert result["title"] == "Title"
    assert result["description"] == "Description"
    assert result["status"] == "todo"

def test_add_task_with_status(db_conn):
    result = db.add_task(db_conn, {"title": "Title", "description": "Description", "status": TaskStatus.in_progress})
    assert result is not None
    assert result["title"] == "Title"
    assert result["description"] == "Description"
    assert result["status"] == "in_progress"

def test_add_task_with_bad_status(db_conn):
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        db.add_task(db_conn, {"title": "Title", "description": "Description", "status": "bad"})
    assert "CHECK constraint failed" in str(exc_info.value)

def test_list_tasks(db_conn):
    db.add_task(db_conn, {"title": "Title 1", "description": "Description 1", "status": TaskStatus.todo})
    db.add_task(db_conn, {"title": "Title 2", "description": "Description 2", "status": TaskStatus.todo})
    
    tasks = db.get_tasks(db_conn)
    assert len(tasks) == 2
    assert tasks[0]["id"] == 1 
    assert tasks[0]["title"] == "Title 1"
    assert tasks[0]["description"] == "Description 1"
    assert tasks[0]["status"] == "todo"
    assert tasks[1]["id"] == 2
    assert tasks[1]["title"] == "Title 2"
    assert tasks[1]["description"] == "Description 2"
    assert tasks[1]["status"] == "todo"

def test_get_task(db_conn):
    db.add_task(db_conn, {"title": "Title 1", "description": "Description 1", "status": TaskStatus.todo})

    task = db.get_task(db_conn, 1)
    assert task is not None
    assert task["id"] == 1
    assert task["title"] == "Title 1"
    assert task["description"] == "Description 1"
    assert task["status"] == "todo"

def test_get_missing_task_returns_none(db_conn):
    task = db.get_task(db_conn, 0)
    assert task is None

def test_update_task(db_conn):
    db.add_task(db_conn, {"title": "Title", "description": "Description", "status": TaskStatus.todo})
    db.update_task(db_conn, 1, {"title": "New Title", "description": "New Description", "status": TaskStatus.done})
    task = db.get_task(db_conn, 1)
    assert task is not None
    assert task["id"] == 1
    assert task["title"] == "New Title"
    assert task["description"] == "New Description"
    assert task["status"] == "done"

def test_delete_task(db_conn):
    db.add_task(db_conn, {"title": "Title", "description": "Description", "status": TaskStatus.done})
    deleted_task = db.delete_task(db_conn, 1)
    assert deleted_task["id"] == 1
    assert deleted_task["title"] == "Title"
    assert deleted_task["description"] == "Description"
    assert deleted_task["status"] == "done"

    task = db.get_task(db_conn, 1)
    assert task is None
