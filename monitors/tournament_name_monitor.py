import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests

from gotobet_api import (
    BEIJING_TZ,
    build_headers,
    extract_events,
    extract_next_cursor,
    fetch_sports,
    iter_dicts,
    request_json,
)


ENDPOINTS = {
    "tournament_hot": "/v1/tournament/hot",
    "match_ao_vivo": "/v1/match/ao-vivo",
    "match_melhores_partidas": "/v1/match/melhores-partidas",
    "match_search": "/v1/match/search",
    "match_hot": "/v1/match/hot",
    "menu_breadcrumb": "/v1/menu/breadcrumb",
}


def has_text(value) -> bool:
    return value is not None and str(value).strip() != ""


def compact_params(params: Optional[dict]) -> str:
    if not params:
        return ""
    return json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def format_path(parent: str, key) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if not parent:
        return str(key)
    return f"{parent}.{key}"


def find_tournament_name_issues(value, path: str = "") -> List[dict]:
    issues = []
    if isinstance(value, dict):
        tournament_id = value.get("tournament_id")
        if has_text(tournament_id) and not has_text(value.get("tournament_name")):
            issues.append(
                {
                    "path": path or "$",
                    "tournament_id": str(tournament_id).strip(),
                    "sport_id": str(value.get("sport_id") or ""),
                    "sport_name": str(value.get("sport_name") or ""),
                    "category_id": str(value.get("category_id") or ""),
                    "category_name": str(value.get("category_name") or ""),
                    "event_id": str(value.get("event_id") or ""),
                    "home_name": _competitor_name(value, "home_competitor")
                    or str(value.get("home_name") or ""),
                    "away_name": _competitor_name(value, "away_competitor")
                    or str(value.get("away_name") or ""),
                }
            )
        for key, child in value.items():
            issues.extend(find_tournament_name_issues(child, format_path(path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(find_tournament_name_issues(child, format_path(path, index)))
    return issues


def _competitor_name(value: dict, key: str) -> str:
    competitor = value.get(key)
    if isinstance(competitor, dict):
        return str(competitor.get("name") or competitor.get("short_name") or "")
    return ""


def collect_tournament_refs(data: dict) -> List[dict]:
    refs: Dict[Tuple[str, str, str], dict] = {}
    for item in iter_dicts(data):
        sport_id = item.get("sport_id")
        category_id = item.get("category_id")
        tournament_id = item.get("tournament_id")
        if not (has_text(sport_id) and has_text(category_id) and has_text(tournament_id)):
            continue
        key = (str(sport_id), str(category_id), str(tournament_id))
        refs.setdefault(
            key,
            {
                "sport_id": str(sport_id),
                "category_id": str(category_id),
                "tournament_id": str(tournament_id),
            },
        )
    return list(refs.values())


class TournamentNameMonitor:
    def __init__(self, settings, alerts, deduper=None):
        self.settings = settings
        self.alerts = alerts
        self.deduper = deduper
        self.alerted_keys: Dict[str, float] = {}

    @property
    def interval(self):
        return self.settings.tournament_name_interval

    def run_once(self):
        headers = build_headers(self.settings)
        enabled_endpoints = []
        seen_enabled = set()
        for endpoint in self.settings.tournament_name_endpoints:
            endpoint = endpoint.strip()
            if not endpoint or endpoint in seen_enabled:
                continue
            enabled_endpoints.append(endpoint)
            seen_enabled.add(endpoint)
        if not enabled_endpoints:
            print("[TOURNAMENT NAME] no endpoint enabled", flush=True)
            return

        all_alerts = []
        event_ids: Set[str] = set()
        tournament_refs: Dict[Tuple[str, str, str], dict] = {}

        with requests.Session() as session:
            sports = []
            if "match_search" in seen_enabled:
                sports = fetch_sports(session, self.settings, headers)

            for endpoint in enabled_endpoints:
                if endpoint in {"match_search", "menu_breadcrumb"}:
                    continue
                if endpoint not in ENDPOINTS:
                    print(f"[TOURNAMENT NAME] unknown endpoint={endpoint}", flush=True)
                    continue

                data = self._request_endpoint(session, headers, endpoint, None)
                if not data:
                    continue
                event_ids.update(self._event_ids_from(data))
                for ref in collect_tournament_refs(data):
                    tournament_refs.setdefault(
                        (ref["sport_id"], ref["category_id"], ref["tournament_id"]),
                        ref,
                    )
                all_alerts.extend(self._issues_from_data(endpoint, None, data))

            if "match_search" in seen_enabled:
                if not sports:
                    data = self._request_endpoint(session, headers, "match_search", None)
                    if data:
                        event_ids.update(self._event_ids_from(data))
                        for ref in collect_tournament_refs(data):
                            tournament_refs.setdefault(
                                (ref["sport_id"], ref["category_id"], ref["tournament_id"]),
                                ref,
                            )
                        all_alerts.extend(self._issues_from_data("match_search", None, data))
                for sport in sports:
                    sport_id = str(sport["sport_id"])
                    for status in self.settings.tournament_name_statuses:
                        for params, data in self._iter_match_search(session, headers, sport_id, status):
                            event_ids.update(self._event_ids_from(data))
                            for ref in collect_tournament_refs(data):
                                tournament_refs.setdefault(
                                    (ref["sport_id"], ref["category_id"], ref["tournament_id"]),
                                    ref,
                                )
                            all_alerts.extend(self._issues_from_data("match_search", params, data))

            if "menu_breadcrumb" in seen_enabled:
                breadcrumb_jobs = self._breadcrumb_jobs(event_ids, list(tournament_refs.values()))
                for params in breadcrumb_jobs:
                    data = self._request_endpoint(session, headers, "menu_breadcrumb", params)
                    if data:
                        all_alerts.extend(self._issues_from_data("menu_breadcrumb", params, data))
                print(
                    f"[TOURNAMENT NAME] menu_breadcrumb checked={len(breadcrumb_jobs)}",
                    flush=True,
                )

        print(f"[TOURNAMENT NAME] alerts={len(all_alerts)}", flush=True)
        if all_alerts:
            self.alerts.send_system_alert(
                "Gotobet tournament_name 缺失告警",
                self._build_message(all_alerts),
            )

    def _request_endpoint(self, session, headers, endpoint: str, params: Optional[dict]):
        url = f"{self.settings.gotobet_service_api_base_url.rstrip('/')}{ENDPOINTS[endpoint]}"
        data = request_json(
            session,
            url,
            headers,
            params=params,
            timeout=max(3, self.settings.api_detail_timeout),
            retries=max(0, self.settings.api_detail_retries),
        )
        if data is not None:
            count = sum(1 for _ in iter_dicts(data))
            print(
                f"[TOURNAMENT NAME] {endpoint} params={compact_params(params) or '-'} "
                f"objects={count}",
                flush=True,
            )
        return data

    def _iter_match_search(self, session, headers, sport_id: str, status: str):
        url = f"{self.settings.gotobet_service_api_base_url.rstrip('/')}{ENDPOINTS['match_search']}"
        cursor = "0"
        seen_cursors: Set[str] = set()

        for _ in range(max(1, self.settings.api_max_pages)):
            params = {"sport_id": sport_id, "status": str(status), "cursor": cursor}
            data = request_json(
                session,
                url,
                headers,
                params=params,
                timeout=max(3, self.settings.api_detail_timeout),
                retries=max(0, self.settings.api_detail_retries),
            )
            if not data:
                break

            print(
                f"[TOURNAMENT NAME] match_search sport_id={sport_id} "
                f"status={status} cursor={cursor}",
                flush=True,
            )
            yield params, data

            next_cursor = extract_next_cursor(data)
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            cursor = next_cursor

    def _issues_from_data(self, endpoint: str, params: Optional[dict], data: dict):
        current_time = time.time()
        issues = []
        for issue in find_tournament_name_issues(data):
            issue.update(
                {
                    "endpoint": endpoint,
                    "params": params or {},
                    "url": (
                        f"{self.settings.gotobet_service_api_base_url.rstrip('/')}"
                        f"{ENDPOINTS[endpoint]}"
                    ),
                }
            )
            key = self._alert_key(issue)
            if not self._should_alert(key, current_time):
                continue
            issues.append(issue)
        return issues

    @staticmethod
    def _event_ids_from(data: dict) -> Set[str]:
        return {str(event["event_id"]) for event in extract_events(data) if event.get("event_id")}

    def _breadcrumb_jobs(self, event_ids: Set[str], tournament_refs: List[dict]) -> List[dict]:
        jobs = []
        seen = set()
        limit = max(1, self.settings.tournament_name_max_breadcrumb_items)

        for event_id in sorted(event_ids):
            key = ("event_id", event_id)
            if key in seen:
                continue
            seen.add(key)
            jobs.append({"event_id": event_id})
            if len(jobs) >= limit:
                return jobs

        for ref in tournament_refs:
            key = (ref["sport_id"], ref["category_id"], ref["tournament_id"])
            if key in seen:
                continue
            seen.add(key)
            jobs.append(dict(ref))
            if len(jobs) >= limit:
                break

        return jobs

    def _alert_key(self, issue: dict) -> str:
        return "|".join(
            [
                "tournament_name_missing",
                issue.get("endpoint") or "",
                compact_params(issue.get("params")),
                issue.get("path") or "",
                issue.get("sport_id") or "",
                issue.get("category_id") or "",
                issue.get("tournament_id") or "",
                issue.get("event_id") or "",
            ]
        )

    def _should_alert(self, key: str, now: float) -> bool:
        ttl_seconds = max(1, self.settings.api_repeat_alert_interval)
        if self.deduper is not None:
            return self.deduper.should_alert(
                f"api_field:{key}",
                now,
                ttl_seconds=ttl_seconds,
            )

        last_alert_time = self.alerted_keys.get(key, 0)
        if now - last_alert_time < ttl_seconds:
            return False
        self.alerted_keys[key] = now
        return True

    def _build_message(self, alerts):
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        max_items = max(1, self.settings.tournament_name_max_alert_items)
        shown = alerts[:max_items]
        lines = [
            f"Gotobet tournament_name 缺失告警 @ {timestamp}",
            f"发现 {len(alerts)} 条 tournament_id 有值但 tournament_name 为空的数据。",
            "",
        ]
        if len(alerts) > max_items:
            lines.append(f"以下仅展示前 {max_items} 条：")
            lines.append("")

        for index, issue in enumerate(shown, 1):
            lines.append(f"{index}. endpoint={issue['endpoint']}")
            if issue.get("params"):
                lines.append(f"   params={compact_params(issue['params'])}")
            lines.append(f"   path={issue.get('path') or '-'}")
            lines.append(f"   tournament_id={issue.get('tournament_id') or '-'}")
            if issue.get("sport_id") or issue.get("sport_name"):
                lines.append(
                    f"   sport={issue.get('sport_name') or '-'}({issue.get('sport_id') or '-'})"
                )
            if issue.get("category_id") or issue.get("category_name"):
                lines.append(
                    f"   category={issue.get('category_name') or '-'}"
                    f"({issue.get('category_id') or '-'})"
                )
            if issue.get("event_id"):
                lines.append(f"   event_id={issue['event_id']}")
            if issue.get("home_name") or issue.get("away_name"):
                lines.append(
                    f"   match={issue.get('home_name') or '-'} vs "
                    f"{issue.get('away_name') or '-'}"
                )
            lines.append(f"   url={issue['url']}")
            lines.append("")
        return "\n".join(lines).rstrip()
