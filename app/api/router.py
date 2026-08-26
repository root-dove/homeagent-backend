from fastapi import APIRouter

from app.api.v1.cleanliness import router as cleanliness_router
from app.api.v1.devices import router as devices_router
from app.api.v1.health import router as health_router
from app.api.v1.modes import router as modes_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(modes_router, prefix="/modes", tags=["modes"])
api_router.include_router(cleanliness_router, prefix="/modes", tags=["cleanliness"])
api_router.include_router(devices_router, prefix="/devices", tags=["devices"])
