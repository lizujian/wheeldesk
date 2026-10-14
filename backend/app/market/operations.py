from functools import wraps
from threading import Lock

from fastapi import HTTPException

_lock = Lock()


def market_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not _lock.acquire(timeout=1):
            raise HTTPException(409, "行情刷新或来源切换正在进行，请完成后重试")
        try:
            return function(*args, **kwargs)
        finally:
            _lock.release()
    return wrapped
