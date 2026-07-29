from fastapi import APIRouter

router = APIRouter(tags=["health"])

# Marcador de despliegue: cambiar al publicar cambios críticos (smoke /health).
HEALTH_BUILD = "prod-paths-probe-20260729"


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "build": HEALTH_BUILD}
