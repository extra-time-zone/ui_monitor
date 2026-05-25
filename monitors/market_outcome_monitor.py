import time
from datetime import datetime
from typing import Dict, List

import requests

from gotobet_api import (
    BEIJING_TZ,
    STATUS_CONFIG,
    build_headers,
    competitor_name,
    extract_markets,
    fetch_events,
    fetch_match_detail,
    fetch_sports,
    format_match_time,
    run_detail_jobs,
)


def has_text(value) -> bool:
    return value is not None and str(value).strip() != ""


def market_display_name(market: dict) -> str:
    name = market.get("name") or market.get("name_raw") or market.get("market_name")
    return str(name).strip() if has_text(name) else "(空)"


def outcome_display_name(outcome: dict) -> str:
    name = outcome.get("name") or outcome.get("name_raw") or outcome.get("outcome_name")
    return str(name).strip() if has_text(name) else "(空)"


def find_market_issues(detail_data: dict) -> List[dict]:
    findings = []
    for market in extract_markets(detail_data):
        market_id = str(market.get("id") or market.get("market_id") or "")
        display_market_name = market_display_name(market)

        if not has_text(market.get("name")):
            findings.append(
                {
                    "issue_type": "market_name_empty",
                    "issue_label": "Market name 为空",
                    "market_id": market_id,
                    "market_name": display_market_name,
                    "outcome_id": "",
                    "outcome_name": "",
                }
            )

        outcomes = market.get("outcomes")
        if not isinstance(outcomes, list):
            continue

        for outcome in outcomes:
            outcome_dict = (
                outcome if isinstance(outcome, dict) else {"name": "" if outcome is None else str(outcome)}
            )
            if has_text(outcome_dict.get("name")):
                continue
            findings.append(
                {
                    "issue_type": "outcome_name_empty",
                    "issue_label": "Outcome name 为空",
                    "market_id": market_id,
                    "market_name": display_market_name,
                    "outcome_id": str(outcome_dict.get("id") or outcome_dict.get("outcome_id") or ""),
                    "outcome_name": outcome_display_name(outcome_dict),
                }
            )

        if len(outcomes) == 1:
            outcome = outcomes[0] if isinstance(outcomes[0], dict) else {"name": str(outcomes[0])}
            findings.append(
                {
                    "issue_type": "single_outcome",
                    "issue_label": "Market 只有一条 Outcome",
                    "market_id": market_id,
                    "market_name": display_market_name,
                    "outcome_id": str(outcome.get("id") or outcome.get("outcome_id") or ""),
                    "outcome_name": outcome_display_name(outcome),
                }
            )
    return findings


class MarketOutcomeMonitor:
    def __init__(self, settings, alerts):
        self.settings = settings
        self.alerts = alerts
        self.alerted_keys: Dict[str, float] = {}

    @property
    def interval(self):
        return self.settings.market_outcome_interval

    def run_once(self):
        headers = build_headers(self.settings)
        with requests.Session() as session:
            sports = fetch_sports(session, self.settings, headers)
            if not sports:
                print("[MARKET OUTCOME] no sport_id found", flush=True)
                return

            all_alerts = []
            counts = {}
            for sport in sports:
                sport_id = sport["sport_id"]
                sport_name = sport.get("name") or sport_id
                for status_key in self.settings.market_outcome_statuses:
                    status_info = STATUS_CONFIG.get(status_key)
                    if not status_info:
                        continue
                    events = fetch_events(
                        session,
                        self.settings,
                        headers,
                        sport_id,
                        status_info["status"],
                        self.settings.api_max_pages,
                    )
                    counts[f"{status_key}:{sport_id}"] = len(events)
                    print(
                        f"[MARKET OUTCOME] {status_info['label']} "
                        f"{sport_name}({sport_id}) matches={len(events)}",
                        flush=True,
                    )
                    all_alerts.extend(
                        self._scan_events(headers, sport_id, sport_name, status_key, status_info, events)
                    )

            print(
                f"[MARKET OUTCOME] checked={sum(counts.values())} alerts={len(all_alerts)}",
                flush=True,
            )
            if all_alerts:
                self.alerts.send_system_alert(
                    "Gotobet market/outcome 告警",
                    self._build_message(all_alerts),
                )

    def _scan_events(self, headers, sport_id, sport_name, status_key, status_info, events):
        current_time = time.time()

        def worker(event):
            event_id = str(event.get("event_id") or "")
            if not event_id:
                return event, []
            with requests.Session() as detail_session:
                detail_data = fetch_match_detail(detail_session, self.settings, headers, event_id)
            return event, find_market_issues(detail_data or {})

        alerts = []
        for event, findings in run_detail_jobs(self.settings, headers, events, worker):
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            for finding in findings:
                alert_key = "|".join(
                    [
                        status_key,
                        event_id,
                        finding.get("issue_type") or "",
                        finding.get("market_id") or finding.get("market_name") or "",
                        finding.get("outcome_id") or finding.get("outcome_name") or "",
                    ]
                )
                last_alert_time = self.alerted_keys.get(alert_key, 0)
                if current_time - last_alert_time < self.settings.api_repeat_alert_interval:
                    continue
                self.alerted_keys[alert_key] = current_time
                alerts.append(
                    {
                        "event": event,
                        "finding": finding,
                        "sport_id": sport_id,
                        "sport_name": sport_name,
                        "status_label": status_info["label"],
                        "detail_url": f"{self.settings.gotobet_base_url.rstrip('/')}/en/matches/{event_id}",
                    }
                )
        return alerts

    @staticmethod
    def _build_message(alerts):
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"Gotobet market/outcome 告警 @ {timestamp}",
            f"发现 {len(alerts)} 条 market/outcome 异常：",
            "",
        ]
        for index, alert in enumerate(alerts, 1):
            event = alert["event"]
            finding = alert["finding"]
            home = competitor_name(event, "home_competitor", "Home")
            away = competitor_name(event, "away_competitor", "Away")
            lines.append(f"{index}. [{alert['status_label']}] {alert['sport_name']} / {event['event_id']}")
            lines.append(f"   比赛: {home} vs {away}")
            lines.append(f"   开赛时间: {format_match_time(event)}")
            lines.append(f"   页面: {alert['detail_url']}")
            lines.append(f"   问题: {finding.get('issue_label') or finding.get('issue_type') or '未知'}")
            lines.append(f"   Market: {finding['market_name']}")
            if finding.get("outcome_name"):
                lines.append(f"   Outcome: {finding['outcome_name']}")
            if finding.get("market_id") or finding.get("outcome_id"):
                lines.append(
                    f"   IDs: market={finding.get('market_id') or '-'} "
                    f"outcome={finding.get('outcome_id') or '-'}"
                )
            lines.append("")
        return "\n".join(lines).rstrip()
