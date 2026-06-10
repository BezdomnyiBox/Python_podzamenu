from __future__ import annotations

import re


def normalize_phone(phone: str, allowed_country_codes: tuple[str, ...] = ("7",)) -> str:
    """Приводит номер к формату для WhatsApp Web: только цифры, международный."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""

    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    if len(digits) == 10 and "7" in allowed_country_codes:
        digits = "7" + digits

    if allowed_country_codes and not any(digits.startswith(code) for code in allowed_country_codes):
        raise ValueError(f"Номер не соответствует разрешённым кодам стран: {allowed_country_codes}")

    if len(digits) < 10:
        raise ValueError("Слишком короткий номер телефона")

    return digits
