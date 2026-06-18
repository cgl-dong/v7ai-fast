"""Migration: Add user_id column to knowledge_bases and knowledge_files tables."""
from app.core.database import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        # Check if columns already exist
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'knowledge_bases' AND column_name = 'user_id'
        """))
        if not result.fetchone():
            print("Adding user_id to knowledge_bases...")
            conn.execute(text("""
                ALTER TABLE knowledge_bases
                ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_knowledge_bases_user_id ON knowledge_bases(user_id)
            """))
            print("  Done.")
        else:
            print("knowledge_bases.user_id already exists, skipping.")

        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'knowledge_files' AND column_name = 'user_id'
        """))
        if not result.fetchone():
            print("Adding user_id to knowledge_files...")
            conn.execute(text("""
                ALTER TABLE knowledge_files
                ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_knowledge_files_user_id ON knowledge_files(user_id)
            """))
            print("  Done.")
        else:
            print("knowledge_files.user_id already exists, skipping.")

        conn.commit()
        print("Migration complete.")

if __name__ == "__main__":
    migrate()
