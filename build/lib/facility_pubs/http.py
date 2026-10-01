"""Small HTTP helper with bounded retries and explicit request provenance."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "Mozilla/5.0 (compatible; facility-publication-finder/0.1)"


# Hosts that said they are out of budget for this run (circuit breaker).
_EXHAUSTED = set()
_LOCK = threading.Lock()
LONG_WAIT_SECONDS = 120


def _host(url):
    return urllib.parse.urlsplit(url).netloc.lower()


def reset_circuit_breaker():
    with _LOCK:
        _EXHAUSTED.clear()


def _retry_after_raw(headers):
    try:
        return int(headers.get("Retry-After")) if headers else None
    except (TypeError, ValueError):
        return None


def _retry_after_seconds(headers, default):
    if not headers:
        return default
    value = headers.get("Retry-After")
    try:
        return max(0, min(120, int(value)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class FetchResult:
    body: bytes | None
    status: int | None
    final_url: str | None
    content_type: str | None
    error: str | None = None

    @property
    def ok(self):
        return self.body is not None and self.status is not None and 200 <= self.status < 300


def fetch_result(url, timeout=60, tries=3, data=None, headers=None):
    """Fetch bytes and preserve HTTP/transport outcome.

    401/403/404/410 are returned immediately as explicit failures. 429 and
    transient failures are retried with bounded backoff.
    """
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    host = _host(url)
    if host in _EXHAUSTED:
        return FetchResult(None, 429, url, None, "host_exhausted")
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return FetchResult(
                    body=response.read(),
                    status=getattr(response, "status", None) or response.getcode(),
                    final_url=response.geturl(),
                    content_type=response.headers.get_content_type()
                    if response.headers else None,
                )
        except urllib.error.HTTPError as exc:
            last = FetchResult(
                body=None,
                status=exc.code,
                final_url=getattr(exc, "url", url),
                content_type=exc.headers.get_content_type() if exc.headers else None,
                error=f"http_{exc.code}",
            )
            if exc.code in (401, 403, 404, 410):
                return last
            if exc.code == 429:
                raw = _retry_after_raw(exc.headers)
                try:
                    body = exc.read(2000).decode("utf-8", "ignore").lower()
                except Exception:
                    body = ""
                # Out of budget, or told to wait for a long time: stop asking this host
                # for the rest of the run instead of stalling every later request.
                if (raw is not None and raw > LONG_WAIT_SECONDS) or "budget" in body:
                    with _LOCK:
                        _EXHAUSTED.add(host)
                    return FetchResult(None, 429, last.final_url, last.content_type, "host_exhausted")
                time.sleep(_retry_after_seconds(exc.headers, 10 * (attempt + 1)))
                continue
        except urllib.error.URLError as exc:
            last = FetchResult(None, None, url, None, f"url_error:{exc.reason}")
        except TimeoutError:
            last = FetchResult(None, None, url, None, "timeout")
        except Exception as exc:
            last = FetchResult(None, None, url, None, f"{type(exc).__name__}:{exc}")
        time.sleep(2 ** attempt)
    return last or FetchResult(None, None, url, None, "unknown_error")


def fetch(url, binary=False, timeout=60, tries=3, data=None, headers=None):
    """Compatibility wrapper returning body or None."""
    result = fetch_result(
        url,
        timeout=timeout,
        tries=tries,
        data=data,
        headers=headers,
    )
    if not result.ok:
        return None
    return result.body if binary else result.body.decode("utf-8", "ignore")


def get_json(url, **kw):
    text = fetch(url, **kw)
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None
