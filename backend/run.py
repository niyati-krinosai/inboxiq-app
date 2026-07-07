"""Production entrypoint — fixes Render/Railway postgres URL for asyncpg."""
import os

from app.config import normalize_database_url

if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        os.environ["DATABASE_URL"] = normalize_database_url(db_url)

    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
