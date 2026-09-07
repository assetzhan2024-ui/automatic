"""In-memory immutable portfolio snapshots.

A snapshot is created exactly once after Markowitz optimization and is the single
source of truth for all downstream consumers (GBM, Bootstrap and Excel export).
Downstream models never rerun the optimizer.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
import uuid

_MAX_SNAPSHOTS = 32
_TTL = timedelta(hours=2)
_LOCK = threading.RLock()
_STORE: "OrderedDict[str, dict]" = OrderedDict()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _purge() -> None:
    cutoff = _now() - _TTL
    expired = [sid for sid, item in _STORE.items() if item["created_at"] < cutoff]
    for sid in expired:
        _STORE.pop(sid, None)
    while len(_STORE) > _MAX_SNAPSHOTS:
        _STORE.popitem(last=False)


def save_portfolio_snapshot(result: dict, historical_returns: list[dict]) -> str:
    """Store one Markowitz result plus aligned historical returns and return its ID."""
    sid = uuid.uuid4().hex
    payload = {
        "created_at": _now(),
        "result": deepcopy(result),
        "historical_returns": deepcopy(historical_returns or []),
    }
    with _LOCK:
        _purge()
        _STORE[sid] = payload
        _STORE.move_to_end(sid)
    return sid


def get_portfolio_snapshot(snapshot_id: str) -> dict:
    """Return a defensive copy of a stored snapshot or raise a clear error."""
    sid = str(snapshot_id or "").strip()
    if not sid:
        raise ValueError("Отсутствует snapshot_id. Сначала рассчитайте портфель Markowitz.")
    with _LOCK:
        _purge()
        item = _STORE.get(sid)
        if item is None:
            raise ValueError("Portfolio snapshot не найден или истёк. Рассчитайте портфель заново.")
        _STORE.move_to_end(sid)
        return {
            "result": deepcopy(item["result"]),
            "historical_returns": deepcopy(item["historical_returns"]),
        }


def clear_portfolio_snapshots() -> None:
    with _LOCK:
        _STORE.clear()
