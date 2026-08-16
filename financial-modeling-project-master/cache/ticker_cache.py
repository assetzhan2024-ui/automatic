"""Thread-safe background fetch cache for stocks, ETFs and bonds."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from fetcher.ticker import fetch_ticker, has_meaningful_data
from fetcher.bonds import fetch_bond, has_bond_data
from fetcher.fundamentals import clear_fund_cache
from fetcher.chart import clear_chart_cache
from fetcher.fx import clear_fx_cache

REQUEST_DELAY: float = 0.05
NUM_WORKERS: int = 10

_cache: dict = {
    "data": [],
    "status": "idle",
    "progress": 0,
    "total": 0,
    "skipped": 0,
    "last_updated": None,
}
_cache_lock = threading.Lock()
_stop_flag = threading.Event()


def get_status() -> dict:
    with _cache_lock:
        return {
            "status": _cache["status"],
            "progress": _cache["progress"],
            "total": _cache["total"],
            "skipped": _cache["skipped"],
            "last_updated": _cache["last_updated"],
            "data": list(_cache["data"]),
        }


def clear_cache() -> None:
    with _cache_lock:
        _cache.update({
            "data": [], "status": "idle", "progress": 0, "total": 0,
            "skipped": 0, "last_updated": None,
        })
    clear_fund_cache()
    clear_chart_cache()
    clear_fx_cache()


def stop_fetch() -> None:
    with _cache_lock:
        if _cache["status"] != "loading":
            return
        _stop_flag.set()
        _cache["status"] = "done"


def _record_is_usable(rec: dict, requested_asset_type: str) -> bool:
    if requested_asset_type == "bond":
        return has_bond_data(rec)
    return has_meaningful_data(rec)


def _do_fetch(tickers: list, asset_type: str = "stock") -> None:
    n = len(tickers)
    with _cache_lock:
        _cache.update({"status": "loading", "progress": 0, "total": n, "data": [], "skipped": 0})

    # Slots preserve the requested order. A completely empty instrument leaves
    # its slot as None, so it never appears in the UI.
    results = [None] * n
    prog_lock = threading.Lock()
    completed = [0]
    skipped = [0]

    def _worker(idx: int, sym: str) -> None:
        if _stop_flag.is_set():
            return

        rec = fetch_bond(sym) if asset_type == "bond" else fetch_ticker(sym)
        usable = _record_is_usable(rec, asset_type)

        if REQUEST_DELAY > 0:
            time.sleep(REQUEST_DELAY)

        if usable:
            results[idx] = rec
        else:
            with prog_lock:
                skipped[0] += 1

        with prog_lock:
            completed[0] += 1
            prog = completed[0]
            skip_count = skipped[0]

        if usable:
            tag = "OK" if not rec.get("error") else f"PARTIAL {str(rec.get('error'))[:40]}"
        else:
            tag = "SKIP all data N/A"
        print(f"  [{prog:>3}/{n}] {sym:<18} {tag}")

        with _cache_lock:
            _cache["data"] = [r for r in results if r is not None]
            _cache["progress"] = prog
            _cache["skipped"] = skip_count

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
        futures = {pool.submit(_worker, i, sym): sym for i, sym in enumerate(tickers)}
        for fut in as_completed(futures):
            if _stop_flag.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            try:
                fut.result()
            except Exception as exc:
                print(f"  Worker exception {futures[fut]}: {exc}")

    with _cache_lock:
        _cache["data"] = [r for r in results if r is not None]
        _cache["status"] = "done"
        _cache["last_updated"] = datetime.utcnow().isoformat()
        _cache["skipped"] = skipped[0]

    print(f"\n  ✓ Done — {completed[0]}/{n} checked, {skipped[0]} all-N/A removed\n")


def start_fetch(tickers: list, asset_type: str = "stock") -> None:
    _stop_flag.clear()
    print(f"\n  ▶ Fetching {len(tickers)} {asset_type} instruments with {NUM_WORKERS} workers")
    threading.Thread(target=_do_fetch, args=(tickers, asset_type), daemon=True).start()
