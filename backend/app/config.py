"""Configuration settings for Mintly Backend."""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Mintly"
    APP_ENV: str = "development"
    DEBUG: bool = True
    APP_SECRET_KEY: str = "mintly-dev-secret-key-must-be-changed-in-production-12345"
    PUBLIC_URL: str = "https://mintly.duckdns.org"

    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./mintly.db"

    # Worker & Scheduling
    WORKER_POLL_INTERVAL_SECONDS: int = 120
    WORKER_LEASE_DURATION_SECONDS: int = 30
    TIMEZONE: str = "Africa/Lagos"

    # Twikit & X Source
    TWIKIT_USERNAME: Optional[str] = None
    TWIKIT_EMAIL: Optional[str] = None
    TWIKIT_PASSWORD: Optional[str] = None
    TWIKIT_COOKIES_FILE: str = "./cookies.json"
    X_MONITORED_USER: str = "lakzonevn"

    # Free OpenSea drop API key, rotated by the server before its 7-day expiry.
    OPENSEA_KEY_FILE: str = "./opensea-key.json"

    # RPC Configuration
    RPC_ETHEREUM: str = "https://rpc.ankr.com/eth"
    RPC_BASE: str = "https://mainnet.base.org"
    RPC_SEPOLIA: str = "https://rpc.sepolia.org"
    RPC_BASE_SEPOLIA: str = "https://sepolia.base.org"

    # Signer Boundary
    SIGNER_MODE: str = "disabled"  # legacy signer code is not exposed to MetaMask users
    SIGNER_PRIVATE_KEY: Optional[str] = None
    ALLOW_LIVE_BROADCAST: bool = False
    CORS_ORIGINS: list[str] = []

    # Notifications
    FIREBASE_CREDENTIALS_FILE: Optional[str] = None
    ENABLE_LOCAL_NOTIFICATION_LOG: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
