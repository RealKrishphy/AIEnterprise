from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lumen.api import router
from lumen.documents import router as documents_router

app = FastAPI(title="Lumen API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.include_router(router)
app.include_router(documents_router)


@app.get("/health/live", tags=["health"])
async def liveness():
    return {"status": "ok"}
