"""Technology metadata API (Java TechnologyController parity)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/technology", tags=["Technology"])

_TECHNOLOGIES = ["AI", "Blockchain", "Web Development"]


@router.get("/categories")
async def list_technology_categories() -> list[str]:
    return list(_TECHNOLOGIES)


@router.get("/test")
async def technology_health() -> str:
    return "WORKING"
