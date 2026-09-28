from __future__ import annotations

import re
import unicodedata


def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", text).strip().upper()


def compact_label(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))
