"""Mintly FastAPI Application Entrypoint."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.api import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    if settings.APP_ENV == "production":
        if settings.DEBUG or len(settings.APP_SECRET_KEY) < 32 or settings.APP_SECRET_KEY.startswith(("mintly-dev", "change-this")):
            raise RuntimeError("Production requires DEBUG=false and a random APP_SECRET_KEY of at least 32 characters.")
    # Initialize DB schema
    await init_db()
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
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.middleware("http")
async def prevent_sensitive_response_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/auth/", "/api/admin/", "/api/wallet-link/", "/api/mint-permission")):
        response.headers["Cache-Control"] = "no-store"
    return response

_web_dir = Path(__file__).parent / "web"
_connect_headers = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
}


@app.get("/connect", include_in_schema=False)
async def connect_wallet_page():
    return FileResponse(_web_dir / "connect.html", media_type="text/html", headers=_connect_headers)


@app.get("/connect.js", include_in_schema=False)
async def connect_wallet_script():
    return FileResponse(_web_dir / "connect.js", media_type="application/javascript", headers=_connect_headers)


@app.get('/authorize-mint',include_in_schema=False)
async def authorize_mint_page():
    return FileResponse(_web_dir/'authorize-mint.html',media_type='text/html',headers=_connect_headers)


@app.get('/authorize-mint.js',include_in_schema=False)
async def authorize_mint_script():
    return FileResponse(_web_dir/'authorize-mint.js',media_type='application/javascript',headers=_connect_headers)


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


@app.get('/wallet-capabilities', include_in_schema=False)
async def wallet_capabilities_page():
    return FileResponse(_web_dir / 'wallet-capabilities.html', media_type='text/html', headers=_connect_headers)


@app.get('/wallet-capabilities.js', include_in_schema=False)
async def wallet_capabilities_script():
    return FileResponse(_web_dir / 'wallet-capabilities.js', media_type='application/javascript', headers=_connect_headers)
