from fastapi import APIRouter

router = APIRouter(tags=["health"])

# Marcador de despliegue: cambiar al publicar cambios críticos (smoke /health).
HEALTH_BUILD = "extract-damaged-failclosed-20260730"


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "build": HEALTH_BUILD}
