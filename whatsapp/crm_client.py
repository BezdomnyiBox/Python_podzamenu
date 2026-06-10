from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import requests

from whatsapp.config import Settings, settings

logger = logging.getLogger(__name__)

AckStatus = Literal["sent", "failed"]


@dataclass(frozen=True)
class OutboxMessage:
    id: int
    phone: str
    text: str
    attempts: int = 0
    order_id: int | None = None


class CrmClientError(Exception):
    pass


class CrmClient:
    """HTTP-клиент очереди WhatsApp на стороне CRM (Symfony)."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        if not self.cfg.crm_base_url:
            raise CrmClientError("CRM_BASE_URL не задан в .env")
        if not self.cfg.crm_agent_id:
            raise CrmClientError("CRM_AGENT_ID не задан в .env")
        if not self.cfg.crm_agent_token:
            raise CrmClientError("CRM_AGENT_TOKEN не задан в .env")

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.cfg.crm_agent_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Podzamenu-WhatsApp-Agent/1.0",
            }
        )

    def fetch_outbox(self, limit: int | None = None) -> list[OutboxMessage]:
        batch_limit = limit if limit is not None else self.cfg.crm_batch_limit
        url = f"{self.cfg.crm_base_url}/api/whatsapp/outbox"
        params = {
            "agent_id": self.cfg.crm_agent_id,
            "limit": batch_limit,
        }
        data = self._request("GET", url, params=params)
        raw_messages = data.get("messages", [])
        return [self._parse_message(item) for item in raw_messages]

    def ack_message(
        self,
        message_id: int,
        status: AckStatus,
        *,
        external_message_id: str | None = None,
        error: str | None = None,
        sent_at: str | None = None,
    ) -> None:
        url = f"{self.cfg.crm_base_url}/api/whatsapp/outbox/{message_id}/ack"
        payload: dict[str, Any] = {"status": status}
        if external_message_id:
            payload["message_id"] = external_message_id
        if error:
            payload["error"] = error
        if sent_at:
            payload["sent_at"] = sent_at
        self._request("POST", url, json=payload)

    def heartbeat(self, *, logged_in: bool, version: str = "1.0") -> None:
        url = f"{self.cfg.crm_base_url}/api/whatsapp/agent/heartbeat"
        payload = {
            "agent_id": self.cfg.crm_agent_id,
            "logged_in": logged_in,
            "version": version,
        }
        try:
            self._request("POST", url, json=payload)
        except CrmClientError:
            logger.warning("Не удалось отправить heartbeat в CRM", exc_info=True)

    def _parse_message(self, item: dict[str, Any]) -> OutboxMessage:
        try:
            return OutboxMessage(
                id=int(item["id"]),
                phone=str(item["phone"]),
                text=str(item["text"]),
                attempts=int(item.get("attempts", 0)),
                order_id=int(item["order_id"]) if item.get("order_id") is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CrmClientError(f"Некорректный формат сообщения из CRM: {item}") from exc

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=json,
                timeout=self.cfg.crm_request_timeout,
            )
        except requests.RequestException as exc:
            raise CrmClientError(f"Ошибка сети при запросе {url}: {exc}") from exc

        if response.status_code == 204:
            return {}

        if not response.ok:
            detail = response.text[:500]
            raise CrmClientError(f"CRM ответил {response.status_code}: {detail}")

        if not response.content:
            return {}

        try:
            body = response.json()
        except ValueError as exc:
            raise CrmClientError(f"CRM вернул не-JSON: {response.text[:200]}") from exc

        if not isinstance(body, dict):
            raise CrmClientError("CRM вернул JSON не в виде объекта")
        return body
