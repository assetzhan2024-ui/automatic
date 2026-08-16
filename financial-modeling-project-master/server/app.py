"""
server/app.py
=============
HTTP-сервер: маршрутизация запросов и отдача статических файлов.

Этот модуль знает только о транспорте (HTTP) и роутинге.
Вся бизнес-логика делегирована server/handlers.py.
"""

import json
import math
import os
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from server.handlers import (
    handle_status,
    handle_chart,
    handle_fundamentals,
    handle_tickers,
    handle_fetch_post,
    handle_stop_post,
    handle_kase_test,
    handle_clear_post,
    handle_export,
    handle_export_dcf,
)

MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
    ".svg":  "image/svg+xml",
}

_project_root: str = ""

_URL_TO_DIR: list[tuple[str, str]] = [
    ("/styles/",    "styles"),
    ("/script/",    "script"),
    ("/templates/", "templates"),
]

_ROOT_INDEX = "templates/index.html"


def configure(project_root: str) -> None:
    global _project_root
    _project_root = project_root


def _resolve_file(url_path: str) -> str | None:
    """Разрешить URL-путь в абсолютный путь к файлу на диске."""
    url_path = url_path.split("?")[0].split("#")[0]

    if url_path in ("/", ""):
        candidate = os.path.join(_project_root, _ROOT_INDEX)
        return candidate if os.path.isfile(candidate) else None

    for url_prefix, dir_name in _URL_TO_DIR:
        if url_path.startswith(url_prefix):
            filename = url_path[len(url_prefix):].replace("..", "").lstrip("/")
            if not filename:
                return None
            candidate = os.path.join(_project_root, dir_name, filename)
            return candidate if os.path.isfile(candidate) else None

    safe = url_path.lstrip("/").replace("..", "")
    candidate = os.path.join(_project_root, safe)
    return candidate if os.path.isfile(candidate) else None


# ── Маршрутные таблицы ────────────────────────────────────────────────────────
_GET_ROUTES: dict = {
    "/api/status":       lambda qs: handle_status(qs),
    "/api/chart":        lambda qs: handle_chart(qs),
    "/api/fundamentals": lambda qs: handle_fundamentals(qs),
    "/api/tickers":      lambda _qs: handle_tickers(),
    "/api/kase_test":    lambda qs: handle_kase_test(qs),
    "/api/export":       lambda qs: handle_export(qs),
    "/api/export/dcf":   lambda qs: handle_export_dcf(qs),
}

_POST_ROUTES: dict = {
    "/api/fetch": lambda qs: handle_fetch_post(qs),
    "/api/stop":  lambda _qs: handle_stop_post(),
    "/api/clear": lambda _qs: handle_clear_post(),
}


def _clean_json(o):
    """Рекурсивно заменяем Infinity/NaN на null — они невалидны в JSON."""
    if isinstance(o, float):
        return None if (math.isinf(o) or math.isnan(o)) else o
    if isinstance(o, dict):
        return {k: _clean_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean_json(v) for v in o]
    return o


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()}  {fmt % args}")

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(_clean_json(obj), ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_xlsx(self, body: bytes, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, url_path: str) -> None:
        file_path = _resolve_file(url_path)
        if file_path:
            ext  = os.path.splitext(file_path)[1].lower()
            mime = MIME_TYPES.get(ext, "application/octet-stream")
            with open(file_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type",   mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            print(f"  404: {url_path!r}")
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self) -> None:
        """Preflight CORS для браузерных запросов."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        handler = _GET_ROUTES.get(parsed.path)
        if not handler:
            self._serve_static(parsed.path)
            return

        try:
            result = handler(qs)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send_json({"error": str(exc)}, 500)
            return

        # Бинарные ответы: (status, bytes, content_type)
        if len(result) == 3:
            status, body, _ctype = result
            if isinstance(body, bytes) and status == 200:
                fname = f"export_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
                try:
                    self._send_xlsx(body, fname)
                except Exception:
                    pass
                return
            err = body if isinstance(body, dict) else {"error": body.decode("utf-8", errors="replace")}
            self._send_json(err, status)
        else:
            status, body = result
            self._send_json(body, status)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)

        handler = _POST_ROUTES.get(parsed.path)
        if handler:
            try:
                status, body = handler(qs)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                self._send_json({"error": str(exc)}, 500)
                return
            self._send_json(body, status)
        else:
            self.send_response(404)
            self.end_headers()


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    """Создать и вернуть многопоточный HTTPServer."""
    return ThreadingHTTPServer((host, port), Handler)
