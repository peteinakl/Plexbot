from __future__ import annotations

import os
import stat
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
POSTER_CACHE_DIR = DATA_DIR / "posters"
DB_PATH = DATA_DIR / "plexbot.db"
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"

APP_NAME = "Plexbot"
APP_VERSION = "1.0.0"
DEFAULT_HOST = os.environ.get("PLEXBOT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("PLEXBOT_PORT", "8765"))


def ensure_data_dirs() -> None:
    """Create local data directories with owner-only permissions for token safety."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, stat.S_IRWXU)
    except OSError:
        pass
