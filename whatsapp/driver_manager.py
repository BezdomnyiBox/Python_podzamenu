from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from whatsapp.config import Settings, settings

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

logger = logging.getLogger(__name__)

WHATSAPP_URL = "https://web.whatsapp.com"


class WhatsAppDriverError(Exception):
    pass


class WhatsAppNotLoggedInError(WhatsAppDriverError):
    pass


class WhatsAppDriverManager:
    """Один браузер на процесс, потокобезопасный доступ через lock."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        self._driver: WebDriver | None = None
        self._lock = threading.RLock()
        self._last_activity = 0.0
        self.cfg.chrome_profile_dir.mkdir(parents=True, exist_ok=True)

    def get_driver(self) -> WebDriver:
        with self._lock:
            if self._driver is None:
                self._driver = self._create_driver()
                self._open_whatsapp()
            return self._driver

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                try:
                    self._driver.quit()
                except WebDriverException:
                    logger.exception("Ошибка при закрытии браузера")
                finally:
                    self._driver = None

    def is_logged_in(self) -> bool:
        with self._lock:
            try:
                driver = self.get_driver()
            except WhatsAppDriverError:
                return False
            return self._check_logged_in(driver)

    def wait_for_login(self, timeout_sec: int = 300) -> bool:
        """Ждёт QR-логин после первого запуска."""
        driver = self.get_driver()
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self._check_logged_in(driver):
                return True
            time.sleep(2)
        return False

    def _create_driver(self) -> WebDriver:
        options = Options()
        options.add_argument(f"--user-data-dir={self.cfg.chrome_profile_dir}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=ru-RU")

        if self.cfg.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1280,900")

        if self.cfg.chrome_binary:
            options.binary_location = self.cfg.chrome_binary

        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        try:
            driver = webdriver.Chrome(options=options)
        except WebDriverException as exc:
            raise WhatsAppDriverError(
                "Не удалось запустить Chrome. Установите Google Chrome и chromedriver "
                "(selenium 4+ подтягивает его автоматически)."
            ) from exc

        driver.set_page_load_timeout(self.cfg.page_load_timeout)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """
            },
        )
        return driver

    def _open_whatsapp(self) -> None:
        driver = self._driver
        assert driver is not None
        driver.get(WHATSAPP_URL)
        WebDriverWait(driver, self.cfg.element_wait_timeout).until(
            lambda d: self._check_logged_in(d) or self._check_qr_visible(d)
        )

    def _check_qr_visible(self, driver: WebDriver) -> bool:
        try:
            driver.find_element(By.CSS_SELECTOR, "canvas[aria-label], div[data-ref]")
            return True
        except Exception:
            return False

    def _check_logged_in(self, driver: WebDriver) -> bool:
        """Сессия активна, если видна панель чатов."""
        selectors = [
            "div#pane-side",
            "div[data-testid='chat-list']",
            "header[data-testid='chatlist-header']",
        ]
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                if element.is_displayed():
                    return True
            except Exception:
                continue
        return False

    def ensure_logged_in(self) -> None:
        driver = self.get_driver()
        if not self._check_logged_in(driver):
            raise WhatsAppNotLoggedInError(
                "WhatsApp Web не авторизован. Запустите: python -m whatsapp.login"
            )


driver_manager = WhatsAppDriverManager()
