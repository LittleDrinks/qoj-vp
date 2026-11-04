"""Shared errors and time values."""
import math
import time
from datetime import datetime

class ApplicationError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def now_ms():
    return int(time.time() * 1000)


def timestamp_ms(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if value.tzinfo is None:
            raise ValueError('A timestamp requires an explicit timezone')
        value = value.timestamp() * 1000
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError('Expected a nonnegative epoch-millisecond timestamp')
    return int(value)
