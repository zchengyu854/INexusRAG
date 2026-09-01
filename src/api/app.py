from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.api.schemas import HealthResponse

app = FastAPI(
    title="NexusRAG",
    description="多文档智能问答系统 — 学习路径用 FastAPI 后端模板",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", include_in_schema=False)
async def root():
    return HealthResponse()
