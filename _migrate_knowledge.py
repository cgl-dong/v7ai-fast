"""Add chunking columns to knowledge_files."""
from app.core.database import engine
from sqlalchemy import text

COLS = [
    ("chunk_strategy", "VARCHAR(20) DEFAULT ''"),
    ("chunk_size", "INTEGER DEFAULT 0"),
    ("chunk_overlap", "INTEGER DEFAULT 0"),
]

with engine.connect() as c:
    for col, coltype in COLS:
        try:
            c.execute(text(f"ALTER TABLE knowledge_files ADD COLUMN IF NOT EXISTS {col} {coltype}"))
            print(f"Added column: {col}")
        except Exception as e:
            print(f"Error {col}: {e}")
    c.commit()
    print("Migration done")
