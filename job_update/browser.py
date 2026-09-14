"""Optional Playwright Chromium boundary for dynamic public recruitment pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserResponse:
    url: str
    html: str = ""
    status_code: int | None = None
    error: str = ""
    captured_urls: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.html) and not self.error


class BrowserClient:
    """Launches Chromium only when an adapter explicitly requests it.

    No CAPTCHA or authentication bypass is attempted. A challenge page is
    returned to the adapter so the source can be marked partial/blocked.
    """

    def __init__(self, *, headless: bool = True, timeout_ms: int = 30_000, executable_path: str | None = None) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.executable_path = executable_path

    @staticmethod
    def available() -> bool:
        try:
            import playwright.sync_api  # type: ignore
        except ImportError:
            return False
        return True

    def render(
        self,
        url: str,
        *,
        wait_for: str | None = None,
        wait_ms: int = 2_000,
        capture_urls: bool = False,
        load_more_selector: str | None = None,
        max_load_more: int = 100,
    ) -> BrowserResponse:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return BrowserResponse(url=url, error="Playwright is not installed")

        captured: list[str] = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless, executable_path=self.executable_path)
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                if capture_urls:
                    page.on("response", lambda response: captured.append(response.url))
                response = page.goto(url, wait_until="domcontentloaded")
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=self.timeout_ms)
                    except PlaywrightTimeoutError:
                        pass
                if wait_ms:
                    page.wait_for_timeout(wait_ms)
                if load_more_selector:
                    for _ in range(max(0, max_load_more)):
                        more = page.locator(load_more_selector).last
                        if more.count() == 0 or not more.is_visible():
                            break
                        try:
                            more.click(timeout=min(self.timeout_ms, 5_000))
                            page.wait_for_timeout(wait_ms)
                        except Exception:
                            break
                html = page.content()
                status = response.status if response else None
                browser.close()
                return BrowserResponse(url=page.url or url, html=html, status_code=status, captured_urls=captured)
        except Exception as exc:  # Playwright has several platform-specific exception classes.
            return BrowserResponse(url=url, error=f"{type(exc).__name__}: {exc}", captured_urls=captured)
