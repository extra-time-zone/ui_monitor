import time
from datetime import datetime

from parsers import (
    check_all_markets_down,
    collect_all_matches,
    get_page_counts,
    has_missing_status_field,
    has_negative_time,
    scheduled_time_is_stale,
)
from state import MatchStateStore


class LiveMonitor:
    def __init__(self, settings, browser_manager, alerts, screenshotter, deduper=None):
        self.settings = settings
        self.browser_manager = browser_manager
        self.alerts = alerts
        self.screenshotter = screenshotter
        self.deduper = deduper
        self.state = MatchStateStore("live")
        self.count_mismatch_rounds = 0
        self.market_down_rounds = 0
        self.empty_page_rounds = 0
        self.system_alerted_dates = {}
        self.page = None

    @property
    def interval(self):
        return self.settings.live_check_interval

    def close_page(self):
        if self.page is not None:
            try:
                self.page.close()
            except Exception:
                pass
        self.page = None

    def ensure_page(self):
        if self.page is None or self.page.is_closed():
            self.page = self.browser_manager.new_page()
            self.page.goto(
                self.settings.url,
                wait_until="domcontentloaded",
                timeout=120000,
            )
            self.page.wait_for_timeout(3000)
        return self.page

    def run_once(self):
        now = time.time()
        page = self.ensure_page()

        page.goto(self.settings.url, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(3000)

        counts = get_page_counts(page)
        matches = collect_all_matches(
            page,
            max_scrolls=self.settings.collect_max_scrolls,
            stable_round_limit=self.settings.collect_stable_rounds,
            scroll_wait_ms=self.settings.collect_scroll_wait_ms,
        )
        current_ids = set()

        top_count = counts["top_live_count"]
        right_count = counts["right_matches_count"]
        script_count = len(matches)

        all_markets_down, normal_market_count, unavailable_market_count = (
            check_all_markets_down(matches)
        )

        print("\n================ LIVE ================", flush=True)
        print(f"TOP Live count       : {top_count}", flush=True)
        print(f"RIGHT MATCHES count  : {right_count}", flush=True)
        print(f"SCRIPT parsed count  : {script_count}", flush=True)
        print(f"MARKET normal        : {normal_market_count}", flush=True)
        print(f"MARKET unavailable   : {unavailable_market_count}", flush=True)

        self._check_count_mismatch(top_count, right_count, script_count)
        self._check_all_markets_down(
            all_markets_down,
            script_count,
            normal_market_count,
            unavailable_market_count,
        )
        self._check_empty_page(top_count, right_count, script_count)

        for match in matches:
            match_id = match["match_id"]
            current_ids.add(match_id)

            is_new, is_reappeared, reappeared_after, state = self.state.mark_seen(
                match_id,
                now,
                self.settings.reappear_alert_seconds,
            )

            self._print_match(match)

            alert, reason = self._should_alert(match, is_new, is_reappeared)
            if not alert:
                continue

            display_period = match.get("period") or match.get("scheduled_time") or ""
            key = self._alert_key(match, reason, display_period)
            if not self._should_send_alert_key(key, now):
                continue

            shot_path = self.screenshotter.save(
                page,
                match_id,
                match["title"],
                reason,
            )

            extra = ""
            if reason == "reappeared_match":
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

        self.state.mark_missing(current_ids, self.settings.missing_threshold, now)
        self.state.cleanup_old(self.settings.match_expire_seconds)
        print("======================================\n", flush=True)

    def _check_count_mismatch(self, top_count, right_count, script_count):
        if top_count is None or right_count is None:
            return

        expected = max(top_count, right_count)
        if script_count == expected:
            self.count_mismatch_rounds = 0
            return

        self.count_mismatch_rounds += 1
        print(f"[COUNT MISMATCH] rounds={self.count_mismatch_rounds}", flush=True)

        if self.count_mismatch_rounds >= self.settings.count_mismatch_threshold:
            self.alerts.send_system_alert(
                "COUNT MISMATCH",
                (
                    f"count mismatch persisted for {self.count_mismatch_rounds} rounds\n"
                    f"top_live_count={top_count}\n"
                    f"right_matches_count={right_count}\n"
                    f"script_parsed_count={script_count}\n"
                    f"url={self.settings.url}"
                ),
            )
            self.count_mismatch_rounds = 0

    def _check_all_markets_down(
        self,
        all_markets_down,
        script_count,
        normal_market_count,
        unavailable_market_count,
    ):
        if not all_markets_down:
            self.market_down_rounds = 0
            return

        self.market_down_rounds += 1
        print(f"[ALL MARKETS DOWN] rounds={self.market_down_rounds}", flush=True)

        if self.market_down_rounds >= self.settings.market_down_threshold:
            self.alerts.send_system_alert(
                "ALL MARKETS DOWN",
                (
                    "all parsed live matches have unavailable/locked markets "
                    f"for {self.market_down_rounds} rounds\n"
                    f"total_matches={script_count}\n"
                    f"normal_market_count={normal_market_count}\n"
                    f"unavailable_market_count={unavailable_market_count}\n"
                    f"url={self.settings.url}"
                ),
            )
            self.market_down_rounds = 0

    def _check_empty_page(self, top_count, right_count, script_count):
        expected = max(
            [count for count in (top_count, right_count) if count is not None],
            default=0,
        )
        if script_count > 0 or expected <= 0:
            self.empty_page_rounds = 0
            return

        self.empty_page_rounds += 1
        print(f"[LIVE PAGE NO MATCHES] rounds={self.empty_page_rounds}", flush=True)

        if self.empty_page_rounds < self.settings.live_empty_page_threshold:
            return
        if not self._can_send_daily_system_alert("LIVE_PAGE_NO_MATCHES"):
            self.empty_page_rounds = 0
            return

        self.alerts.send_system_alert(
            "LIVE_PAGE_NO_MATCHES",
            (
                "live page parsed zero matches while page counters indicate matches\n"
                f"top_live_count={top_count}\n"
                f"right_matches_count={right_count}\n"
                f"script_parsed_count={script_count}\n"
                f"rounds={self.empty_page_rounds}\n"
                f"url={self.settings.url}"
            ),
        )
        self.empty_page_rounds = 0

    def _should_alert(self, match, is_new_match, is_reappeared):
        if has_negative_time(match):
            return True, "negative_match_time"

        if has_missing_status_field(match):
            return True, "missing_status_field"

        if scheduled_time_is_stale(
            match.get("scheduled_time"),
            self.settings.scheduled_stale_grace_minutes,
        ):
            return True, "stale_scheduled_match"

        if (
            is_new_match
            and match.get("minutes") is not None
            and match["minutes"] >= self.settings.new_match_alert_minutes
        ):
            return True, "new_match_late_insert"

        if match.get("minutes") is not None and match["minutes"] >= self.settings.limit:
            return True, f"over_{self.settings.limit}"

        if is_reappeared:
            return True, "reappeared_match"

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
    def _alert_key(match, reason, display_period):
        match_id = match["match_id"]
        if reason.startswith("over_"):
            return f"live:{match_id}:over_limit:{reason}"
        if reason in {
            "reappeared_match",
            "new_match_late_insert",
            "negative_match_time",
            "missing_status_field",
        }:
            return f"live:{match_id}:{reason}"
        if reason == "stale_scheduled_match":
            return f"live:{match_id}:{reason}:{display_period}"
        return f"live:{match_id}:{reason}"

    @staticmethod
    def _print_match(match):
        minute_text = (
            f"{match['minutes']}'" if match.get("minutes") is not None else "not started"
        )
        display_period = match.get("period") or match.get("scheduled_time") or ""

        print(
            f"[{match['match_id']}] "
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

        print("\nALERT", flush=True)
        print(f"reason   : {reason}", flush=True)
        print(f"match_id : {match['match_id']}", flush=True)
        print(f"match    : {match.get('team1', '')} vs {match.get('team2', '')}", flush=True)
        print(f"period   : {display_period}", flush=True)
        print(f"minutes  : {minute_text}", flush=True)
        print(f"screenshot: {shot_path}\n", flush=True)
