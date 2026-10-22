"""The browser the sandbox drives: a small, typed async surface over Playwright.

BrowserDriver is the interface the control server calls. PlaywrightDriver is the real one (Chromium
on a virtual display); tests use a fake. It is async so it shares the server's event loop — sync
Playwright would start its own loop and clash with uvicorn. Chromium launches lazily on the first
navigate, so the server stays up even if the browser is slow to start. Every method returns a small,
plain dict of what is on screen now — data for the engine to observe, never an instruction.
"""

import asyncio
from typing import Protocol, runtime_checkable

from .net import safe_public_url

# The safe, non-committing things the sandbox does on its own (no Founder approval needed).
SAFE_ACTIONS = ("click", "type", "scroll", "key", "back")


@runtime_checkable
class BrowserDriver(Protocol):
    async def navigate(self, url: str) -> dict: ...
    async def interact(self, action: str, selector: str | None, text: str | None) -> dict: ...
    async def state(self) -> dict: ...
    async def close(self) -> None: ...


class PlaywrightDriver:
    """The real driver: one Chromium page on the sandbox's virtual display. Deploy-tested.

    Lazy-launches Chromium on first use (inside the event loop), so the package imports and the
    server starts without Playwright running, and a browser problem surfaces per request.
    """

    def __init__(self, headless: bool = False) -> None:
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._page is None:
            from playwright.async_api import async_playwright  # lazy: only in the sandbox image

            self._pw = await async_playwright().start()
            # Fill the virtual screen: a maximized window the size of the display, and a page with
            # no forced viewport so its content fills that window (the panel shows a full browser,
            # not a small window on a black desktop).
            self._browser = await self._pw.chromium.launch(
                headless=self._headless,
                args=["--start-maximized", "--window-position=0,0", "--window-size=1280,800"],
            )
            context = await self._browser.new_context(no_viewport=True)
            self._page = await context.new_page()

    async def navigate(self, url: str) -> dict:
        async with self._lock:
            await self._ensure()
            await self._page.goto(safe_public_url(url), wait_until="domcontentloaded")
            return await self._state()

    async def interact(self, action: str, selector: str | None, text: str | None) -> dict:
        async with self._lock:
            await self._ensure()
            if action == "click" and selector:
                await self._page.click(selector)
            elif action == "type" and selector is not None:
                await self._page.fill(selector, text or "")
            elif action == "scroll":
                await self._page.mouse.wheel(0, int(text or "600"))
            elif action == "key":
                await self._page.keyboard.press(text or "Enter")
            elif action == "back":
                await self._page.go_back()
            else:
                raise ValueError(f"unknown or incomplete interaction: {action!r}")
            return await self._state()

    async def _state(self) -> dict:
        return {"url": self._page.url, "title": await self._page.title()}

    async def state(self) -> dict:
        async with self._lock:
            if self._page is None:
                return {"url": "about:blank", "title": ""}
            return await self._state()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
