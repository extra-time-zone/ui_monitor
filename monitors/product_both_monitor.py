import time
from datetime import datetime
from typing import Dict, List

import requests

from config import today_range_ms
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
from parsers import collect_all_matches


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
    def __init__(self, settings, alerts, browser_manager=None):
        self.settings = settings
        self.alerts = alerts
        self.browser_manager = browser_manager
        self.alerted_keys: Dict[str, float] = {}

    @property
    def interval(self):
        return self.settings.product_rules_interval

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
                    self.settings.product_rules_max_pages,
                )
                total_matches += len(events)
                print(
                    f"[LIVE PRODUCT RULES] sports-live {sport_name}({sport_id}) "
                    f"matches={len(events)}",
                    flush=True,
                )
                all_alerts.extend(self._scan_events(headers, sport_id, sport_name, events))

            print(
                f"[LIVE PRODUCT RULES] checked={total_matches} alerts={len(all_alerts)}",
                flush=True,
            )
            if all_alerts:
                self.alerts.send_system_alert(
                    "Gotobet live product 规则告警",
                    self._build_message(all_alerts),
                )

    def _scan_events(self, headers, sport_id, sport_name, events):
        current_time = time.time()
        today_visible_ids = None

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
            if not event_id:
                continue

            if products.get("3"):
                self._append_alert(
                    alerts,
                    current_time,
                    "live_product3_visible",
                    event=event,
                    products=products,
                    sport_id=sport_id,
                    sport_name=sport_name,
                )

            if not products.get("1") and self.browser_manager is not None:
                if today_visible_ids is None:
                    today_visible_ids = self._collect_today_visible_ids(sport_id, sport_name)
                if event_id in today_visible_ids:
                    self._append_alert(
                        alerts,
                        current_time,
                        "live_no_product1_still_visible_in_today",
                        event=event,
                        products=products,
                        sport_id=sport_id,
                        sport_name=sport_name,
                    )
        return alerts

    def _append_alert(self, alerts, current_time, issue_type, event, products, sport_id, sport_name):
        event_id = str(event.get("event_id") or "")
        alert_key = f"{issue_type}:{event_id}"
        last_alert_time = self.alerted_keys.get(alert_key, 0)
        if current_time - last_alert_time < self.settings.api_repeat_alert_interval:
            return
        self.alerted_keys[alert_key] = current_time
        alerts.append(
            {
                "issue_type": issue_type,
                "event": event,
                "products": products,
                "sport_id": sport_id,
                "sport_name": sport_name,
                "detail_url": f"{self.settings.gotobet_base_url.rstrip('/')}/en/matches/{event_id}",
            }
        )

    def _collect_today_visible_ids(self, sport_id, sport_name):
        from_ms, to_ms = today_range_ms()
        url = (
            f"{self.settings.gotobet_base_url.rstrip('/')}/en/sports/{sport_id}"
            f"?from={from_ms}&to={to_ms}"
        )
        page = self.browser_manager.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(3000)
            matches = collect_all_matches(page, sport_id=sport_id, sport_name=sport_name)
            ids = {match["match_id"] for match in matches}
            print(
                f"[LIVE PRODUCT RULES] today visible {sport_name}({sport_id}) "
                f"matches={len(ids)}",
                flush=True,
            )
            return ids
        except Exception as exc:
            print(
                f"[LIVE PRODUCT RULES] today visibility check failed "
                f"sport_id={sport_id} error={exc}",
                flush=True,
            )
            return set()
        finally:
            try:
                page.close()
            except Exception:
                pass

    @staticmethod
    def _build_message(alerts):
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"Gotobet live product 规则告警 @ {timestamp}",
            f"发现 {len(alerts)} 条 sports-live product 规则异常：",
            "",
        ]
        for index, alert in enumerate(alerts, 1):
            event = alert["event"]
            products = alert["products"]
            event_id = event["event_id"]
            home = competitor_name(event, "home_competitor", "Home")
            away = competitor_name(event, "away_competitor", "Away")
            issue_text = issue_label(alert["issue_type"])
            lines.append(f"{index}. [{issue_text}] {alert['sport_name']} / {event_id}")
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


def issue_label(issue_type):
    labels = {
        "live_product3_visible": "滚球盘不应显示 product=3",
        "live_no_product1_still_visible_in_today": "无 product=1 但仍显示在 today 列表",
    }
    return labels.get(issue_type, issue_type)
