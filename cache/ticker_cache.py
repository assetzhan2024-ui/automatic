"""
cache/ticker_cache.py
=====================
Управляет параллельным фоновым обходом тикеров и глобальным кешем результатов.

Публичный API:
    start_fetch(tickers)  — запустить фоновый обход (не блокирует)
    stop_fetch()          — отменить текущий обход
    get_status()          — вернуть текущее состояние кеша (thread-safe)

Результаты накапливаются по мере готовности и доступны через get_status()
до завершения всего обхода — фронтенд обновляется в реальном времени.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from fetcher.ticker import fetch_ticker
from fetcher.fundamentals import clear_fund_cache
from fetcher.chart import clear_chart_cache
from fetcher.fx import clear_fx_cache

# ── Настройки параллелизма (переопределяются из main) ────────────────────────
REQUEST_DELAY: float = 0.05
NUM_WORKERS:   int   = 10

# ── Глобальный кеш ───────────────────────────────────────────────────────────
_cache: dict = {
    "data":         [],
    "status":       "idle",    # "idle" | "loading" | "done"
    "progress":     0,
    "total":        0,
    "last_updated": None,
}
_cache_lock = threading.Lock()
_stop_flag  = threading.Event()


def get_status() -> dict:
    """Вернуть копию текущего состояния кеша (thread-safe)."""
    with _cache_lock:
        return {
            "status":       _cache["status"],
            "progress":     _cache["progress"],
            "total":        _cache["total"],
            "last_updated": _cache["last_updated"],
            "data":         list(_cache["data"]),  # копируем список, не ссылку
        }


def clear_cache() -> None:
    """Полностью очистить все кеши: скринер, fundamentals, chart."""
    with _cache_lock:
        _cache["data"]         = []
        _cache["status"]       = "idle"
        _cache["progress"]     = 0
        _cache["total"]        = 0
        _cache["last_updated"] = None
    # Сбрасываем кеши подмодулей вне основного лока — у них свои локи
    clear_fund_cache()
    clear_chart_cache()
    clear_fx_cache()


def stop_fetch() -> None:
    """Прервать текущий обход. Статус → "done".

    Если загрузка уже не идёт — ничего не делаем.
    Это защищает от race condition: clearAllData в JS шлёт /api/stop
    асинхронно, и запрос может прийти уже после нового /api/fetch,
    убив новую загрузку.
    """
    with _cache_lock:
        if _cache["status"] != "loading":
            return   # нечего останавливать
        _stop_flag.set()
        _cache["status"] = "done"


def _do_fetch(tickers: list) -> None:
    n = len(tickers)
    with _cache_lock:
        _cache.update({"status": "loading", "progress": 0, "total": n, "data": []})

    # Предварительно выделяем слоты — сохраняем порядок тикеров
    results   = [None] * n
    prog_lock = threading.Lock()
    completed = [0]

    def _worker(idx: int, sym: str) -> None:
        if _stop_flag.is_set():
            return

        rec = fetch_ticker(sym)

        if REQUEST_DELAY > 0:
            time.sleep(REQUEST_DELAY)

        results[idx] = rec

        with prog_lock:
            completed[0] += 1
            prog = completed[0]

        tag = "OK" if not rec.get("error") else f"ERR {rec['error'][:50]}"
        print(f"  [{prog:>3}/{n}] {sym:<18} {tag}")

        # Обновляем кеш после каждого тикера — UI видит прогресс сразу
        with _cache_lock:
            _cache["data"]     = [r for r in results if r is not None]
            _cache["progress"] = prog

    # as_completed — правильный способ: не блокируем параллелизм,
    # просто собираем результаты по мере готовности
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
        futures = {pool.submit(_worker, i, sym): sym for i, sym in enumerate(tickers)}
        for fut in as_completed(futures):
            if _stop_flag.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            try:
                fut.result()
            except Exception as e:
                sym = futures[fut]
                print(f"  Worker exception {sym}: {e}")

    with _cache_lock:
        _cache["data"]         = [r for r in results if r is not None]
        _cache["status"]       = "done"
        _cache["last_updated"] = datetime.utcnow().isoformat()

    print(f"\n  ✓ Done — {completed[0]}/{n} tickers fetched\n")


def start_fetch(tickers: list) -> None:
    """Запустить параллельный обход тикеров в фоновом потоке."""
    _stop_flag.clear()
    print(f"\n  ▶ Fetching {len(tickers)} tickers with {NUM_WORKERS} workers")
    threading.Thread(target=_do_fetch, args=(tickers,), daemon=True).start()
