# Backend Intelligence Pipeline

The frontend is unchanged. All intelligence runs in the backend via a phased pipeline.

## Pipeline Phases

```
Phase 1  OAuth (read-only Gmail) → encrypted token storage
Phase 2  Newsletter discovery (headers + heuristics, ignore personal email)
Phase 3  Historical import (raw HTML + headers only, no AI)
Phase 4  HTML cleaning (strip ads, images, footers, tracking)
Phase 5  Article segmentation (1 newsletter → N articles)
Phase 6  AI extraction (structured JSON per article)
Phase 7  Embeddings (pgvector)
Phase 8  Deduplication (embedding + entity + time proximity)
Phase 9  Knowledge graph (entity relationships)
         + Source enrichment (official URLs, GitHub, docs)
Phase 10 Timeline API
Phase 11 Chat (intent → vector search → rerank → generate)
Phase 12 Search (keyword + semantic + entity)
Phase 13 Source explorer API
Phase 14 Hourly Celery worker (History API incremental sync)
Phase 15 Production (encryption, retries, disconnect, delete account)
```

## Key Services

| Service | File |
|---------|------|
| Google OAuth | `app/services/google_oauth.py` |
| Newsletter discovery | `app/services/newsletter_discovery.py` |
| Newsletter registry | `app/services/newsletter_registry.py` |
| Gmail sync (import only) | `app/services/gmail_sync.py` |
| HTML cleaning | `app/services/html_cleaner.py` |
| Article segmentation | `app/services/article_segmentation.py` |
| Intelligence pipeline | `app/services/pipeline.py` |
| AI extraction | `app/services/ai_extraction.py` |
| Source enrichment | `app/services/source_enrichment.py` |
| Deduplication | `app/services/deduplication.py` |
| Knowledge graph | `app/services/knowledge_graph.py` |
| Vector search | `app/services/search.py` |
| Chat + reranker | `app/services/chat.py`, `app/services/reranker.py` |

## Workers

```bash
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat --loglevel=info
```

- `sync_user_gmail` — Phase 3 import (triggers pipeline)
- `run_intelligence_pipeline` — Phases 4-9
- `sync_all_users` — hourly via beat schedule

## New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/disconnect` | Revoke Gmail, clear tokens |
| DELETE | `/auth/account` | Delete all data + account |
| GET | `/newsletters/{id}` | Newsletter detail with sync status |

## Environment

```bash
cp .env.example .env
# Required: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, TOKEN_ENCRYPTION_KEY, OPENAI_API_KEY
```

Generate encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Architectural Note: Source Enrichment

Newsletters are the **discovery layer**. For each article, InboxIQ:
1. Extracts the official URL from the newsletter
2. Fetches official blog / GitHub release / documentation
3. Merges enriched content into the canonical knowledge object

## Phases 16-25: Intelligence Quality

| Phase | Feature | Service |
|-------|---------|---------|
| 16 | Event canonicalization, confidence, breaking news, ranking | `event_canonicalization.py`, `confidence.py`, `breaking_news.py`, `importance_ranking.py` |
| 17 | Personalized interest profile | `personalization.py` |
| 18 | Chat session memory | `chat_memory.py` |
| 19 | Cross-newsletter comparison | `comparison.py` |
| 20 | Newsletter analytics | `analytics.py` |
| 21 | Hierarchical AI timeline | `ai_timeline.py` |
| 22 | Company intelligence pages | `company_intelligence.py` |
| 23 | AI research mode | `research_mode.py` |
| 24 | Daily digest | `daily_digest.py` |
| 25 | Event-centric intelligence graph | `intelligence_graph.py` |
| — | Ask Over Time (longitudinal queries) | `ask_over_time.py` |

### Intelligence API (`/api/v1/intelligence/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/events/{id}` | Full canonical event |
| GET | `/events/{id}/comparison` | Cross-newsletter coverage |
| GET | `/events/{id}/graph` | Event-centric graph |
| GET | `/timeline/hierarchical` | Month → Week → Day → Hour |
| GET | `/companies/{name}` | Company intelligence |
| POST | `/research` | AI research report |
| POST | `/ask-over-time` | Longitudinal synthesis |
| GET | `/digest` | Daily personalized digest |
| GET | `/analytics` | Newsletter analytics |
| GET | `/profile` | Interest profile |
| POST | `/activity` | Track clicks/searches |

### Chat upgrades

- Retrieves **canonical events**, not raw articles
- `session_id` for conversational memory
- Auto-detects longitudinal questions → Ask Over Time engine
- Returns `verification`, `confidence_score`, `is_breaking`, `is_trending`

## Operational Infrastructure

| # | Feature | Location |
|---|---------|----------|
| 1 | Pipeline stage tracing | `core/pipeline_tracer.py`, `models/operations.py` |
| 2 | Pipeline dashboard | `GET /ops/pipeline`, `GET /ops/pipeline/{issue_id}` |
| 3 | LLM cost tracking | `services/llm_cost.py`, `GET /ops/costs` |
| 4 | Quality eval suite | `evals/fixtures.json`, `POST /ops/eval/run` |
| 5 | Human corrections | `POST /ops/corrections` |
| 6 | Retrieval metrics | `GET /ops/retrieval-metrics` |
| 7 | Multi-LLM providers | `app/providers/` |
| 8 | Model versioning | `GET /ops/model-versions`, stored in `metadata_json` |
| 9 | Security | OAuth CSRF state, API rate limiting, encrypted tokens |
| 10 | Gmail push | `POST /ops/gmail/webhook`, `POST /ops/gmail/watch` |

### Pipeline trace stages

`discovery → import → clean → segment → extract → embed → deduplicate → canonicalize → enrich → graph → stored`

Each stage records: start/end time, duration, tokens, cost, failure reason, retry count, model + prompt version.

### Run eval suite

```bash
cd backend && python evals/run.py
```
