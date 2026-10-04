from fastapi import APIRouter, status
from app.core.config import settings
from app.db.session import check_db_connection
from app.schemas.common import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check probe",
    description="Check application and database health status.",
)
async def health_check() -> HealthResponse:
    is_db_connected = await check_db_connection()
    db_status = "connected" if is_db_connected else "disconnected"

    return HealthResponse(
        status="healthy" if is_db_connected else "degraded",
        database=db_status,
        environment=settings.ENVIRONMENT,
        version="0.1.0",
    )
