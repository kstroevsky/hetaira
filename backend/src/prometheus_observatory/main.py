from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401
from .api import router
from .codebooks import register_codebooks
from .config import get_settings
from .database import Base, SessionLocal, engine
from .seed import seed_demo


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        register_codebooks(session)
        if get_settings().seed_demo:
            seed_demo(session)
    yield


settings = get_settings()
app = FastAPI(
    title="Prometheus Observatory API",
    version="0.1.0",
    description="Evidence-first, Russian-first computational conversation observatory.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
