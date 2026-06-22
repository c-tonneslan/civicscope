from app import schemas
from datetime import datetime
import time

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_add_task(client):
    response = client.post("/tasks", json={"title": "Title", "description": "Description", "status": "todo"})
    data = schemas.TaskOut(**response.json())
    assert response is not None
    assert response.status_code == 201
    assert data.id == 1
    assert data.title == "Title"
    assert data.description == "Description"
    assert data.status == "todo"

def test_add_task_with_bad_status(client):
    response = client.post("/tasks", json={"title": "Title", "description": "Description", "status": "bad"})
    assert response.status_code == 422

def test_get_tasks(client):
    client.post("/tasks", json={"title": "Title 1", "description": "Description 1", "status": "todo"})
    client.post("/tasks", json={"title": "Title 2", "description": "Description 2", "status": "backlog"})

    response = client.get("/tasks")

    assert response.status_code == 200
    data = [schemas.TaskOut(**row) for row in response.json()]
    data.sort(key = lambda x : x.id)
    assert data[0].id == 1
    assert data[0].title == "Title 1"
    assert data[0].description == "Description 1"
    assert data[0].status == "todo"
    assert data[1].id == 2
    assert data[1].title == "Title 2"
    assert data[1].description == "Description 2"
    assert data[1].status == "backlog"

def test_get_task(client):
    client.post("/tasks", json={"title": "Title 1", "description": "Description 1", "status": "todo"})
    response = client.get("/tasks/1")
    assert response.status_code == 200
    data = schemas.TaskOut(**response.json())
    assert data.id == 1
    assert data.title == "Title 1"
    assert data.description == "Description 1"
    assert data.status == "todo"
    assert isinstance(data.created_at, datetime)
    assert isinstance(data.updated_at, datetime)

def test_get_task_returns_404(client):
    response = client.get("/tasks/1")
    assert response.status_code == 404
    assert response.json() == {"detail": "Task with ID 1 not found"}

def test_update_task(client):
    client.post("/tasks", json={"title": "Title 1", "description": "Description 1", "status": "todo"})
    response = client.patch("/tasks/1", json={"title": "New title", "description": "New description", "status": "done"})

    assert response.status_code == 200
    data = schemas.TaskOut(**response.json())
    assert data.id == 1
    assert data.title == "New title"
    assert data.description == "New description"
    assert data.status == "done"
    assert isinstance(data.created_at, datetime)
    assert isinstance(data.updated_at, datetime)
    assert data.created_at < data.updated_at

def test_partial_update_only_status(client):
    client.post("/tasks", json={"title": "Keep me", "description": "Keep me too", "status": "todo"})
    response = client.patch("/tasks/1", json={"status": "done"})
    assert response.status_code == 200
    data = schemas.TaskOut(**client.get("/tasks/1").json())
    assert data.title == "Keep me"
    assert data.status == "done"

def test_update_task_returns_404(client):
    response = client.patch("/tasks/1", json={"status": "done"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Task with ID 1 not found"}

def test_delete_task(client):
    client.post("/tasks", json={"title": "Title 1", "description": "Description 1", "status": "todo"})
    response = client.delete("/tasks/1")
    data = schemas.TaskOut(**response.json())
    assert data.id == 1
    assert data.title == "Title 1"
    assert data.description == "Description 1"
    assert data.status == "todo"
    
def test_delete_returns_404(client):
    response = client.delete("/tasks/1")
    assert response.status_code == 404
    assert response.json() == {"detail": "Task with ID 1 not found"}