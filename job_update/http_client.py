"""Conservative standard-library HTTP client used by source adapters."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener


@dataclass
class HttpResponse:
    url: str
    status_code: int | None
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 400 and not self.error

    def json(self) -> Any:
        return json.loads(self.text)


class HttpClient:
    """A bounded, run-local cached HTTP client.

    The client deliberately returns structured failures. Adapters decide whether
    a failure is recoverable through browser fallback or must become Blocked.
    """

    def __init__(
        self,
        *,
        user_agent: str = "NottinghamshireJobsUpdate/1.0 (+https://github.com/anthonytransform-ai/nottinghamshire-jobs)",
        timeout: float = 25.0,
        retries: int = 2,
        host_delay: float = 0.15,
        cache_enabled: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(0, retries)
        self.host_delay = max(0.0, host_delay)
        self.cache_enabled = cache_enabled
        self._cache: dict[str, HttpResponse] = {}
        self._last_host_request: dict[str, float] = {}
        self._httpx = None
        try:
            import httpx  # type: ignore

            self._httpx = httpx.Client(
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": user_agent},
            )
        except ImportError:
            # Keep the engine usable in the repository's standard-library CI
            # environment. Operators get persistent cookies and the more
            # complete CA bundle when the documented httpx dependency exists.
            self._httpx = None
        self._opener = build_opener()

    @staticmethod
    def cache_key(url: str, method: str = "GET", data: bytes | None = None) -> str:
        digest = hashlib.sha256(data or b"").hexdigest()
        return f"{method.upper()} {url} {digest}"

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> HttpResponse:
        key = self.cache_key(url, method, data)
        if self.cache_enabled and use_cache and key in self._cache:
            cached = self._cache[key]
            return HttpResponse(**{**cached.__dict__, "from_cache": True})

        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
        }
        if headers:
            request_headers.update(headers)
        request = Request(url, data=data, headers=request_headers, method=method.upper())
        host = urlsplit(url).netloc
        last_error = ""
        for attempt in range(self.retries + 1):
            self._respect_host_delay(host)
            try:
                if self._httpx is not None:
                    response = self._httpx.request(
                        method.upper(),
                        url,
                        content=data,
                        headers=request_headers,
                    )
                    result = HttpResponse(
                        url=str(response.url),
                        status_code=response.status_code,
                        text=response.text,
                        headers=dict(response.headers),
                        error=(f"HTTP {response.status_code}: {response.reason_phrase}" if response.status_code >= 400 else ""),
                    )
                else:
                    with self._opener.open(request, timeout=self.timeout) as response:
                        body = response.read()
                        result = HttpResponse(
                            url=response.geturl(),
                            status_code=getattr(response, "status", 200),
                            text=body.decode(response.headers.get_content_charset() or "utf-8", errors="replace"),
                            headers=self._headers(response.headers),
                        )
                if self.cache_enabled and use_cache:
                    self._cache[key] = result
                if not result.error:
                    return result
                last_error = result.error
                if result.status_code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= self.retries:
                    return result
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                last_error = f"HTTP {exc.code}: {exc.reason}"
                result = HttpResponse(
                    url=url,
                    status_code=exc.code,
                    text=body,
                    headers=self._headers(exc.headers),
                    error=last_error,
                )
                if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= self.retries:
                    return result
            except (URLError, TimeoutError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.retries:
                    return HttpResponse(url=url, status_code=None, error=last_error)
            except Exception as exc:
                # httpx uses its own timeout/transport exception hierarchy;
                # keep a source-visible structured error without importing it
                # when the optional dependency is absent.
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.retries:
                    return HttpResponse(url=url, status_code=None, error=last_error)
            time.sleep(min(1.5, 0.25 * (attempt + 1)))
        return HttpResponse(url=url, status_code=None, error=last_error or "request failed")

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request(url, **kwargs)

    def _respect_host_delay(self, host: str) -> None:
        if not host or self.host_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_host_request.get(host, 0.0)
        if elapsed < self.host_delay:
            time.sleep(self.host_delay - elapsed)
        self._last_host_request[host] = time.monotonic()

    @staticmethod
    def _headers(headers: Message | None) -> dict[str, str]:
        if headers is None:
            return {}
        return {key: value for key, value in headers.items()}


def add_query(url: str, **params: str | int) -> str:
    """Add or replace simple query values without losing the existing route."""

    parts = urlsplit(url)
    query = dict()
    for pair in parts.query.split("&") if parts.query else []:
        if "=" in pair:
            key, value = pair.split("=", 1)
            query[key] = value
    query.update({key: str(value) for key, value in params.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
