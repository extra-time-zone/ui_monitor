import os
import re
from datetime import datetime

from parsers import reset_scroll_to_top, scroll_to_match


def safe_name(value):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "").strip("_")


class Screenshotter:
    def __init__(self, settings):
        self.settings = settings
        os.makedirs(self.settings.screenshot_dir, exist_ok=True)

    def save(self, page, match_id, title, reason):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = (
            f"{ts}_{match_id}_{safe_name(reason)}_{safe_name(title)[:60]}.jpg"
        )
        path = os.path.join(self.settings.screenshot_dir, filename)

        try:
            locator = scroll_to_match(page, match_id)

            if locator is not None:
                container = locator.locator(
                    "xpath=ancestor::*[self::div or self::article]"
                    "[contains(., 'Home') or contains(., 'Away') "
                    "or contains(., 'Under/Over') "
                    "or contains(., 'Live market offers') "
                    "or contains(., '+')][1]"
                )

                if container.count() > 0:
                    container.screenshot(path=path, type="jpeg", quality=70)
                else:
                    locator.screenshot(path=path, type="jpeg", quality=70)

                return path

            print(
                "[SCREENSHOT] match card not found, opening detail page: "
                f"{match_id}",
                flush=True,
            )

            detail_page = page.context.new_page()
            try:
                detail_page.set_viewport_size({"width": 1600, "height": 1000})
                detail_page.goto(
                    f"https://gotobet.com/en/matches/{match_id}",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                detail_page.wait_for_timeout(3000)
                detail_page.screenshot(path=path, type="jpeg", quality=70)
            finally:
                detail_page.close()

            return path

        except Exception as exc:
            print(f"[SCREENSHOT ERROR] {exc}", flush=True)

            try:
                reset_scroll_to_top(page)
                page.wait_for_timeout(500)
                page.screenshot(path=path, type="jpeg", quality=50)
            except Exception as fallback_exc:
                print(f"[SCREENSHOT FALLBACK ERROR] {fallback_exc}", flush=True)

            return path


def cleanup_old_screenshots(directory: str, expire_seconds: int):
    if not os.path.exists(directory):
        return

    import time

    now = time.time()
    removed = 0

    for filename in os.listdir(directory):
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue

        try:
            if now - os.path.getmtime(path) > expire_seconds:
                os.remove(path)
                removed += 1
        except Exception as exc:
            print(f"[SCREENSHOT CLEANUP ERROR] {exc}", flush=True)

    if removed:
        print(f"[CLEANUP] removed {removed} screenshots", flush=True)
