import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from flashcard.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

@router.get("/health")
async def health_check(request: Request):
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check(request: Request):
    try:
        client = request.app.state.mongo_client
        await asyncio.wait_for(client.admin.command("ping"), timeout=3.0)
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        return JSONResponse(
            {"status": "unhealthy", "reason": "database unreachable"},
            status_code=503,
        )
    return {"status": "ready"}
