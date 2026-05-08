import time

from config import sport_name, today_range_ms
from parsers import check_all_markets_down, collect_all_matches, scheduled_time_is_stale
from state import MatchStateStore


class SportsTodayMonitor:
    def __init__(self, settings, browser_manager, alerts, screenshotter):
        self.settings = settings
        self.browser_manager = browser_manager
        self.alerts = alerts
        self.screenshotter = screenshotter
        self.states = {
            sport_id: MatchStateStore(f"today:{sport_id}")
            for sport_id in self.settings.sport_ids
        }
        self.seen_alerts = set()
        self.market_down_rounds = {sport_id: 0 for sport_id in self.settings.sport_ids}

    @property
    def interval(self):
        return self.settings.today_check_interval

    def run_once(self):
        for sport_id in self.settings.sport_ids:
            self._run_sport_once(sport_id)

    def _run_sport_once(self, sport_id: str):
        now = time.time()
        name = sport_name(sport_id)
        url = self._today_url(sport_id)
        page = self.browser_manager.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(3000)
            matches = collect_all_matches(page, sport_id=sport_id, sport_name=name)
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
                key = (
                    f"today:{sport_id}:{match_id}:{reason}:"
                    f"{match.get('minutes')}:{display_period}"
                )
                if key in self.seen_alerts:
                    continue

                self.seen_alerts.add(key)
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

    def _should_alert(self, match, is_reappeared):
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
