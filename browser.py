import time


class BrowserManager:
    def __init__(self, playwright, settings):
        self.playwright = playwright
        self.settings = settings
        self.browser = None
        self.context = None
        self.started_at = 0.0

    def ensure(self):
        now = time.time()
        if (
            self.browser is None
            or self.context is None
            or now - self.started_at > self.settings.browser_recycle_seconds
        ):
            self.recycle()
        return self.context

    def recycle_if_needed(self) -> bool:
        if self.browser is None:
            self.recycle()
            return True
        if time.time() - self.started_at > self.settings.browser_recycle_seconds:
            print("[BROWSER] recycling...", flush=True)
            self.recycle()
            print("[BROWSER] recycled", flush=True)
            return True
        return False

    def new_page(self):
        context = self.ensure()
        return context.new_page()

    def recycle(self):
        self.close()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self.context = self.browser.new_context(
            viewport={
                "width": self.settings.viewport_width,
                "height": self.settings.viewport_height,
            },
            user_agent=self.settings.user_agent,
        )
        self.started_at = time.time()

    def close(self):
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass
        self.context = None
        self.browser = None
