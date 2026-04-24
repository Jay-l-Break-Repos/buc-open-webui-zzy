"""
settings.py – Router for the user-facing settings pages.

Currently exposes:
  GET /settings/avatar  →  Avatar upload UI (HTML page)
"""

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import STATIC_DIR

router = APIRouter()

# Path to the pre-built HTML template
_TEMPLATE_PATH = Path(STATIC_DIR) / "templates" / "avatar_settings.html"


@router.get("/avatar", response_class=HTMLResponse, include_in_schema=False)
async def avatar_settings_page():
    """
    Serve the avatar-upload settings page.

    The page is a self-contained HTML/CSS/JS file that:
      - Shows the user's current avatar (or the default logo)
      - Lets the user pick a PNG, JPEG, or WebP image via file-picker or drag-and-drop
      - Validates format and size (≤ 5 MB) client-side before upload
      - Calls POST /api/v1/users/user/avatar with a Bearer token
      - Displays a live preview, upload progress, and success/error feedback
    """
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content=html)
