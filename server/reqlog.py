"""Per-request logging + failure recording: a middleware appends a compact JSONL
record (method / path / status / latency / ip / country / error / traceback) per
request to a per-replica file under WORK_DIR; helpers read them back. The /stats,
/stats/daily and /failures endpoints aggregate these across replicas. Client ip /
country come from Cloudflare's CF-Connecting-IP / CF-IPCountry headers."""

import json as _json
import socket as _socket
import time as _time
import traceback as _tb
from collections import deque as _deque
from datetime import datetime

from starlette.middleware.base import BaseHTTPMiddleware as _BaseHTTPMiddleware
from starlette.responses import Response as _RawResponse

from server.config import WORK_DIR

_REQ_DIR = WORK_DIR / "_requests"
_REPLICA = _socket.gethostname()
_recent_requests: _deque = _deque(maxlen=3000)
_SKIP_LOG_PATHS = {"/api/v1/stats", "/api/v1/stats/daily", "/api/v1/failures",
                   "/api/v1/health", "/dashboard", "/dashboard/echarts.js", "/favicon.ico"}


def _record_request(rec: dict) -> None:
    _recent_requests.append(rec)
    try:
        import json as _json
        _REQ_DIR.mkdir(parents=True, exist_ok=True)
        f = _REQ_DIR / f"{_REPLICA}.jsonl"
        if f.exists() and f.stat().st_size > 5_000_000:  # bound the file (~5 MB)
            tail = f.read_text(errors="replace").splitlines()[-15000:]
            f.write_text("\n".join(tail) + "\n")
        with open(f, "a") as fh:
            fh.write(_json.dumps(rec) + "\n")
    except Exception:
        pass


class RequestLogMiddleware(_BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = _time.time()
        path = request.url.path
        # Behind Cloudflare → nginx, the real client is in CF headers (hyphenated,
        # so nginx forwards them by default); fall back to XFF then the socket peer.
        h = request.headers
        ip = (h.get("cf-connecting-ip")
              or (h.get("x-forwarded-for") or "").split(",")[0].strip()
              or (request.client.host if request.client else ""))
        country = (h.get("cf-ipcountry") or "").upper()
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "method": request.method, "path": path, "replica": _REPLICA,
            "ip": ip, "country": country,
        }
        try:
            response = await call_next(request)
        except Exception as exc:  # unhandled → 500, capture traceback
            rec.update(status=500, ms=round((_time.time() - start) * 1000, 1),
                       error=f"{type(exc).__name__}: {exc}",
                       traceback=_tb.format_exc()[-2000:])
            if path not in _SKIP_LOG_PATHS:
                _record_request(rec)
            raise
        rec["status"] = response.status_code
        rec["ms"] = round((_time.time() - start) * 1000, 1)
        if response.status_code >= 400:
            # Buffer the (small) error body to capture the reason, then rebuild
            # the response.  Success/streaming responses are passed through as-is.
            import json as _json
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            try:
                rec["error"] = _json.loads(body).get("detail") if body else ""
            except Exception:
                rec["error"] = body.decode(errors="replace")[:500]
            headers = dict(response.headers)
            headers.pop("content-length", None)
            response = _RawResponse(content=body, status_code=response.status_code,
                                    headers=headers, media_type=response.media_type)
        if path not in _SKIP_LOG_PATHS:
            _record_request(rec)
        return response


def _read_request_records(limit_lines: int = 20000) -> list:
    """Aggregate recent request records across all replicas' JSONL files."""
    import json as _json
    recs: list = []
    try:
        for f in _REQ_DIR.glob("*.jsonl"):
            try:
                lines = f.read_text(errors="replace").splitlines()[-limit_lines:]
            except Exception:
                continue
            for ln in lines:
                try:
                    recs.append(_json.loads(ln))
                except Exception:
                    pass
    except Exception:
        pass
    recs.sort(key=lambda r: r.get("ts", ""))
    return recs
