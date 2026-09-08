# InboxIQ

Transform your Gmail newsletter subscriptions into a searchable, conversational intelligence system.

**Gmail is only the ingestion layer.** The chatbot answers exclusively from structured knowledge extracted from newsletters — never from raw emails. Nothing is ever sent, modified, deleted, or labeled in the connected mailbox; access is strictly read-only.

**Live deployment:**
| Layer | URL |
|---|---|
| App (frontend) | https://inboxiq-iota.vercel.app |
| API (backend) | https://inboxiq-api-q4en.onrender.com |
| API health check | https://inboxiq-api-q4en.onrender.com/health |
| Source | https://github.com/niyati-krinosai/inboxiq-app |

---

## Table of contents

1. [How it works](#how-it-works)
2. [Services used](#services-used)
3. [Tech stack](#tech-stack)
4. [Local setup](#local-setup)
5. [Environment variables](#environment-variables)
6. [Production deployment](#production-deployment)
7. [API reference](#api-reference)
8. [Operational scripts](#operational-scripts)
9. [CI/CD](#cicd)
10. [Design constraints](#design-constraints)
11. [Troubleshooting](#troubleshooting)

---

## How it works

InboxIQ never lets an LLM read your raw inbox at answer-time. Instead it runs a one-way pipeline that turns newsletters into structured, queryable knowledge ahead of time, and the chat/search/timeline features only ever read from that structured store.

```
┌─────────────┐   ┌──────────────────┐   ┌────────────────┐   ┌───────────────┐
│   Gmail     │──▶│ Newsletter       │──▶│ Incremental     │──▶│  HTML Parser   │
│ (read-only) │   │ Discovery Engine │   │ Sync (History   │   │ (strip ads /   │
│             │   │ (List-Unsub,     │   │  API, cursor)   │   │  footers, split│
│             │   │  List-ID, sender │   │                 │   │  into articles)│
│             │   │  heuristics)     │   │                 │   │                │
└─────────────┘   └──────────────────┘   └─────────────────┘   └───────┬────────┘
                                                                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          AI Extraction (OpenAI / OpenRouter)                  │
│   structured metadata → categories → entities → importance score             │
└───────────────────────────────────────┬──────────────────────────────────────┘
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│           Deduplication — embedding similarity + entity/time-window boost    │
│           (same story from 5 different newsletters ⇒ one canonical event)    │
└───────────────────────────────────────┬──────────────────────────────────────┘
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│        Knowledge Base — PostgreSQL + pgvector (events, entities, sources,    │
│        embeddings, taxonomy, conflicts, corrections, prompt versions)        │
└───────────────────────────────────────┬──────────────────────────────────────┘
                                          ▼
                    ┌─────────────────────────────────────────┐
                    │  Chat (RAG)  │ Timeline │ Categories │   │
                    │  Source Explorer │ Search │ Digest    │  │
                    └─────────────────────────────────────────┘
```

**Step by step:**

1. **Auth** — user signs in with Google OAuth (`gmail.readonly` scope only). Tokens are encrypted at rest ([`services/encryption.py`](backend/app/services/encryption.py)) using a Fernet key (`TOKEN_ENCRYPTION_KEY`), never stored in plaintext.
2. **Discovery** — [`services/newsletter_discovery.py`](backend/app/services/newsletter_discovery.py) scans the mailbox for newsletter senders using `List-Unsubscribe`/`List-ID` headers, known sender domains, and heuristics — personal email is excluded by default.
3. **Sync** — [`services/gmail_sync.py`](backend/app/services/gmail_sync.py) uses the Gmail History API so re-syncs are incremental (only new mail since the last cursor), not a full re-scan. Initial sync is capped by `INITIAL_SYNC_MAX_MESSAGES`.
4. **Parse** — [`services/newsletter_parser.py`](backend/app/services/newsletter_parser.py) / [`html_cleaner.py`](backend/app/services/html_cleaner.py) strip tracking pixels, footers and ads, then split a single email into individual article "issues."
5. **Extract** — [`services/ai_extraction.py`](backend/app/services/ai_extraction.py) calls the configured LLM to pull structured fields (title, summary, category, entities, importance) out of each article. Prompt versions are tracked in the DB ([`services/prompt_registry.py`](backend/app/services/prompt_registry.py)) so extraction quality changes are auditable.
6. **Deduplicate** — [`services/deduplication.py`](backend/app/services/deduplication.py) embeds each article (`EMBEDDING_MODEL`) and merges near-duplicate coverage of the same story from multiple newsletters into one canonical event, with conflict detection ([`services/conflict_detection.py`](backend/app/services/conflict_detection.py)) when sources disagree.
7. **Serve** — the frontend reads only from this processed knowledge base via `/api/v1/*`: conversational **Chat** (RAG over canonical events, [`services/chat.py`](backend/app/services/chat.py)), a filterable **Timeline**, **Category** views, a **Source Explorer**, keyword/entity **Search**, and a **Daily Digest**.

Two execution modes exist, controlled by env vars:
- **`SIMPLE_MODE=true`** (used in production) — lightweight per-article segmentation and chat, no multi-stage LLM pipeline, no Celery worker required.
- **`SIMPLE_MODE=false`** with **`USE_CELERY=true`** — full multi-stage pipeline (extraction → dedup → canonicalization → enrichment) runs as Celery background tasks, for self-hosted setups with a Redis worker.

## Services used

| Service | Role | Where it's configured |
|---|---|---|
| **Vercel** | Hosts the Next.js frontend, proxies `/api/v1/*` to the backend so the browser never needs the backend's raw hostname | Project env var `BACKEND_URL` |
| **Render** | Hosts the FastAPI backend (Docker web service) **and** a managed PostgreSQL database, deployed as one Blueprint from [`render.yaml`](render.yaml) | [render.yaml](render.yaml), Render dashboard env vars |
| **PostgreSQL + pgvector** | System of record: users, newsletters, articles, canonical events, embeddings, taxonomy, corrections. The `vector` extension is enabled automatically on startup ([`main.py`](backend/app/main.py)) | `DATABASE_URL` |
| **Redis + Celery** | Optional background job queue for the full pipeline mode and periodic sync (`celery beat`). Not used on the current Render free-tier deployment (`USE_CELERY=false`) | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| **Google Cloud OAuth + Gmail API** | Identity (`openid email profile`) and read-only mailbox access (`gmail.readonly`) — this is the *only* Google scope requested | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` |
| **OpenAI-compatible LLM API** | Structured extraction, embeddings, and chat. [`providers/openai_client.py`](backend/app/providers/openai_client.py) auto-routes to OpenRouter's endpoint when the key starts with `sk-or-`, otherwise talks to `api.openai.com` directly | `OPENAI_API_KEY`, `OPENAI_MODEL`, `EMBEDDING_MODEL`, `OPENAI_BASE_URL` (optional override) |
| **GitHub** | Source of truth + CI. Render and Vercel both auto-deploy from pushes to `master` | [.github/workflows/ci.yml](.github/workflows/ci.yml) |

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, React 19 |
| Backend | FastAPI, Python 3.12, async SQLAlchemy 2.0 |
| Database | PostgreSQL 16 + pgvector (via `pgvector/pgvector:pg16` image locally, Render Postgres in prod) |
| Queue (optional) | Redis 7 + Celery 5 |
| Auth | Google OAuth 2.0, JWT session tokens (`python-jose`), Fernet-encrypted refresh tokens at rest |
| AI | OpenAI SDK — works against OpenAI or OpenRouter (extraction, embeddings, chat) |
| Infra | Docker Compose (local), Render Blueprint (backend + DB), Vercel (frontend) |

## Local setup

### Prerequisites

- Docker & Docker Compose
- Node.js 20+ and npm
- Python 3.12+ (only if running the backend outside Docker)
- A Google Cloud project with OAuth credentials ([console.cloud.google.com](https://console.cloud.google.com))
- An OpenAI or OpenRouter API key

### 1. Google OAuth setup (one-time)

1. Create a project in Google Cloud Console → enable the **Gmail API**.
2. Create an **OAuth 2.0 Client ID** (type: Web application).
3. Add authorized redirect URI: `http://localhost:8000/api/v1/auth/callback`
4. Add authorized JavaScript origin: `http://localhost:3000`
5. Copy the Client ID and Client Secret.

### 2. Configure environment

```bash
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Fill in `backend/.env` with your Google OAuth credentials and LLM API key (see the [environment variables](#environment-variables) reference below for every field).

### 3a. Run everything with Docker (recommended)

```bash
docker compose up --build
```

This starts Postgres (with pgvector), Redis, and the API together, wired via the `docker-compose.yml` network. Tables are created automatically on boot (no migration step required — see [Troubleshooting](#troubleshooting)).

### 3b. Run services individually

```bash
docker compose up -d postgres redis
```

Backend (from `backend/`):
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Celery worker + beat (only needed if `USE_CELERY=true`, separate terminals):
```bash
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat --loglevel=info
```

Frontend (from `frontend/`):
```bash
npm install
npm run dev
```

Open **http://localhost:3000**.

## Environment variables

### Backend (`backend/.env`, see [`config.py`](backend/app/config.py) for full defaults)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://inboxiq:inboxiq@localhost:5432/inboxiq` | `postgres://`/`postgresql://` from Render/Railway are auto-normalized to the `asyncpg` driver |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | `redis://localhost:6379/{0,0,1}` | Only needed when `USE_CELERY=true` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | From Google Cloud Console |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/auth/callback` | **Must exactly match** the backend's actual public URL and be registered in Google Cloud Console |
| `JWT_SECRET_KEY` | `change-me-in-production` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `TOKEN_ENCRYPTION_KEY` | — | Fernet key for encrypting stored OAuth refresh tokens. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `OPENAI_API_KEY` | — | Accepts an OpenAI key or an OpenRouter key (`sk-or-...`, auto-detected) |
| `OPENAI_BASE_URL` | — | Explicit override, e.g. `https://openrouter.ai/api/v1` |
| `OPENAI_MODEL` / `EMBEDDING_MODEL` | `gpt-4o-mini` / `text-embedding-3-small` | |
| `FRONTEND_URL` | `http://localhost:3000` | Used for OAuth redirect-back and as a default CORS origin |
| `CORS_EXTRA_ORIGINS` | — | Comma-separated extra allowed origins (e.g. a Vercel preview URL) |
| `SIMPLE_MODE` | `true` | Lightweight pipeline mode — see [How it works](#how-it-works) |
| `USE_CELERY` | `false` | Set `true` only if a Redis worker is actually running |
| `INITIAL_SYNC_MAX_MESSAGES` | `2000` | Cap on messages scanned on first sync |
| `SYNC_INTERVAL_SECONDS` | `3600` | Background re-sync cadence (Celery beat mode only) |
| `ADMIN_SECRET` | — | Enables `/api/v1/ops/admin/*` endpoints, sent as header `X-Admin-Secret`. Leave empty to keep them disabled (404) |
| `API_RATE_LIMIT_RPM` | `120` | Per-IP request rate limit |
| `GMAIL_PUBSUB_TOPIC` / `GMAIL_WEBHOOK_SECRET` | — | Optional: real-time Gmail push notifications instead of polling |

### Frontend (`frontend/.env.local`, see [`lib/api-base.ts`](frontend/src/lib/api-base.ts))

| Variable | Where set | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | local dev only | If set, the browser calls the backend directly at this URL + `/api/v1` |
| `BACKEND_URL` | **Vercel project settings** (production) | Server-side only. The `[...path]/route.ts` proxy forwards browser calls to `${BACKEND_URL}/api/v1/...` so the backend's real hostname is never exposed to the client and CORS is a non-issue in prod |

## Production deployment

The app deploys as two independent pieces that must each be told about the other's final URL.

### Backend + database → Render

1. Push to `master` on [github.com/niyati-krinosai/inboxiq-app](https://github.com/niyati-krinosai/inboxiq-app).
2. On [Render](https://dashboard.render.com), **New → Blueprint**, connect the repo. Render reads [`render.yaml`](render.yaml) and provisions:
   - `inboxiq-db` — free managed Postgres (pgvector image is not needed here; the `CREATE EXTENSION vector` runs automatically in `main.py`'s lifespan on boot, and Render Postgres supports it).
   - `inboxiq-api` — Docker web service built from `backend/Dockerfile`, health-checked at `/health`.
3. Render will prompt for the `sync: false` secrets: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `OPENAI_API_KEY`, `ADMIN_SECRET`. `JWT_SECRET_KEY` and `TOKEN_ENCRYPTION_KEY` are auto-generated by the blueprint.
4. **Important:** Render assigns the service a slug like `inboxiq-api-xxxx.onrender.com` if the plain name is taken — check the actual assigned URL under the service's dashboard before setting `GOOGLE_REDIRECT_URI`, don't assume `inboxiq-api.onrender.com`. Set `GOOGLE_REDIRECT_URI` to `https://<actual-slug>.onrender.com/api/v1/auth/callback`.
5. In **Google Cloud Console → Credentials → your OAuth client**, add that same URL to **Authorized redirect URIs**. This step is manual and outside Render — a mismatch here causes `redirect_uri_mismatch` at login.
6. Auto-deploy is on by default (`autoDeploy: commit` on `master`) — every push redeploys.

### Frontend → Vercel

1. Import the same GitHub repo into Vercel, root directory `frontend/`.
2. Set project env var `BACKEND_URL` = `https://<actual-render-slug>.onrender.com` (no trailing slash, no `/api/v1` — the proxy route adds that).
3. Set `FRONTEND_URL` and `CORS_EXTRA_ORIGINS` on the **Render** service to the Vercel URL (e.g. `https://inboxiq-iota.vercel.app`) so CORS and the post-OAuth redirect target it correctly. (Render's CORS middleware also allows any `*.vercel.app` origin by regex, which covers preview deployments.)
4. Redeploy — env var changes on Vercel require a new deployment to take effect, saving alone isn't enough.

### Quick deploy helpers

- [`scripts/open-render-deploy.ps1`](scripts/open-render-deploy.ps1) — opens the Render Blueprint deploy page pre-filled with this repo.
- [`scripts/create-github-repo.ps1`](scripts/create-github-repo.ps1) — creates a fresh GitHub repo and pushes the current tree (only if `origin` isn't already set).
- [`scripts/deploy-vercel.ps1`](scripts/deploy-vercel.ps1) / [`scripts/deploy-production.ps1`](scripts/deploy-production.ps1) — Vercel/production deploy helpers.

## API reference

All routes are prefixed with `/api/v1`. Base URL in production: `https://inboxiq-api-q4en.onrender.com/api/v1`.

### Auth, sync & core features — [`api/routes.py`](backend/app/api/routes.py)

| Method | Path | Description |
|---|---|---|
| GET | `/auth/login` | Returns the Google OAuth consent URL |
| GET | `/auth/callback` | OAuth redirect target; exchanges code, creates session |
| GET | `/auth/me` | Current authenticated user |
| POST | `/auth/disconnect` | Revoke Gmail access, keep account |
| DELETE | `/auth/account` | Delete account and all associated data |
| GET | `/sync/status` | Current sync progress/state |
| POST | `/sync/trigger` | Kick off a sync (inline task if `USE_CELERY=false`) |
| POST | `/sync/process` | Process already-fetched messages |
| GET | `/newsletters` | List detected newsletters |
| GET | `/newsletters/{id}` | Newsletter detail |
| GET | `/newsletters/{id}/articles` | Articles from one newsletter |
| GET | `/timeline` | Filterable event feed (24h – 2 months) |
| GET | `/search` | Keyword/entity search over the knowledge base |
| POST | `/chat` | RAG chat over canonical events |
| GET | `/categories` | List categories for filtering |

### Intelligence — [`api/intelligence.py`](backend/app/api/intelligence.py)

| Method | Path | Description |
|---|---|---|
| GET | `/events/{event_id}` | Canonical event detail |
| GET | `/events/{event_id}/comparison` | Cross-source comparison of one story |
| GET | `/events/{event_id}/graph` | Entity/relationship graph for an event |
| GET | `/timeline/hierarchical` | Timeline grouped hierarchically |
| GET | `/companies/{company_name}` | Company-centric intelligence view |
| POST | `/research` | Deep research mode over the knowledge base |
| POST | `/ask-over-time` | Ask a question across a date range |
| GET | `/digest` | Daily digest |
| GET | `/analytics` | Usage/coverage analytics |
| GET | `/profile` | User interest profile |
| POST | `/activity` | Log user activity (personalization signal) |

### Knowledge management — [`api/knowledge.py`](backend/app/api/knowledge.py)

| Method | Path | Description |
|---|---|---|
| GET | `/events/{event_id}/history` | Version history of a canonical event |
| GET | `/events/{event_id}/history/{version}` | One specific version |
| GET | `/events/{event_id}/conflicts` | Detected conflicts between sources |
| POST | `/conflicts/{conflict_id}/resolve` | Resolve a source conflict |
| GET`/`POST | `/taxonomy` | List / create taxonomy categories |
| GET | `/taxonomy/{id}/events` | Events under a taxonomy node |
| GET`/`POST | `/prompts` | List / register prompt versions |
| POST | `/prompts/{name}/{version}/promote` | Promote a prompt version to active |
| POST | `/prompts/{name}/rollback` | Roll back to the previous prompt version |
| GET | `/connectors` | List available source connectors |
| GET | `/connectors/{source_type}/discover` | Discovery preview for a connector |
| POST | `/freshness/refresh` | Force a freshness/staleness recheck |

### Operations & admin — [`api/operations.py`](backend/app/api/operations.py)

| Method | Path | Description |
|---|---|---|
| GET | `/ops/pipeline` | Pipeline dashboard (all issues) |
| GET | `/ops/pipeline/{issue_id}` | Pipeline status for one issue |
| GET | `/ops/costs` | LLM cost tracking |
| GET | `/ops/model-versions` | Active model/prompt versions |
| POST | `/ops/eval/run` | Run the eval suite on demand |
| GET`/`POST | `/ops/corrections` | List / submit user corrections to extracted data |
| GET | `/ops/corrections/types` | Correction type taxonomy |
| GET | `/ops/retrieval-metrics` | Search/chat retrieval quality metrics |
| POST | `/ops/gmail/webhook` | Gmail Pub/Sub push notification receiver |
| POST | `/ops/gmail/watch` | Register a Gmail watch (push notifications) |
| GET | `/ops/admin/users` 🔒 | List users — requires `X-Admin-Secret` |
| POST | `/ops/admin/force-sync` 🔒 | Force-sync a user by email — requires `X-Admin-Secret` |

🔒 = disabled (404) unless `ADMIN_SECRET` is set on the backend; when set, requests must include header `X-Admin-Secret: <value>`.

## Operational scripts

Located in [`scripts/`](scripts/), mostly PowerShell + Python helpers used against the **production** Render deployment:

| Script | Purpose |
|---|---|
| `force_user_sync.py`, `trigger_remote_sync.py` | Trigger a sync for a specific user via `/ops/admin/*` (needs `ADMIN_SECRET`) |
| `list_users.py` | List registered users |
| `render_logs.ps1` | Tail Render service logs |
| `expose-api.ps1` | Expose the local backend for testing OAuth callbacks |
| `docker-up.ps1`, `start-local.ps1` | Local stack startup helpers |
| `fetch_tldr_for_user.py`, `fetch_all_tldr_yearly.py`, `list_tldr_products_in_gmail.py`, `probe_tldr_*.py`, `check_tldr_visibility.py`, `fix_tldr_article_links.py`, `reclassify_tldr_products.py` | TLDR-newsletter-specific ingestion/debugging utilities used to widen discovery coverage for that sender family |

## CI/CD

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push/PR to `main`/`master`:
1. Install backend dependencies.
2. `python -m compileall app` — compile check.
3. `python -m evals.run` — extraction/chat quality eval suite.
4. `pytest tests/ -v` — backend test suite.

Render and Vercel each watch `master` independently and redeploy on push; there is no separate CD job in this workflow.

## Design constraints

- **Read-only**: never modify, delete, send, or label emails.
- **Newsletter-only**: personal emails excluded by default via discovery heuristics.
- **Structured intelligence**: every answer comes from processed knowledge, never from raw email content directly.
- **Deduplication first**: the same story from multiple newsletters becomes one canonical event.
- **Transparency**: every answer links back to its newsletter and original source.
- **Incremental sync**: only new mail is processed after the initial import (Gmail History API cursor).

## Troubleshooting

- **`redirect_uri_mismatch` on login** — `GOOGLE_REDIRECT_URI` on the backend doesn't exactly match a URI registered in Google Cloud Console, or doesn't match the backend's actual deployed hostname (Render appends a random suffix if the plain name is taken).
- **Frontend can't reach the API in production** — check `BACKEND_URL` in Vercel project settings; it must be the bare Render URL (no `/api/v1`), and Vercel needs a fresh deploy after changing it.
- **No tables / DB errors on first boot** — there are no Alembic migrations; tables are created via `Base.metadata.create_all` in `main.py`'s lifespan on every startup. If this fails, check `DATABASE_URL` has a real hostname (a validator in `config.py` rejects a missing host) and that the `vector` extension can be created (Render/most managed Postgres allow this; some restricted hosts don't).
- **Admin endpoints return 404** — `ADMIN_SECRET` is empty; set it on the backend and pass it back as the `X-Admin-Secret` header.
- **Sync never progresses on Render free tier** — `USE_CELERY` should be `false` there (no worker process); `SIMPLE_MODE=true` runs sync inline via `BackgroundTasks` instead.

## License

MIT
