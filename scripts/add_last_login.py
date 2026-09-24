from app.core.config import settings
from sqlalchemy import create_engine, text

engine = create_engine(settings.database_url)
with engine.connect() as conn:
    cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
    print("Existing columns:", cols)
    if "last_login" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN last_login DATETIME"))
        conn.commit()
        print("Added last_login column OK")
    else:
        print("last_login already exists")
