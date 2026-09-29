"""Mintly FastAPI Application Entrypoint."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.services.seed import seed_initial_data
from app.api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    # Initialize DB schema
    await init_db()
    # Seed initial demo reference data
    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Mintly - Personal NFT discovery and scheduled minting server",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for Flutter Android / Web / Local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": "1.0.0",
        "tagline": "Your next mint. Already planned.",
        "timezone": settings.TIMEZONE,
    }


@app.get("/healthz")
async def health_check():
    return {"status": "ok", "env": settings.APP_ENV}
