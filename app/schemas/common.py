from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class HealthResponse(BaseModel):
    """Health check diagnostic response."""
    status: str = Field(default="healthy", description="Application overall health status")
    database: str = Field(default="connected", description="Database connectivity status")
    environment: str = Field(..., description="Active runtime environment")
    version: str = Field(default="0.1.0", description="Application version")


class ApiResponse(BaseModel, Generic[DataT]):
    """Standard unified API response wrapper."""
    success: bool = True
    message: Optional[str] = None
    data: Optional[DataT] = None
