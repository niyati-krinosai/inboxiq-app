from app.config import normalize_database_url


def test_render_postgres_url():
    url = "postgresql://user:pass@dpg-xxx.oregon-postgres.render.com/inboxiq"
    assert normalize_database_url(url) == (
        "postgresql+asyncpg://user:pass@dpg-xxx.oregon-postgres.render.com/inboxiq"
    )


def test_postgres_scheme_url():
    url = "postgres://user:pass@host/db"
    assert normalize_database_url(url) == "postgresql+asyncpg://user:pass@host/db"


def test_asyncpg_url_unchanged():
    url = "postgresql+asyncpg://user:pass@host/db"
    assert normalize_database_url(url) == url
