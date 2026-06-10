"""Пути к данным приложения (dev и собранный .exe)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Папка с .env: корень проекта (dev) или папка с .exe (сборка)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_chrome_profile_dir() -> Path:
    """Профиль Chrome: рядом с .exe или whatsapp/chrome_profile в dev."""
    if is_frozen():
        return app_dir() / "chrome_profile"
    return Path(__file__).resolve().parent / "chrome_profile"


def load_env_file() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    env_path = app_dir() / ".env"
    if env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()
