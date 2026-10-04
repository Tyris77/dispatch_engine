import asyncio
import uuid
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import generate_api_key, generate_webhook_secret
from app.db.base import Base
from app.main import app
from app.models.tenant import Tenant

# In-memory SQLite async test database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Create all tables in memory once for the test session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for test isolation."""
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP async test client with dependency override for database session."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def sample_tenant(db_session: AsyncSession) -> dict:
    """Fixture providing an active seeded tenant with known API credentials."""
    raw_api_key, api_key_hash = generate_api_key()
    webhook_secret = generate_webhook_secret()

    tenant = Tenant(
        id=uuid.uuid4(),
        name="Acme Operations",
        slug=f"acme-{uuid.uuid4().hex[:6]}",
        api_key_hash=api_key_hash,
        webhook_secret=webhook_secret,
        is_active=True,
        settings={
            "min_qualification_score": 0.5,
            "routing_rules": {
                "default_route": "general_sales",
                "high_priority_route": "executive_escalation",
            },
        },
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)

    return {
        "tenant": tenant,
        "raw_api_key": raw_api_key,
        "webhook_secret": webhook_secret,
    }
