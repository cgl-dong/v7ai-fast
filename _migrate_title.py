from app.core.database import engine
from sqlalchemy import text
c = engine.connect()
c.execute(text("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS title VARCHAR(200) DEFAULT ''"))
c.commit()
c.close()
print("done")
