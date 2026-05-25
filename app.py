import time

from playwright.sync_api import sync_playwright

from alerts import AlertClient
from browser import BrowserManager
from config import load_settings
from monitors.live_monitor import LiveMonitor
from monitors.market_outcome_monitor import MarketOutcomeMonitor
from monitors.product_both_monitor import ProductBothMonitor
from monitors.sports_today_monitor import SportsTodayMonitor
from screenshot import Screenshotter, cleanup_old_screenshots


def main():
    settings = load_settings()
    alerts = AlertClient(settings.lark_webhook)
    screenshotter = Screenshotter(settings)

    print("[APP] gotobet monitor starting", flush=True)
    print(f"[APP] live interval={settings.live_check_interval}s", flush=True)
    print(f"[APP] today interval={settings.today_check_interval}s", flush=True)
    print(f"[APP] today sport source={settings.today_sport_ids_source}", flush=True)
    print(f"[APP] fallback sport_ids={','.join(settings.sport_ids)}", flush=True)
    print(
        f"[APP] market/outcome detail monitor enabled="
        f"{settings.enable_market_outcome_monitor}",
        flush=True,
    )
    print(
        f"[APP] live product rules detail monitor enabled="
        f"{settings.enable_live_product_rules_monitor}",
        flush=True,
    )

    with sync_playwright() as playwright:
        browser_manager = BrowserManager(playwright, settings)
        live_monitor = LiveMonitor(settings, browser_manager, alerts, screenshotter)
        today_monitor = SportsTodayMonitor(
            settings,
            browser_manager,
            alerts,
            screenshotter,
        )
        scheduled_monitors = [
            {"name": "live", "monitor": live_monitor, "next_at": 0.0},
            {"name": "today", "monitor": today_monitor, "next_at": 0.0},
        ]
        if settings.enable_market_outcome_monitor:
            scheduled_monitors.append(
                {
                    "name": "market_outcome",
                    "monitor": MarketOutcomeMonitor(settings, alerts),
                    "next_at": 0.0,
                }
            )
            print("[APP] market/outcome monitor enabled", flush=True)
        if settings.enable_live_product_rules_monitor:
            scheduled_monitors.append(
                {
                    "name": "live_product_rules",
                    "monitor": ProductBothMonitor(settings, alerts, browser_manager),
                    "next_at": 0.0,
                }
            )
            print("[APP] live product rules monitor enabled", flush=True)

        next_cleanup_at = 0.0

        try:
            while True:
                now = time.time()
                recycled = browser_manager.recycle_if_needed()
                if recycled:
                    live_monitor.close_page()

                for item in scheduled_monitors:
                    if now >= item["next_at"]:
                        run_monitor(item["name"], item["monitor"].run_once)
                        item["next_at"] = time.time() + item["monitor"].interval

                if now >= next_cleanup_at:
                    cleanup_old_screenshots(
                        settings.screenshot_dir,
                        settings.screenshot_expire_seconds,
                    )
                    next_cleanup_at = time.time() + 3600

                next_monitor_at = min(item["next_at"] for item in scheduled_monitors)
                sleep_for = max(1.0, min(next_monitor_at, next_cleanup_at) - time.time())
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
