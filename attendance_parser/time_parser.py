from __future__ import annotations

import math
import re
from datetime import datetime, time


TIME_PATTERN = re.compile(r"^\s*(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\s*\*?\s*$")


def normalize_time(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return f"{value.hour:02d}:{value.minute:02d}"
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number) or number < 0 or number >= 1:
            return None
        total_minutes = int(round(number * 24 * 60)) % (24 * 60)
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
    if not isinstance(value, str):
        return None
    match = TIME_PATTERN.fullmatch(value)
    if not match:
        return None
    hour, minute, second = (int(part or 0) for part in match.groups())
    if hour > 23 or minute > 59 or second > 59:
        return None
    return f"{hour:02d}:{minute:02d}"
