"""Фоновый воркер: опрос очереди CRM и отправка через WhatsApp Web."""

from __future__ import annotations

import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

from whatsapp.config import settings
from whatsapp.crm_client import CrmClient, CrmClientError, OutboxMessage
from whatsapp.driver_manager import driver_manager
from whatsapp.paths import app_dir, is_frozen
from whatsapp.sender import sender

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if is_frozen():
        log_dir = app_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "whatsapp_worker.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


_setup_logging()
logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0"
_running = True


def _handle_stop(signum: int, _frame) -> None:
    global _running
    logger.info("Получен сигнал %s, завершение...", signum)
    _running = False


def _process_message(crm: CrmClient, message: OutboxMessage) -> None:
    logger.info(
        "Отправка #%s → %s (попытка %s)",
        message.id,
        message.phone,
        message.attempts + 1,
    )
    try:
        result = sender.send_text(message.phone, message.text)
    except ValueError as exc:
        crm.ack_message(message.id, "failed", error=str(exc))
        logger.warning("Сообщение #%s отклонено: %s", message.id, exc)
        return

    if result.success:
        crm.ack_message(
            message.id,
            "sent",
            external_message_id=result.message_id,
            sent_at=result.sent_at,
        )
        logger.info("Сообщение #%s отправлено", message.id)
        return

    crm.ack_message(message.id, "failed", error=result.error or "Неизвестная ошибка")
    logger.warning("Сообщение #%s не отправлено: %s", message.id, result.error)


def run_worker() -> int:
    global _running

    try:
        crm = CrmClient()
    except CrmClientError as exc:
        logger.error("%s", exc)
        return 1

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    logger.info(
        "WhatsApp Worker запущен (агент=%s, CRM=%s, интервал=%.0f сек)",
        settings.crm_agent_id,
        settings.crm_base_url,
        settings.crm_poll_interval_sec,
    )
    logger.info("Профиль Chrome: %s", settings.chrome_profile_dir)

    while _running:
        try:
            logged_in = driver_manager.is_logged_in()
            crm.heartbeat(logged_in=logged_in, version=AGENT_VERSION)

            if not logged_in:
                logger.warning(
                    "WhatsApp не авторизован. Запустите: python -m whatsapp.login"
                )
            else:
                messages = crm.fetch_outbox()
                if messages:
                    logger.info("Получено сообщений из очереди: %s", len(messages))
                for message in messages:
                    if not _running:
                        break
                    _process_message(crm, message)

        except CrmClientError:
            logger.exception("Ошибка при обращении к CRM")
        except Exception:
            logger.exception("Неожиданная ошибка воркера")

        if not _running:
            break

        time.sleep(settings.crm_poll_interval_sec)

    logger.info("Закрытие браузера...")
    driver_manager.close()
    logger.info("WhatsApp Worker остановлен")
    return 0


def main() -> None:
    raise SystemExit(run_worker())


if __name__ == "__main__":
    main()
