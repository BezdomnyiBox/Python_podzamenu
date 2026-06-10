from __future__ import annotations

import logging
import random
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from whatsapp.config import Settings, settings
from whatsapp.driver_manager import WhatsAppDriverError, WhatsAppNotLoggedInError, driver_manager
from whatsapp.phone import normalize_phone

logger = logging.getLogger(__name__)

SEND_BUTTON_SELECTORS = [
    "span[data-icon='send']",
    "button[aria-label='Send']",
    "button[aria-label='Отправить']",
    "div[aria-label='Send']",
    "div[aria-label='Отправить']",
]

MESSAGE_INPUT_SELECTORS = [
    "footer div[contenteditable='true'][data-tab='10']",
    "div[contenteditable='true'][data-tab='10']",
    "footer div[contenteditable='true']",
    "#main footer div[contenteditable='true']",
]

INVALID_NUMBER_MARKERS = [
    "phone number shared via url is invalid",
    "недействительный",
    "invalid",
]


@dataclass
class SendResult:
    success: bool
    phone: str
    message_id: str | None
    error: str | None
    sent_at: str


class WhatsAppSender:
    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        self._send_lock = threading.Lock()
        self._last_send_at = 0.0

    def send_text(self, phone: str, text: str) -> SendResult:
        normalized = normalize_phone(phone, self.cfg.allowed_country_codes)
        if not text or not text.strip():
            raise ValueError("Текст сообщения не может быть пустым")

        with self._send_lock:
            self._apply_rate_limit()
            try:
                driver_manager.ensure_logged_in()
                driver = driver_manager.get_driver()
                self._open_chat(driver, normalized, text)
                self._submit_message(driver, text)
                self._last_send_at = time.time()
                message_id = f"selenium_{normalized}_{int(self._last_send_at)}"
                return SendResult(
                    success=True,
                    phone=normalized,
                    message_id=message_id,
                    error=None,
                    sent_at=datetime.now(timezone.utc).isoformat(),
                )
            except WhatsAppNotLoggedInError as exc:
                return self._fail(normalized, str(exc))
            except (TimeoutException, WebDriverException, WhatsAppDriverError) as exc:
                logger.exception("Ошибка отправки WhatsApp")
                return self._fail(normalized, str(exc))

    def _fail(self, phone: str, error: str) -> SendResult:
        return SendResult(
            success=False,
            phone=phone,
            message_id=None,
            error=error,
            sent_at=datetime.now(timezone.utc).isoformat(),
        )

    def _apply_rate_limit(self) -> None:
        if self._last_send_at <= 0:
            return
        elapsed = time.time() - self._last_send_at
        delay = random.uniform(self.cfg.send_delay_min, self.cfg.send_delay_max)
        remaining = delay - elapsed
        if remaining > 0:
            logger.info("Пауза %.1f сек перед следующим сообщением", remaining)
            time.sleep(remaining)

    def _open_chat(self, driver, phone: str, text: str) -> None:
        encoded_text = urllib.parse.quote(text)
        url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_text}"
        driver.get(url)
        wait = WebDriverWait(driver, self.cfg.element_wait_timeout)

        try:
            wait.until(lambda d: self._chat_ready(d) or self._invalid_number_popup(d))
        except TimeoutException as exc:
            raise WhatsAppDriverError("Таймаут загрузки чата WhatsApp") from exc

        if self._invalid_number_popup(driver):
            raise WhatsAppDriverError(f"Номер {phone} недоступен в WhatsApp")

    def _chat_ready(self, driver) -> bool:
        for selector in MESSAGE_INPUT_SELECTORS:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                if element.is_displayed():
                    return True
            except Exception:
                continue
        return False

    def _invalid_number_popup(self, driver) -> bool:
        try:
            popup = driver.find_element(By.CSS_SELECTOR, "div[data-testid='popup-contents']")
            if not popup.is_displayed():
                return False
            body = popup.text.lower()
            return any(marker in body for marker in INVALID_NUMBER_MARKERS)
        except Exception:
            return False

    def _submit_message(self, driver, text: str) -> None:
        wait = WebDriverWait(driver, self.cfg.element_wait_timeout)
        input_box = None

        for selector in MESSAGE_INPUT_SELECTORS:
            try:
                input_box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                break
            except TimeoutException:
                continue

        if input_box is None:
            raise WhatsAppDriverError("Не найдено поле ввода сообщения")

        # URL уже подставил текст; Enter надёжнее кнопки Send при смене вёрстки.
        input_box.click()
        time.sleep(0.3)
        input_box.send_keys(Keys.ENTER)

        # Дополнительно пробуем клик по кнопке, если Enter не сработал.
        time.sleep(0.5)
        if self._message_still_in_input(driver, text):
            self._click_send_button(driver)

        time.sleep(0.5)

    def _message_still_in_input(self, driver, text: str) -> bool:
        for selector in MESSAGE_INPUT_SELECTORS:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                current = (element.text or element.get_attribute("innerText") or "").strip()
                if current and text.strip().startswith(current[: min(len(current), 20)]):
                    return True
            except Exception:
                continue
        return False

    def _click_send_button(self, driver) -> None:
        for selector in SEND_BUTTON_SELECTORS:
            try:
                button = driver.find_element(By.CSS_SELECTOR, selector)
                if button.is_displayed():
                    button.click()
                    return
            except Exception:
                continue
        raise WhatsAppDriverError("Не найдена кнопка отправки")


sender = WhatsAppSender()
