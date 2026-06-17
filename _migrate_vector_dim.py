"""Fix pgvector dimension mismatch: 384 -> 768 for bge-base-zh-v1.5."""
from app.core.database import engine
from sqlalchemy import text

with engine.connect() as c:
    # Drop old embedding column and recreate with correct dim
    try:
        c.execute(text("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding"))
        print("Dropped old embedding column")
    except Exception as e:
        print(f"Drop error (ok if already dropped): {e}")
        c.rollback()

    try:
        c.execute(text("ALTER TABLE document_chunks ADD COLUMN embedding vector(768)"))
        print("Added embedding column with vector(768)")
    except Exception as e:
        print(f"Add error: {e}")
        c.rollback()

    c.commit()
    print("Migration done. Existing files need re-indexing.")
