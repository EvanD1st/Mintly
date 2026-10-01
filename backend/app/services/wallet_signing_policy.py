"""Keep contract experiments separate from supported browser authorization."""

from fastapi import HTTPException

from app.config import settings


MINT_SIGNING_UNAVAILABLE = (
    'Scheduled mint approval is unavailable with the current MetaMask integration. '
    'MetaMask blocks custom delegation and account-domain signatures from websites. '
    'No automatic mint was armed. Use Open on OpenSea in Mint plans and confirm '
    'the mint in MetaMask when the eligible stage opens.'
)


def require_browser_mint_signing():
    # Local contract tests use ephemeral keys. They do not establish browser
    # support. Production must reject the flow even if its old flags are enabled.
    if settings.APP_ENV == 'production':
        raise HTTPException(409, MINT_SIGNING_UNAVAILABLE)
