import time
from datetime import datetime
from typing import Dict, List

import requests

from gotobet_api import (
    BEIJING_TZ,
    build_headers,
    competitor_name,
    extract_markets,
    fetch_events,
    fetch_match_detail,
    fetch_sports,
    format_match_time,
    run_detail_jobs,
)


def normalize_product(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def line_product_details(detail_data: dict) -> Dict[str, List[dict]]:
    products: Dict[str, List[dict]] = {"1": [], "3": []}
    for market in extract_markets(detail_data):
        market_name = str(
            market.get("name") or market.get("name_raw") or market.get("id") or "Unknown market"
        )
        for line in market.get("lines") or []:
            if not isinstance(line, dict):
                continue
            product = normalize_product(line.get("product"))
            if product not in products:
                continue
            products[product].append(
                {
                    "market": market_name,
                    "line_id": str(line.get("id") or ""),
                    "specifiers": str(line.get("specifiers") or line.get("row") or ""),
                    "product_raw": str(line.get("product_raw") or ""),
                }
            )
    return products


class ProductBothMonitor:
    def __init__(self, settings, alerts):
        self.settings = settings
        self.alerts = alerts
        self.alerted_keys: Dict[str, float] = {}

    @property
    def interval(self):
        return self.settings.product_both_interval

    def run_once(self):
        headers = build_headers(self.settings)
        with requests.Session() as session:
            sports = fetch_sports(session, self.settings, headers)
            if not sports:
                print("[PRODUCT BOTH] no sport_id found", flush=True)
                return

            all_alerts = []
            total_matches = 0
            for sport in sports:
                sport_id = sport["sport_id"]
                sport_name = sport.get("name") or sport_id
                events = fetch_events(
                    session,
                    self.settings,
                    headers,
                    sport_id,
                    "2",
                    self.settings.product_both_max_pages,
                )
                total_matches += len(events)
                print(
                    f"[PRODUCT BOTH] sports-live {sport_name}({sport_id}) "
                    f"matches={len(events)}",
                    flush=True,
                )
                all_alerts.extend(self._scan_events(headers, sport_id, sport_name, events))

            print(
                f"[PRODUCT BOTH] checked={total_matches} alerts={len(all_alerts)}",
                flush=True,
            )
            if all_alerts:
                self.alerts.send_system_alert(
                    "Gotobet product 1 和 3 同时存在告警",
                    self._build_message(all_alerts),
                )

    def _scan_events(self, headers, sport_id, sport_name, events):
        current_time = time.time()

        def worker(event):
            event_id = str(event.get("event_id") or "")
            if not event_id:
                return event, {"1": [], "3": []}
            with requests.Session() as detail_session:
                detail_data = fetch_match_detail(detail_session, self.settings, headers, event_id)
            return event, line_product_details(detail_data or {})

        alerts = []
        for event, products in run_detail_jobs(self.settings, headers, events, worker):
            event_id = str(event.get("event_id") or "")
            if not event_id or not products.get("1") or not products.get("3"):
                continue
            last_alert_time = self.alerted_keys.get(event_id, 0)
            if current_time - last_alert_time < self.settings.api_repeat_alert_interval:
                continue
            self.alerted_keys[event_id] = current_time
            alerts.append(
                {
                    "event": event,
                    "products": products,
                    "sport_id": sport_id,
                    "sport_name": sport_name,
                    "detail_url": f"{self.settings.gotobet_base_url.rstrip('/')}/en/matches/{event_id}",
                }
            )
        return alerts

    @staticmethod
    def _build_message(alerts):
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"Gotobet product 同时存在告警 @ {timestamp}",
            f"发现 {len(alerts)} 场 sports-live 比赛同时存在 product 1 和 product 3：",
            "",
        ]
        for index, alert in enumerate(alerts, 1):
            event = alert["event"]
            products = alert["products"]
            event_id = event["event_id"]
            home = competitor_name(event, "home_competitor", "Home")
            away = competitor_name(event, "away_competitor", "Away")
            lines.append(f"{index}. {alert['sport_name']} / {event_id}")
            lines.append(f"   比赛: {home} vs {away}")
            lines.append(f"   开赛时间: {format_match_time(event)}")
            lines.append(f"   页面: {alert['detail_url']}")
            for product in ("1", "3"):
                details = products.get(product) or []
                lines.append(f"   Product {product}: {len(details)} 条 line")
                for detail in details[:5]:
                    spec = f" ({detail['specifiers']})" if detail.get("specifiers") else ""
                    raw = f" raw={detail['product_raw']}" if detail.get("product_raw") else ""
                    lines.append(f"     - {detail['market']}{spec}{raw}")
                if len(details) > 5:
                    lines.append(f"     - 其余 {len(details) - 5} 条略")
            lines.append("")
        return "\n".join(lines).rstrip()
