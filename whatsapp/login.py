"""Первичная авторизация WhatsApp Web по QR-коду."""

from __future__ import annotations

import logging
import sys

from whatsapp.config import settings
from whatsapp.driver_manager import driver_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    print("=" * 60)
    print("WhatsApp Web — авторизация")
    print(f"Профиль Chrome: {settings.chrome_profile_dir}")
    print("=" * 60)
    print()
    print("1. Откроется Chrome с web.whatsapp.com")
    print("2. На телефоне: WhatsApp → Связанные устройства → Привязать")
    print("3. Отсканируйте QR-код")
    print()

    if settings.headless:
        print("ВНИМАНИЕ: WHATSAPP_HEADLESS=true — QR не будет виден.")
        print("Для первого входа установите WHATSAPP_HEADLESS=false")
        return 1

    try:
        driver_manager.get_driver()
        print("Ожидание авторизации (до 5 минут)...")
        if driver_manager.wait_for_login(timeout_sec=300):
            print()
            print("Авторизация успешна. Сессия сохранена в профиле Chrome.")
            print("Теперь можно запускать воркер или API:")
            print("  python -m whatsapp.worker")
            print("  python -m whatsapp.app")
            return 0

        print("Таймаут: QR не был отсканирован за 5 минут.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        return 130
    finally:
        driver_manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
