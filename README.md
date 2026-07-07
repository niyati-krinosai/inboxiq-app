# InboxIQ

Transform your Gmail newsletter subscriptions into a searchable, conversational intelligence system.

**Gmail is only the ingestion layer.** The chatbot answers exclusively from structured knowledge extracted from newsletters — never from raw emails.

## Architecture

```
Gmail (read-only) → Discovery Engine → Incremental Sync → Parser
    → AI Extraction → Deduplication → Knowledge Base (PostgreSQL + pgvector)
    → Chat | Timeline | Categories | Source Explorer | Search
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python 3.12+ |
| Database | PostgreSQL + pgvector |
| Queue | Redis + Celery |
| Auth | Google OAuth 2.0 (read-only Gmail) |
| AI | OpenAI (extraction, embeddings, chat) |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Google Cloud OAuth credentials ([Console](https://console.cloud.google.com))
- OpenAI API key

### 1. Google OAuth Setup

1. Create a project in Google Cloud Console
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (Web application)
4. Add authorized redirect URI: `http://localhost:8000/api/v1/auth/callback`
5. Add authorized JavaScript origin: `http://localhost:3000`

### 2. Environment

```bash
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

Edit `backend/.env` with your Google OAuth and OpenAI credentials.

### 3. Start Services

```bash
docker compose up -d postgres redis
```

Start the backend (from `backend/`):

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Start Celery worker (separate terminal):

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

Start Celery beat for periodic sync:

```bash
celery -A app.workers.celery_app beat --loglevel=info
```

Start the frontend (from `frontend/`):

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Full Docker Stack

```bash
# Configure backend/.env first
docker compose up --build
```

## Core Features

- **Google OAuth** — Read-only Gmail access, automatic token refresh
- **Newsletter Discovery** — Multi-heuristic detection (List-Unsubscribe, List-ID, sender patterns, known domains)
- **Incremental Sync** — Gmail History API for efficient updates
- **HTML Parser** — Strips ads, footers, tracking; splits into articles
- **AI Extraction** — Structured metadata, categories, entities, importance scores
- **Deduplication** — Embedding-based clustering merges duplicate news
- **AI Chat** — RAG over knowledge base with structured responses
- **Timeline** — Filterable event feed (24h to 2 months)
- **Category Dashboard** — Filter timeline and chat by topic
- **Source Explorer** — Browse all detected newsletters
- **Search** — Keyword and entity search

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/auth/login` | Get Google OAuth URL |
| GET | `/api/v1/auth/callback` | OAuth callback |
| GET | `/api/v1/auth/me` | Current user |
| GET | `/api/v1/sync/status` | Sync status |
| POST | `/api/v1/sync/trigger` | Trigger manual sync |
| GET | `/api/v1/timeline` | Timeline events |
| GET | `/api/v1/search` | Search knowledge base |
| POST | `/api/v1/chat` | AI chat |
| GET | `/api/v1/newsletters` | List newsletters |
| GET | `/api/v1/categories` | List categories |

## Design Constraints

- **Read-only**: Never modify, delete, send, or label emails
- **Newsletter-only**: Personal emails excluded by default
- **Structured intelligence**: Answers from processed knowledge, not raw email
- **Deduplication first**: Same story from multiple sources = one event
- **Transparency**: Every answer includes newsletter and official source links
- **Incremental sync**: Only new newsletters processed after initial import

## Project Structure

```
InboxIQ/
├── backend/
│   ├── app/
│   │   ├── api/routes.py          # REST endpoints
│   │   ├── models/                # SQLAlchemy models
│   │   ├── services/
│   │   │   ├── gmail_sync.py      # Gmail History API sync
│   │   │   ├── newsletter_discovery.py
│   │   │   ├── newsletter_parser.py
│   │   │   ├── ai_extraction.py
│   │   │   ├── deduplication.py
│   │   │   ├── search.py
│   │   │   └── chat.py
│   │   └── workers/tasks.py       # Celery background jobs
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/                   # Next.js pages
│       ├── components/            # UI components
│       └── lib/                   # API client, utils
└── docker-compose.yml
```

## License

MIT
