from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from whatsapp.paths import default_chrome_profile_dir, load_env_file

load_env_file()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    chrome_profile_dir: Path
    chrome_binary: str | None
    headless: bool
    api_host: str
    api_port: int
    api_key: str | None
    send_delay_min: float
    send_delay_max: float
    page_load_timeout: int
    element_wait_timeout: int
    allowed_country_codes: tuple[str, ...]
    crm_base_url: str | None
    crm_agent_id: str | None
    crm_agent_token: str | None
    crm_poll_interval_sec: float
    crm_request_timeout: int
    crm_batch_limit: int

    @classmethod
    def from_env(cls) -> Settings:
        profile = os.getenv("WHATSAPP_CHROME_PROFILE")
        profile_dir = Path(profile) if profile else default_chrome_profile_dir()

        codes = os.getenv("WHATSAPP_ALLOWED_COUNTRY_CODES", "7")
        return cls(
            chrome_profile_dir=profile_dir,
            chrome_binary=os.getenv("CHROME_BINARY") or None,
            headless=os.getenv("WHATSAPP_HEADLESS", "false").lower() in {"1", "true", "yes"},
            api_host=os.getenv("WHATSAPP_API_HOST", "127.0.0.1"),
            api_port=_env_int("WHATSAPP_API_PORT", 8765),
            api_key=os.getenv("WHATSAPP_API_KEY") or None,
            send_delay_min=_env_float("WHATSAPP_SEND_DELAY_MIN", 5.0),
            send_delay_max=_env_float("WHATSAPP_SEND_DELAY_MAX", 15.0),
            page_load_timeout=_env_int("WHATSAPP_PAGE_LOAD_TIMEOUT", 60),
            element_wait_timeout=_env_int("WHATSAPP_ELEMENT_WAIT_TIMEOUT", 30),
            allowed_country_codes=tuple(c.strip() for c in codes.split(",") if c.strip()),
            crm_base_url=(os.getenv("CRM_BASE_URL") or "").rstrip("/") or None,
            crm_agent_id=os.getenv("CRM_AGENT_ID") or None,
            crm_agent_token=os.getenv("CRM_AGENT_TOKEN") or None,
            crm_poll_interval_sec=_env_float("CRM_POLL_INTERVAL_SEC", 30.0),
            crm_request_timeout=_env_int("CRM_REQUEST_TIMEOUT", 30),
            crm_batch_limit=_env_int("CRM_BATCH_LIMIT", 5),
        )


settings = Settings.from_env()
