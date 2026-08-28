from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from .api.router import router

app = FastAPI(title="凿 agugent", version="0.1.0")
app.include_router(router)


@app.exception_handler(HTTPException)
async def api_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = dict(exc.detail) if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    code = detail.pop("code", f"HTTP_{exc.status_code}")
    message = detail.pop("message", str(exc.detail))
    return JSONResponse(status_code=exc.status_code,
                        content={"error": {"code": code, "message": message,
                                            "details": detail, "request_id": str(uuid4())}})


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "zao-agugent", "status": "ok"}
