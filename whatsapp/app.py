from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from whatsapp.config import settings
from whatsapp.driver_manager import driver_manager
from whatsapp.sender import SendResult, sender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class SendMessageRequest(BaseModel):
    phone: str = Field(..., description="Телефон в любом формате, например +79001234567")
    text: str = Field(..., min_length=1, max_length=4096)


class SendMessageResponse(BaseModel):
    success: bool
    phone: str
    message_id: str | None = None
    error: str | None = None
    sent_at: str


class StatusResponse(BaseModel):
    logged_in: bool
    profile_dir: str
    headless: bool


def verify_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Неверный API-ключ")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("WhatsApp API запущен (профиль: %s)", settings.chrome_profile_dir)
    yield
    logger.info("Закрытие браузера...")
    driver_manager.close()


app = FastAPI(
    title="Podzamenu WhatsApp Selenium API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status", response_model=StatusResponse)
def status(_: None = Depends(verify_api_key)) -> StatusResponse:
    return StatusResponse(
        logged_in=driver_manager.is_logged_in(),
        profile_dir=str(settings.chrome_profile_dir),
        headless=settings.headless,
    )


@app.post("/send", response_model=SendMessageResponse)
def send_message(
    body: SendMessageRequest,
    _: None = Depends(verify_api_key),
) -> SendMessageResponse:
    try:
        result: SendResult = sender.send_text(body.phone, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = SendMessageResponse(
        success=result.success,
        phone=result.phone,
        message_id=result.message_id,
        error=result.error,
        sent_at=result.sent_at,
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=response.model_dump())
    return response


def main() -> None:
    import uvicorn

    uvicorn.run(
        "whatsapp.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
