import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SPORT_NAME_BY_ID: Dict[str, str] = {
    "131506": "American Football",
    "154914": "Baseball",
    "48242": "Basketball",
    "452674": "Cricket",
    "6046": "Football",
    "265917": "Table Tennis",
    "54094": "Tennis",
    "154830": "Volleyball",
}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def env_list(name: str, default: str) -> List[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    base_dir: str = BASE_DIR
    url: str = "https://gotobet.com/en/sports-live"
    lark_webhook: str = ""

    limit: int = 480
    new_match_alert_minutes: int = 30
    live_check_interval: int = 15

    missing_threshold: int = 3
    reappear_alert_seconds: int = 60
    market_down_threshold: int = 3
    count_mismatch_threshold: int = 3
    scheduled_stale_grace_minutes: int = 5

    sport_ids: List[str] = field(default_factory=lambda: ["6046"])
    today_check_interval: int = 60
    today_start_grace_minutes: int = 5
    today_market_down_threshold: int = 3
    today_missing_threshold: int = 3
    today_reappear_alert_seconds: int = 60

    match_expire_seconds: int = 604800
    screenshot_expire_seconds: int = 604800
    browser_recycle_seconds: int = 86400
    screenshot_dir: str = os.path.join(BASE_DIR, "screenshots")

    viewport_width: int = 1920
    viewport_height: int = 1200
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def load_settings() -> Settings:
    load_dotenv()

    check_interval = env_int("CHECK_INTERVAL", 15)
    default_user_agent = Settings.user_agent

    return Settings(
        url=os.getenv("URL", "https://gotobet.com/en/sports-live"),
        lark_webhook=os.getenv("LARK_WEBHOOK", ""),
        limit=env_int("LIMIT", 480),
        new_match_alert_minutes=env_int("NEW_MATCH_ALERT_MINUTES", 30),
        live_check_interval=env_int("LIVE_CHECK_INTERVAL", check_interval),
        missing_threshold=env_int("MISSING_THRESHOLD", 3),
        reappear_alert_seconds=env_int("REAPPEAR_ALERT_SECONDS", 60),
        market_down_threshold=env_int("MARKET_DOWN_THRESHOLD", 3),
        count_mismatch_threshold=env_int("COUNT_MISMATCH_THRESHOLD", 3),
        scheduled_stale_grace_minutes=env_int("SCHEDULED_STALE_GRACE_MINUTES", 5),
        sport_ids=env_list("SPORT_IDS", "6046"),
        today_check_interval=env_int("TODAY_CHECK_INTERVAL", 60),
        today_start_grace_minutes=env_int("TODAY_START_GRACE_MINUTES", 5),
        today_market_down_threshold=env_int("TODAY_MARKET_DOWN_THRESHOLD", 3),
        today_missing_threshold=env_int("TODAY_MISSING_THRESHOLD", 3),
        today_reappear_alert_seconds=env_int("TODAY_REAPPEAR_ALERT_SECONDS", 60),
        match_expire_seconds=env_int("MATCH_EXPIRE_SECONDS", 604800),
        screenshot_expire_seconds=env_int("SCREENSHOT_EXPIRE_SECONDS", 604800),
        browser_recycle_seconds=env_int("BROWSER_RECYCLE_SECONDS", 86400),
        screenshot_dir=os.getenv("SCREENSHOT_DIR", os.path.join(BASE_DIR, "screenshots")),
        viewport_width=env_int("VIEWPORT_WIDTH", 1920),
        viewport_height=env_int("VIEWPORT_HEIGHT", 1200),
        user_agent=os.getenv("USER_AGENT", default_user_agent),
    )


def today_range_ms(now: Optional[datetime] = None) -> Tuple[int, int]:
    current = now or datetime.now()
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = current.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def sport_name(sport_id: str) -> str:
    return SPORT_NAME_BY_ID.get(str(sport_id), f"sport_{sport_id}")
