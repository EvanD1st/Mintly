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
    RPC_ETHEREUM: str = "https://ethereum-rpc.publicnode.com"
    RPC_BASE: str = "https://mainnet.base.org"
    RPC_ROBINHOOD: str = "https://rpc.mainnet.chain.robinhood.com"
    RPC_ARBITRUM: str = "https://arb1.arbitrum.io/rpc"
    RPC_OPTIMISM: str = "https://mainnet.optimism.io"
    RPC_SEPOLIA: str = "https://rpc.sepolia.org"
    RPC_BASE_SEPOLIA: str = "https://sepolia.base.org"

    # Signer Boundary
    SIGNER_MODE: str = "disabled"  # legacy signer code is not exposed to MetaMask users
    SIGNER_PRIVATE_KEY: Optional[str] = None
    ALLOW_LIVE_BROADCAST: bool = False
    MINT_RELAYER_KEY_FILE: str = "/run/opensea/mint-relayer.key"
    ENABLE_MINT_PERMISSIONS: bool = False
    ENABLE_DIRECT_WALLET_GAS: bool = False
    ENABLE_DIRECT_WALLET_BROADCAST: bool = False
    # Explicit custody, separate from blocked MetaMask permission experiments.
    ENABLE_CUSTODIAL_AUTOMATIC: bool = False
    ENABLE_CUSTODY_IMPORT: bool = False
    AUTOMATIC_CHAIN_ID: int = 31337
    ENABLE_ROBINHOOD_AUTOMATIC: bool = False  # separate explicit mainnet opt-in
    AUTOMATIC_RPC: str = 'http://127.0.0.1:18545'
    AUTOMATIC_SIGNER_URL: str = 'http://127.0.0.1:18766'
    AUTOMATIC_SIGNER_TOKEN_FILE: str = ''
    CUSTODY_VAULT_DIR: str = ''  # mounted only in signer container
    CUSTODY_PASSWORD_FILE: str = ''  # independent runtime secret mount
    CUSTODY_JOURNAL_FILE: str = ''  # signer-only durable journal
    AUTOMATIC_CONFIRMATIONS: int = 2
    AUTOMATIC_POLL_SECONDS: float = 0.5
    MINT_BUNDLER_CONFIG_FILE: str = "/run/opensea/mint-bundlers.json"
    MINT_RELAYER_MAX_FEE_WEI: int = 1000000000000000
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
