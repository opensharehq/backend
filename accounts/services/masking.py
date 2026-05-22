"""Utility functions for masking sensitive data in API responses."""

from __future__ import annotations


def mask_name(name: str) -> str:
    """
    Mask a person's name for display.

    Rules:
        - 3+ chars: show first and last, middle replaced with *
        - 2 chars: show first + *
        - 1 char or empty: return as-is
    """
    if not name:
        return name
    length = len(name)
    if length >= 3:
        return name[0] + "*" * (length - 2) + name[-1]
    if length == 2:
        return name[0] + "*"
    return name


def mask_card(value: str) -> str:
    """
    Mask a card/phone/ID number showing first 3 and last 3 chars.

    Examples:
        - "13812345678" → "138*****678"
        - "320123199001011234" → "320************234"
        - "6222021234567890" → "622**********890"

    """
    if not value:
        return value
    length = len(value)
    if length <= 6:
        return value
    return value[:3] + "*" * (length - 6) + value[-3:]
