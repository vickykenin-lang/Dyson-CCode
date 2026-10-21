"""The browser the sandbox drives. A small, typed surface so the engine never touches Playwright.

BrowserDriver is the interface the control server calls. PlaywrightDriver is the real one (Chromium
on a virtual display); tests use a fake. Every method returns a small, plain dict of what is on
screen now — it is data for the engine to observe, never an instruction (plan-then-execute holds).
"""

from typing import Protocol, runtime_checkable

from .net import safe_public_url

# The safe, non-committing things the sandbox does on its own (no Founder approval needed).
SAFE_ACTIONS = ("click", "type", "scroll", "key", "back")


@runtime_checkable
class BrowserDriver(Protocol):
    def navigate(self, url: str) -> dict: ...
    def interact(self, action: str, selector: str | None, text: str | None) -> dict: ...
    def state(self) -> dict: ...
    def close(self) -> None: ...


class PlaywrightDriver:
    """The real driver: one Chromium page on the sandbox's virtual display. Deploy-tested.

    Lazy-imports Playwright so the package imports (and unit tests run) without it installed.
    """

    def __init__(self, headless: bool = False) -> None:
        from playwright.sync_api import sync_playwright  # lazy: only in the sandbox image

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._page = self._browser.new_page()

    def navigate(self, url: str) -> dict:
        self._page.goto(safe_public_url(url), wait_until="domcontentloaded")
        return self.state()

    def interact(self, action: str, selector: str | None, text: str | None) -> dict:
        if action == "click" and selector:
            self._page.click(selector)
        elif action == "type" and selector is not None:
            self._page.fill(selector, text or "")
        elif action == "scroll":
            self._page.mouse.wheel(0, int(text or "600"))
        elif action == "key":
            self._page.keyboard.press(text or "Enter")
        elif action == "back":
            self._page.go_back()
        else:
            raise ValueError(f"unknown or incomplete interaction: {action!r}")
        return self.state()

    def state(self) -> dict:
        return {"url": self._page.url, "title": self._page.title()}

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()
