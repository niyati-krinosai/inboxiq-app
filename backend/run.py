"""Production entrypoint — fixes Render/Railway postgres URL for asyncpg."""
import os

if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        os.environ["DATABASE_URL"] = db_url.replace(
            "postgres://", "postgresql+asyncpg://", 1
        )

    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
