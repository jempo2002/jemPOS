from __future__ import annotations

import re


def avatar_iniciales(nombre: str) -> str:
    """Return initials for profile avatar fallback."""
    partes = nombre.strip().split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[1][0]).upper()
    if partes:
        return partes[0][:2].upper()
    return "??"


def fmt_money(value: float) -> str:
    """Simple COP formatting for UI labels."""
    return f"${int(round(value)):,}".replace(",", ".")


def normalize_payment_method(raw_method: str | None, allow_fiado: bool = False) -> str | None:
    """Normalize payment methods from UI/API to the DB canonical values."""
    key = str(raw_method or "").strip().lower()
    mapping = {
        "efectivo": "Efectivo",
        "nequi": "Nequi/Daviplata",
        "nequi/daviplata": "Nequi/Daviplata",
        "tarjeta": "Tarjeta",
        "fiado": "fiado",
    }
    value = mapping.get(key)
    if value == "fiado" and not allow_fiado:
        return None
    return value


def only_digits(raw_value: str | None, max_len: int | None = None) -> str:
    """Keep only digits from user input with optional max length."""
    digits = re.sub(r"\D", "", str(raw_value or "").strip())
    if max_len is not None:
        digits = digits[:max_len]
    return digits


def normalize_phone(raw_value: str | None, max_len: int = 10) -> str | None:
    """Return normalized phone digits or None when empty."""
    digits = only_digits(raw_value, max_len=max_len)
    return digits or None
