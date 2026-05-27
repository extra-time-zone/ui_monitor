import time
from datetime import datetime

import requests

from config import sport_name, today_range_ms
from gotobet_api import build_headers, fetch_top_sports
from parsers import (
    check_all_markets_down,
    collect_all_matches,
    has_missing_status_field,
    has_negative_time,
    scheduled_time_is_stale,
)
from state import MatchStateStore


class SportsTodayMonitor:
    def __init__(self, settings, browser_manager, alerts, screenshotter, deduper=None):
        self.settings = settings
        self.browser_manager = browser_manager
        self.alerts = alerts
        self.screenshotter = screenshotter
        self.deduper = deduper
        self.states = {
            sport_id: MatchStateStore(f"today:{sport_id}")
            for sport_id in self.settings.sport_ids
        }
        self.market_down_rounds = {sport_id: 0 for sport_id in self.settings.sport_ids}
        self.empty_page_rounds = {}
        self.system_alerted_dates = {}

    @property
    def interval(self):
        return self.settings.today_check_interval

    def run_once(self):
        sports = self._sports_to_monitor()
        print(
            "[TODAY] sports="
            + ",".join(f"{item['sport_id']}:{item['name']}" for item in sports),
            flush=True,
        )
        for sport in sports:
            self._run_sport_once(sport["sport_id"], sport["name"])

    def _sports_to_monitor(self):
        if self.settings.today_sport_ids_source == "top":
            try:
                headers = build_headers(self.settings)
                with requests.Session() as session:
                    sports = fetch_top_sports(session, self.settings, headers)
                if sports:
                    return sports
                print("[TODAY] top sports API returned empty, using SPORT_IDS fallback", flush=True)
            except Exception as exc:
                print(f"[TODAY] top sports API failed: {exc}", flush=True)

        return [
            {"sport_id": sport_id, "name": sport_name(sport_id)}
            for sport_id in self.settings.sport_ids
        ]

    def _run_sport_once(self, sport_id: str, name: str):
        now = time.time()
        url = self._today_url(sport_id)
        page = self.browser_manager.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(3000)
            matches = collect_all_matches(
                page,
                sport_id=sport_id,
                sport_name=name,
                max_scrolls=self.settings.collect_max_scrolls,
                stable_round_limit=self.settings.collect_stable_rounds,
                scroll_wait_ms=self.settings.collect_scroll_wait_ms,
            )
            current_ids = set()

            all_markets_down, normal_market_count, unavailable_market_count = (
                check_all_markets_down(matches)
            )

            print(f"\n============ TODAY {sport_id} {name} ============", flush=True)
            print(f"URL                 : {url}", flush=True)
            print(f"SCRIPT parsed count : {len(matches)}", flush=True)
            print(f"MARKET normal       : {normal_market_count}", flush=True)
            print(f"MARKET unavailable  : {unavailable_market_count}", flush=True)

            self._check_all_markets_down(
                sport_id,
                name,
                url,
                all_markets_down,
                len(matches),
                normal_market_count,
                unavailable_market_count,
            )
            self._check_empty_page(sport_id, name, url, len(matches))

            store = self.states.setdefault(sport_id, MatchStateStore(f"today:{sport_id}"))

            for match in matches:
                match_id = match["match_id"]
                current_ids.add(match_id)

                _, is_reappeared, reappeared_after, state = store.mark_seen(
                    match_id,
                    now,
                    self.settings.today_reappear_alert_seconds,
                )

                self._print_match(match)

                alert, reason = self._should_alert(match, is_reappeared)
                if not alert:
                    continue

                display_period = (
                    match.get("period") or match.get("scheduled_time") or ""
                )
                key = self._alert_key(sport_id, match, reason, display_period)
                if not self._should_send_alert_key(key, now):
                    continue

                shot_path = self.screenshotter.save(
                    page,
                    match_id,
                    match["title"],
                    reason,
                )

                extra = ""
                if reason == "today_reappeared_match":
                    extra = (
                        f"reappeared_after: {reappeared_after}s\n"
                        f"reappear_count: {state['reappear_count']}"
                    )
                elif reason == "negative_match_time":
                    extra = f"negative_time: {match.get('negative_time') or '-'}"
                elif reason == "missing_status_field":
                    extra = "status_field: missing period/scheduled_time/minutes"

                self.alerts.send_match_alert(match, reason, shot_path, extra)
                self._print_alert(match, reason, shot_path)

            store.mark_missing(
                current_ids,
                self.settings.today_missing_threshold,
                now,
            )
            store.cleanup_old(self.settings.match_expire_seconds)
            print("========================================\n", flush=True)

        finally:
            try:
                page.close()
            except Exception:
                pass

    def _today_url(self, sport_id: str):
        from_ms, to_ms = today_range_ms()
        return (
            f"https://gotobet.com/en/sports/{sport_id}"
            f"?from={from_ms}&to={to_ms}"
        )

    def _check_all_markets_down(
        self,
        sport_id,
        name,
        url,
        all_markets_down,
        script_count,
        normal_market_count,
        unavailable_market_count,
    ):
        if not all_markets_down:
            self.market_down_rounds[sport_id] = 0
            return

        self.market_down_rounds[sport_id] = (
            self.market_down_rounds.get(sport_id, 0) + 1
        )
        rounds = self.market_down_rounds[sport_id]
        print(
            f"[TODAY ALL MARKETS DOWN] sport_id={sport_id} rounds={rounds}",
            flush=True,
        )

        if rounds >= self.settings.today_market_down_threshold:
            if not self._can_send_daily_system_alert(
                f"TODAY_ALL_MARKETS_DOWN:{sport_id}"
            ):
                self.market_down_rounds[sport_id] = 0
                return

            self.alerts.send_system_alert(
                "TODAY_ALL_MARKETS_DOWN",
                (
                    f"sport_id={sport_id}\n"
                    f"sport={name}\n"
                    "all parsed today matches have unavailable/locked markets "
                    f"for {rounds} rounds\n"
                    f"total_matches={script_count}\n"
                    f"normal_market_count={normal_market_count}\n"
                    f"unavailable_market_count={unavailable_market_count}\n"
                    f"url={url}"
                ),
            )
            self.market_down_rounds[sport_id] = 0

    def _check_empty_page(self, sport_id, name, url, script_count):
        if script_count > 0:
            self.empty_page_rounds[sport_id] = 0
            return

        self.empty_page_rounds[sport_id] = self.empty_page_rounds.get(sport_id, 0) + 1
        rounds = self.empty_page_rounds[sport_id]
        print(
            f"[TODAY PAGE NO MATCHES] sport_id={sport_id} rounds={rounds}",
            flush=True,
        )

        if rounds < self.settings.today_empty_page_threshold:
            return
        if not self._can_send_daily_system_alert(f"TODAY_PAGE_NO_MATCHES:{sport_id}"):
            self.empty_page_rounds[sport_id] = 0
            return

        self.alerts.send_system_alert(
            "TODAY_PAGE_NO_MATCHES",
            (
                f"sport_id={sport_id}\n"
                f"sport={name}\n"
                f"today page parsed zero matches for {rounds} rounds\n"
                f"url={url}"
            ),
        )
        self.empty_page_rounds[sport_id] = 0

    def _should_alert(self, match, is_reappeared):
        if has_negative_time(match):
            return True, "negative_match_time"

        if has_missing_status_field(match):
            return True, "missing_status_field"

        if (
            match.get("scheduled_time")
            and match.get("minutes") is None
            and scheduled_time_is_stale(
                match.get("scheduled_time"),
                self.settings.today_start_grace_minutes,
            )
        ):
            return True, "scheduled_match_not_started"

        if is_reappeared:
            return True, "today_reappeared_match"

        return False, ""

    def _can_send_daily_system_alert(self, key):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.system_alerted_dates.get(key) == today:
            return False
        self.system_alerted_dates[key] = today
        return True

    def _should_send_alert_key(self, key, now):
        if self.deduper is None:
            return True
        return self.deduper.should_alert(key, now)

    @staticmethod
    def _alert_key(sport_id, match, reason, display_period):
        match_id = match["match_id"]
        if reason in {
            "today_reappeared_match",
            "scheduled_match_not_started",
            "negative_match_time",
            "missing_status_field",
        }:
            return f"today:{sport_id}:{match_id}:{reason}"
        return f"today:{sport_id}:{match_id}:{reason}:{display_period}"

    @staticmethod
    def _print_match(match):
        minute_text = (
            f"{match['minutes']}'" if match.get("minutes") is not None else "not started"
        )
        display_period = match.get("period") or match.get("scheduled_time") or ""

        print(
            f"[{match['match_id']}] sport_id={match.get('sport_id')} "
            f"{match.get('team1', '')} vs {match.get('team2', '')} | "
            f"{match.get('sport', '')} | {match.get('country', '')} | "
            f"{match.get('league', '')} | {display_period} | {minute_text}",
            flush=True,
        )

    @staticmethod
    def _print_alert(match, reason, shot_path):
        display_period = match.get("period") or match.get("scheduled_time") or ""
        minute_text = (
            f"{match['minutes']}'" if match.get("minutes") is not None else "not started"
        )

        print("\nTODAY ALERT", flush=True)
        print(f"reason   : {reason}", flush=True)
        print(f"sport_id : {match.get('sport_id')}", flush=True)
        print(f"match_id : {match['match_id']}", flush=True)
        print(f"match    : {match.get('team1', '')} vs {match.get('team2', '')}", flush=True)
        print(f"period   : {display_period}", flush=True)
        print(f"minutes  : {minute_text}", flush=True)
        print(f"screenshot: {shot_path}\n", flush=True)
