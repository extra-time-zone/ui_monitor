import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set

import requests


BEIJING_TZ = timezone(timedelta(hours=8))

STATUS_CONFIG = {
    "sports": {"status": "1", "label": "赛前盘"},
    "sports-live": {"status": "2", "label": "滚球盘"},
}


def build_headers(settings) -> Dict[str, str]:
    headers = {
        "accept": "*/*",
        "accept-language": "en",
        "cache-control": "no-cache, no-store, must-revalidate",
        "content-type": "application/json",
        "origin": settings.gotobet_base_url.rstrip("/"),
        "user-agent": settings.user_agent,
        "x-source": "ls",
        "x-timezone": "Asia/Shanghai",
    }
    if settings.gotobet_authorization_token:
        token = settings.gotobet_authorization_token.removeprefix("Bearer ").strip()
        headers["authorization"] = f"Bearer {token}"
    return headers


def request_json(
    session: requests.Session,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, str]] = None,
    timeout: int = 15,
    retries: int = 0,
) -> Optional[dict]:
    last_exc = None
    for attempt in range(max(0, retries) + 1):
        try:
            response = session.get(url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
            print(f"[API] response is not object: {url}", flush=True)
            return None
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
    print(f"[API] request failed: {url} params={params or {}} error={last_exc}", flush=True)
    return None


def iter_dicts(value) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_dicts(item)


def extract_sports(menu_data: dict) -> List[dict]:
    sports: Dict[str, dict] = {}
    for item in iter_dicts(menu_data):
        sport_id = item.get("sport_id")
        if sport_id is None:
            continue
        sport_id = str(sport_id)
        name = (
            item.get("name")
            or item.get("sport_name")
            or item.get("display_name")
            or item.get("title")
            or sport_id
        )
        sports.setdefault(sport_id, {"sport_id": sport_id, "name": str(name)})
    return sorted(sports.values(), key=lambda sport: sport["sport_id"])


def fetch_sports(session: requests.Session, settings, headers: Dict[str, str]) -> List[dict]:
    if settings.gotobet_api_sport_ids:
        return [
            {"sport_id": str(sport_id), "name": str(sport_id)}
            for sport_id in settings.gotobet_api_sport_ids
        ]

    url = settings.gotobet_top_sports_url
    data = request_json(session, url, headers)
    return extract_sports(data or {})


def fetch_top_sports(session: requests.Session, settings, headers: Dict[str, str]) -> List[dict]:
    data = request_json(
        session,
        settings.gotobet_top_sports_url,
        headers,
        timeout=max(3, settings.api_detail_timeout),
        retries=max(0, settings.api_detail_retries),
    )
    return extract_sports(data or {})


def extract_next_cursor(data: dict) -> Optional[str]:
    for item in iter_dicts(data):
        for key in ("next_cursor", "nextCursor", "cursor_next"):
            value = item.get(key)
            if value not in (None, "", "0", 0):
                return str(value)
        has_more = item.get("has_more", item.get("hasMore"))
        cursor = item.get("cursor")
        if has_more and cursor not in (None, "", "0", 0):
            return str(cursor)
    return None


def extract_events(search_data: dict) -> List[dict]:
    events: Dict[str, dict] = {}
    for item in iter_dicts(search_data):
        event_id = item.get("event_id")
        if event_id is None:
            continue
        event_id = str(event_id)
        if event_id not in events:
            copied = dict(item)
            copied["event_id"] = event_id
            events[event_id] = copied
    return list(events.values())


def fetch_events(
    session: requests.Session,
    settings,
    headers: Dict[str, str],
    sport_id: str,
    status: str,
    max_pages: int,
) -> List[dict]:
    url = f"{settings.gotobet_service_api_base_url.rstrip('/')}/v1/match/search"
    events_by_id: Dict[str, dict] = {}
    cursor = "0"
    seen_cursors: Set[str] = set()

    for _ in range(max(1, max_pages)):
        data = request_json(
            session,
            url,
            headers,
            params={"sport_id": sport_id, "status": status, "cursor": cursor},
        )
        if not data:
            break

        for event in extract_events(data):
            events_by_id.setdefault(event["event_id"], event)

        next_cursor = extract_next_cursor(data)
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        cursor = next_cursor

    return list(events_by_id.values())


def fetch_match_detail(
    session: requests.Session,
    settings,
    headers: Dict[str, str],
    event_id: str,
) -> Optional[dict]:
    url = f"{settings.gotobet_service_api_base_url.rstrip('/')}/v1/match/{event_id}"
    return request_json(
        session,
        url,
        headers,
        timeout=max(3, settings.api_detail_timeout),
        retries=max(0, settings.api_detail_retries),
    )


def extract_markets(detail_data: dict) -> List[dict]:
    markets: List[dict] = []
    seen_ids: Set[int] = set()
    for item in iter_dicts(detail_data):
        market_list = item.get("markets")
        if not isinstance(market_list, list):
            continue
        for market in market_list:
            if not isinstance(market, dict):
                continue
            object_id = id(market)
            if object_id in seen_ids:
                continue
            seen_ids.add(object_id)
            markets.append(market)
    return markets


def competitor_name(event: dict, key: str, fallback: str) -> str:
    competitor = event.get(key)
    if isinstance(competitor, dict):
        return str(competitor.get("name") or competitor.get("short_name") or fallback)
    return fallback


def format_match_time(event: dict) -> str:
    start_time = event.get("start_time")
    try:
        return datetime.fromtimestamp(int(start_time), tz=BEIJING_TZ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return str(start_time or "-")


def run_detail_jobs(settings, headers, events, worker_func):
    workers = max(1, settings.api_detail_workers)
    if workers == 1 or len(events) <= 1:
        for event in events:
            yield worker_func(event)
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(worker_func, event): event for event in events}
        for future in as_completed(future_map):
            try:
                yield future.result()
            except Exception as exc:
                event = future_map[future]
                print(
                    f"[API] detail check failed: event_id={event.get('event_id')} "
                    f"error={exc}",
                    flush=True,
                )
