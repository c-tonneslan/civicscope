import sqlite3
from datetime import timezone, datetime


def get_database_connection():
    return sqlite3.connect("tasks.db")

def init_db(conn):
    command = '''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'todo'
            CHECK (status IN ('backlog', 'todo', 'in_progress', 'done')),
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    '''
    cursor = conn.cursor()
    cursor.execute(command)
    conn.commit()

def add_task(conn, data: dict):
    conn.row_factory = sqlite3.Row
    command = "INSERT INTO tasks (title, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
    cursor = conn.cursor()
    time = datetime.now(timezone.utc).isoformat()
    cursor.execute(command, (data["title"], data["description"], data["status"], time, time))
    conn.commit()
    id = cursor.lastrowid

    command = "SELECT * FROM tasks WHERE id = ?"
    cursor = conn.cursor()
    cursor.execute(command, (id,))
    return dict(cursor.fetchone())

def get_tasks(conn):
    conn.row_factory = sqlite3.Row
    command = "SELECT * FROM tasks"
    cursor = conn.cursor()
    cursor.execute(command)
    return [dict(row) for row in cursor.fetchall()]

def get_task(conn, id: int):
    conn.row_factory = sqlite3.Row
    command = "SELECT * FROM tasks WHERE id = ?"
    cursor = conn.cursor()
    cursor.execute(command, (id,))
    row = cursor.fetchone()
    return dict(row) if row else None

def update_task(conn, id: int, updates: dict):
    if not updates:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
    args = list(updates.values())
    args += [datetime.now(timezone.utc).isoformat(), id]

    command = f"UPDATE tasks SET {set_clause}, updated_at = ? WHERE id = ?"

    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(command, args)

    if cursor.rowcount == 0:
        return None
    
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (id,))
    updated_row = cursor.fetchone()
    conn.commit()
    return dict(updated_row) if updated_row else None

def delete_task(conn, id: int):
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (id,))
    deleted_row = cursor.fetchone()
    if deleted_row is None:
        return None

    command = "DELETE FROM tasks WHERE id = ?"
    cursor.execute(command, (id,))
    conn.commit()
    return dict(deleted_row)
