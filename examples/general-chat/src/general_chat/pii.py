"""PII redaction applied to user text before it reaches the LLM.

Pure functions, no state. Patterns target the identifiers most likely to
appear in Indonesian business chats: email addresses, NPWP tax numbers,
Indonesian mobile numbers, and long digit runs (NIK national IDs and
payment-card numbers). Masked forms keep a trailing fragment so the text
stays readable ("transfer ke ****1234").

Ordering matters: the specific patterns (email, NPWP, phone) run before
the generic digit-run rule so formatted values are not half-eaten by it.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")

#: Formatted NPWP: 99.999.999.9-999.999
_NPWP_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.(\d{3})\b")

#: Indonesian mobile numbers: +628..., 628..., 08... (9-13 digits total).
_PHONE_RE = re.compile(r"(?<!\d)(?:\+62|62|0)8\d{7,11}(?!\d)")

#: 13-19 digit runs, optionally grouped by spaces or dashes (NIK is 16
#: digits, payment cards 13-19). The lookarounds keep shorter numbers
#: (years, quantities, invoice ids) untouched.
_DIGIT_RUN_RE = re.compile(r"(?<![\d.])\d(?:[ -]?\d){12,18}(?![\d.])")


def _mask_email(match: re.Match[str]) -> str:
    return f"****@{match.group(1)}"


def _mask_npwp(match: re.Match[str]) -> str:
    return f"NPWP ****{match.group(1)}"


def _mask_last4(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"****{digits[-4:]}"


def redact_pii(text: str) -> tuple[str, bool]:
    """Return ``(redacted_text, changed)`` for ``text``.

    ``changed`` is False when no pattern matched, letting callers skip
    downstream work on clean text.
    """
    if not text:
        return text, False
    redacted = _EMAIL_RE.sub(_mask_email, text)
    redacted = _NPWP_RE.sub(_mask_npwp, redacted)
    redacted = _PHONE_RE.sub(_mask_last4, redacted)
    redacted = _DIGIT_RUN_RE.sub(_mask_last4, redacted)
    return redacted, redacted != text
