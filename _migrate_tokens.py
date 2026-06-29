"""Migration: Add tokens column to document_chunks for BM25."""
from app.core.database import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'document_chunks' AND column_name = 'tokens'
        """))
        if not result.fetchone():
            print("Adding tokens column to document_chunks...")
            conn.execute(text("""
                ALTER TABLE document_chunks
                ADD COLUMN tokens TEXT
            """))
            conn.commit()
            print("  Done. Backfill existing chunks by re-indexing data.")
        else:
            print("document_chunks.tokens already exists, skipping.")
        print("Migration complete.")

if __name__ == "__main__":
    migrate()
