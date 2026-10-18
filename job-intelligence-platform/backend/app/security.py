import hmac
from fastapi import Header, HTTPException
from .config import settings

def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")):
    expected = settings.admin_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API is disabled until ADMIN_API_TOKEN is configured")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True
