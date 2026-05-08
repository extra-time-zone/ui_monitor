import time

from playwright.sync_api import sync_playwright

from alerts import AlertClient
from browser import BrowserManager
from config import load_settings
from monitors.live_monitor import LiveMonitor
from monitors.sports_today_monitor import SportsTodayMonitor
from screenshot import Screenshotter, cleanup_old_screenshots


def main():
    settings = load_settings()
    alerts = AlertClient(settings.lark_webhook)
    screenshotter = Screenshotter(settings)

    print("[APP] gotobet monitor starting", flush=True)
    print(f"[APP] live interval={settings.live_check_interval}s", flush=True)
    print(f"[APP] today interval={settings.today_check_interval}s", flush=True)
    print(f"[APP] sport_ids={','.join(settings.sport_ids)}", flush=True)

    with sync_playwright() as playwright:
        browser_manager = BrowserManager(playwright, settings)
        live_monitor = LiveMonitor(settings, browser_manager, alerts, screenshotter)
        today_monitor = SportsTodayMonitor(
            settings,
            browser_manager,
            alerts,
            screenshotter,
        )

        next_live_at = 0.0
        next_today_at = 0.0
        next_cleanup_at = 0.0

        try:
            while True:
                now = time.time()
                recycled = browser_manager.recycle_if_needed()
                if recycled:
                    live_monitor.close_page()

                if now >= next_live_at:
                    run_monitor("live", live_monitor.run_once)
                    next_live_at = time.time() + settings.live_check_interval

                if now >= next_today_at:
                    run_monitor("today", today_monitor.run_once)
                    next_today_at = time.time() + settings.today_check_interval

                if now >= next_cleanup_at:
                    cleanup_old_screenshots(
                        settings.screenshot_dir,
                        settings.screenshot_expire_seconds,
                    )
                    next_cleanup_at = time.time() + 3600

                sleep_for = max(1.0, min(next_live_at, next_today_at, next_cleanup_at) - time.time())
                time.sleep(sleep_for)
        finally:
            live_monitor.close_page()
            browser_manager.close()


def run_monitor(name, func):
    try:
        func()
    except Exception as exc:
        print(f"[{name.upper()} ERROR] {exc}", flush=True)


if __name__ == "__main__":
    main()
