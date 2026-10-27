"""PII redaction applied to transcripts before they are stored.

Removes what a caller commonly says out loud that should not sit in a log: email
addresses (written or spoken: "name at gmail dot com"), phone numbers, payment card
numbers, Indian Aadhaar numbers (Verhoeff-checked) and PAN. A 14 to 19 digit run that
fails the card checksum is still removed (as ``[number]``): speech recognition mishears
digits, and a card number with one digit wrong is still a card number. Shorter order and
booking numbers survive. Each match becomes a typed placeholder
such as ``[phone]`` so a transcript still reads naturally.

Speech recognition writes numbers in many shapes ("98765 43210", "9 8 7 6..."); the
patterns accept spaces and dashes between digit groups.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# Speech recognition writes addresses as spoken: "priya at gmail dot com".
_SPOKEN_EMAIL = re.compile(r"\b[\w.+-]+\s+at\s+[\w-]+(?:\s+dot\s+[a-z]{2,})+\b", re.IGNORECASE)
# PAN in any case when written together; spaced ("ABCDE 1234 F") only in capitals, so
# ordinary words around a number ("table 2024 a") are left alone.
_PAN = re.compile(r"\b(?:[A-Za-z]{5}[0-9]{4}[A-Za-z]|[A-Z]{5} [0-9]{4} [A-Z])\b")
# 12 digits in groups of four (Aadhaar), 13 to 19 digits (cards), then phone shapes.
_DIGITS = re.compile(r"(?<![\w])(?:\+?\d[\d\s-]{7,22}\d)(?![\w])")

# Verhoeff tables (Aadhaar's check digit).
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_ok(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def luhn_ok(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _classify(digits: str) -> str | None:
    n = len(digits)
    if n == 12 and digits[0] not in "01" and verhoeff_ok(digits):
        return "[aadhaar]"
    if 13 <= n <= 19 and luhn_ok(digits):
        return "[card]"
    if 10 <= n <= 13:
        return "[phone]"
    if 14 <= n <= 19:
        # A card number with a digit misheard fails Luhn but is still a card number.
        return "[number]"
    return None


def redact(text: str | None) -> str | None:
    if not text:
        return text
    out = _EMAIL.sub("[email]", text)
    out = _SPOKEN_EMAIL.sub("[email]", out)
    out = _PAN.sub("[pan]", out)

    def digits(m: re.Match[str]) -> str:
        found = re.sub(r"\D", "", m.group(0))
        label = _classify(found)
        return label if label else m.group(0)

    return _DIGITS.sub(digits, out)
