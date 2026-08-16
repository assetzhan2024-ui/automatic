#!/usr/bin/env python3
"""
cmd/main.py
===========
Точка входа приложения.

Отвечает за:
  - разбор аргументов CLI
  - поиск корневой директории проекта
  - настройку параметров параллелизма
  - запуск HTTP-сервера

Ожидаемая структура:

    automatic/
      cmd/main.py         ← эта точка входа
      templates/index.html
      styles/style.css
      script/app.js
      config/ fetcher/ server/ cache/ regions/

Run:
    pip install yfinance pandas
    cd automatic
    python cmd/main.py [--port 8080] [--workers 10] [--delay 0.05]

Или с явным корнем:
    python cmd/main.py --root /path/to/automatic
"""

import argparse
import os
import sys

import cache.ticker_cache as ticker_cache
from config.tickers import DEFAULT_TICKERS
from server.app import configure as configure_root, create_server

# cmd/ находится внутри проекта — поднимаемся на уровень выше
_CMD_DIR     = os.path.dirname(os.path.realpath(__file__))
_PROJECT_DIR = os.path.dirname(_CMD_DIR)


def _resolve_project_root(override: str | None) -> str:
    """
    Найти корень проекта (папка, содержащая templates/, styles/, script/).

    Порядок поиска:
      1. Явный --root аргумент
      2. Родительская папка cmd/ (стандартная раскладка)
      3. Сама папка cmd/ (запуск из неё напрямую — нестандартно)
    """
    if override:
        return os.path.realpath(override)
    # Стандартная раскладка: templates/ рядом с cmd/
    if os.path.isdir(os.path.join(_PROJECT_DIR, "templates")):
        return _PROJECT_DIR
    # Fallback: может, запустили прямо из корня проекта
    if os.path.isdir(os.path.join(_CMD_DIR, "templates")):
        return _CMD_DIR
    return _PROJECT_DIR


def main() -> None:
    ap = argparse.ArgumentParser(description="Stock Screener v5 — KASE + Global")
    ap.add_argument("--port",    type=int,   default=8080,  help="HTTP-порт (по умолчанию 8080)")
    ap.add_argument("--workers", type=int,   default=10,    help="Параллельных потоков загрузки")
    ap.add_argument("--delay",   type=float, default=0.05,  help="Пауза между запросами на поток (сек)")
    ap.add_argument("--root",    type=str,   default=None,  help="Корень проекта (содержит templates/, styles/, script/)")
    args = ap.parse_args()

    ticker_cache.REQUEST_DELAY = args.delay
    ticker_cache.NUM_WORKERS   = args.workers

    project_root = _resolve_project_root(args.root)
    configure_root(project_root)

    # Проверяем наличие index.html
    index_path = os.path.join(project_root, "templates", "index.html")
    if not os.path.isfile(index_path):
        print(f"""
  ✗ ERROR: templates/index.html не найден.

  Искали в: {project_root}/templates/

  Ожидаемая структура:
    automatic/
      cmd/main.py          ← точка входа
      templates/index.html
      styles/style.css
      script/app.js

  Запуск из корня проекта:
      cd automatic && python cmd/main.py

  Или явно указать корень:
      python cmd/main.py --root /путь/к/automatic
""")
        sys.exit(1)

    server = create_server("0.0.0.0", args.port)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║   STOCK SCREENER  v5  —  KASE + Global  🇰🇿              ║
╠══════════════════════════════════════════════════════════╣
║  URL      →  http://localhost:{args.port:<28}║
║  Tickers  →  {len(DEFAULT_TICKERS):<43}║
║  Workers  →  {args.workers:<43}║
║  Root     →  {project_root:<43}║
╚══════════════════════════════════════════════════════════╝
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
