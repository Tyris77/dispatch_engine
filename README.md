# Multi-Tenant Operations & Dispatch Engine

Production-grade FastAPI application engineered for high-throughput webhook ingestion, tenant isolation, LLM-driven lead qualification, dispatch routing, and CRM synchronization.

---

## Architecture Overview

- **FastAPI**: Async ASGI web framework with OpenAPI / Swagger documentation.
- **SQLAlchemy 2.0 (Async)**: Modern async ORM supporting PostgreSQL (`asyncpg`) and SQLite (`aiosqlite`).
- **Alembic**: Database migrations and schema version management.
- **Multi-Tenancy**: Tenant-scoped records (`TenantScopedMixin`) with API key and HMAC webhook signature authentication.
- **Pydantic v2**: High-performance schema validation and LLM structured outputs.
- **Service Layer**: Separation of concerns across Lead Qualification, Dispatch Routing, and CRM Synchronization.

---

## Directory Structure

```
app/
├── api/
│   ├── deps.py               # Dependency injection (DB session, Tenant resolution, Auth)
│   └── v1/
│       ├── router.py         # Consolidated v1 API router
│       ├── health.py         # GET /health & DB ping
│       ├── tenants.py        # Tenant onboarding and management
│       ├── webhooks.py       # Webhook ingestion & signature validation
│       └── events.py         # Lead actions & event query
├── core/
│   ├── config.py             # Pydantic Settings & environment variables
│   ├── logging.py            # Structured logging setup
│   └── security.py           # HMAC SHA-256 signature validation & API key hashing
├── db/
│   ├── base.py               # DeclarativeBase, UUIDPrimaryKeyMixin, TenantScopedMixin
│   └── session.py            # Async engine & sessionmaker factory
├── models/
│   ├── tenant.py             # Tenant ORM model
│   ├── webhook_event.py      # WebhookEvent ORM model
│   └── lead_action.py        # LeadAction ORM model
├── schemas/
│   ├── common.py             # HealthResponse, generic API envelope
│   ├── tenant.py             # Tenant creation, read, update schemas
│   ├── webhook.py            # Inbound webhook payload and event schemas
│   └── lead.py               # LLM structured output schemas & dispatch plans
└── services/
    ├── qualification.py      # Lead scoring & qualification service
    ├── dispatch.py           # Multi-tenant routing & dispatch service
    └── crm_sync.py           # External CRM sync adapter (HubSpot, Salesforce, webhooks)
```

---

## Quickstart

### 1. Setup Environment
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and configure your database and API keys:
```bash
cp .env.example .env
```

### 3. Run Migrations
```bash
alembic upgrade head
```

### 4. Start Development Server
```bash
uvicorn app.main:app --reload --port 8000
```
Interactive API docs will be accessible at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

---

## Running Tests
```bash
pytest
```
