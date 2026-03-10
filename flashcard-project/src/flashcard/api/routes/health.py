from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/health")
async def health_check(request: Request):
    try:
        client = request.app.state.mongo_client
        await client.admin.command("ping")
    except Exception:
        return JSONResponse(
            {"status": "unhealthy", "reason": "database unreachable"},
            status_code=503,
        )
    return {"status": "ok"}
