import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SPORT_NAME_BY_ID: Dict[str, str] = {
    "131506": "American Football",
    "154914": "Baseball",
    "154919": "Boxing",
    "154923": "Darts",
    "48242": "Basketball",
    "452674": "Cricket",
    "6046": "Football",
    "687887": "Futsal",
    "621569": "Beach Volleyball",
    "35709": "Handball",
    "35232": "Ice Hockey",
    "265917": "Table Tennis",
    "54094": "Tennis",
    "154830": "Volleyball",
    "1149093": "Badminton",
}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def env_list(name: str, default: str) -> List[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    live_empty_page_threshold: int = 3

    sport_ids: List[str] = field(default_factory=lambda: ["6046"])
    today_sport_ids_source: str = "top"
    today_top_sports_url: str = "https://xp-service-api.gotobet.com/v1/menu/sports/top"
    today_check_interval: int = 60
    today_start_grace_minutes: int = 5
    today_market_down_threshold: int = 3
    today_empty_page_threshold: int = 3
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

    gotobet_base_url: str = "https://gotobet.com"
    gotobet_service_api_base_url: str = "https://xp-service-api.gotobet.com"
    gotobet_top_sports_url: str = "https://xp-service-api.gotobet.com/v1/menu/sports/top"
    gotobet_authorization_token: str = ""
    gotobet_api_sport_ids: List[str] = field(default_factory=list)
    api_detail_workers: int = 8
    api_detail_timeout: int = 10
    api_detail_retries: int = 1
    api_max_pages: int = 20
    api_repeat_alert_interval: int = 86400

    enable_market_outcome_monitor: bool = False
    market_outcome_interval: int = 60
    market_outcome_statuses: List[str] = field(
        default_factory=lambda: ["sports", "sports-live"]
    )

    enable_live_product_rules_monitor: bool = False
    product_rules_interval: int = 60
    product_rules_max_pages: int = 1


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
        live_empty_page_threshold=env_int("LIVE_EMPTY_PAGE_THRESHOLD", 3),
        sport_ids=env_list("SPORT_IDS", "6046"),
        today_sport_ids_source=os.getenv("TODAY_SPORT_IDS_SOURCE", "top").strip().lower(),
        today_top_sports_url=os.getenv(
            "TODAY_TOP_SPORTS_URL",
            "https://xp-service-api.gotobet.com/v1/menu/sports/top",
        ),
        today_check_interval=env_int("TODAY_CHECK_INTERVAL", 60),
        today_start_grace_minutes=env_int("TODAY_START_GRACE_MINUTES", 5),
        today_market_down_threshold=env_int("TODAY_MARKET_DOWN_THRESHOLD", 3),
        today_empty_page_threshold=env_int("TODAY_EMPTY_PAGE_THRESHOLD", 3),
        today_missing_threshold=env_int("TODAY_MISSING_THRESHOLD", 3),
        today_reappear_alert_seconds=env_int("TODAY_REAPPEAR_ALERT_SECONDS", 60),
        match_expire_seconds=env_int("MATCH_EXPIRE_SECONDS", 604800),
        screenshot_expire_seconds=env_int("SCREENSHOT_EXPIRE_SECONDS", 604800),
        browser_recycle_seconds=env_int("BROWSER_RECYCLE_SECONDS", 86400),
        screenshot_dir=os.getenv("SCREENSHOT_DIR", os.path.join(BASE_DIR, "screenshots")),
        viewport_width=env_int("VIEWPORT_WIDTH", 1920),
        viewport_height=env_int("VIEWPORT_HEIGHT", 1200),
        user_agent=os.getenv("USER_AGENT", default_user_agent),
        gotobet_base_url=os.getenv("GOTOBET_BASE_URL", "https://gotobet.com"),
        gotobet_service_api_base_url=os.getenv(
            "GOTOBET_SERVICE_API_BASE_URL",
            "https://xp-service-api.gotobet.com",
        ),
        gotobet_top_sports_url=os.getenv(
            "GOTOBET_TOP_SPORTS_URL",
            os.getenv(
                "TODAY_TOP_SPORTS_URL",
                "https://xp-service-api.gotobet.com/v1/menu/sports/top",
            ),
        ),
        gotobet_authorization_token=os.getenv("GOTOBET_AUTHORIZATION_TOKEN", ""),
        gotobet_api_sport_ids=env_list("GOTOBET_API_SPORT_IDS", ""),
        api_detail_workers=env_int("API_DETAIL_WORKERS", 8),
        api_detail_timeout=env_int("API_DETAIL_TIMEOUT", 10),
        api_detail_retries=env_int("API_DETAIL_RETRIES", 1),
        api_max_pages=env_int("API_MAX_PAGES", 20),
        api_repeat_alert_interval=env_int("API_REPEAT_ALERT_INTERVAL", 86400),
        enable_market_outcome_monitor=env_bool("ENABLE_MARKET_OUTCOME_MONITOR", False),
        market_outcome_interval=env_int("MARKET_OUTCOME_INTERVAL", 60),
        market_outcome_statuses=env_list(
            "MARKET_OUTCOME_STATUSES",
            "sports,sports-live",
        ),
        enable_live_product_rules_monitor=env_bool(
            "ENABLE_LIVE_PRODUCT_RULES_MONITOR",
            env_bool("ENABLE_PRODUCT_BOTH_MONITOR", False),
        ),
        product_rules_interval=env_int(
            "PRODUCT_RULES_INTERVAL",
            env_int("PRODUCT_BOTH_INTERVAL", 60),
        ),
        product_rules_max_pages=env_int(
            "PRODUCT_RULES_MAX_PAGES",
            env_int("PRODUCT_BOTH_MAX_PAGES", 1),
        ),
    )


def today_range_ms(now: Optional[datetime] = None) -> Tuple[int, int]:
    current = now or datetime.now()
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = current.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def sport_name(sport_id: str) -> str:
    return SPORT_NAME_BY_ID.get(str(sport_id), f"sport_{sport_id}")
