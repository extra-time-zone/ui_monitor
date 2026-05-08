import requests


class AlertClient:
    def __init__(self, webhook: str):
        self.webhook = webhook

    def send_system_alert(self, title: str, content: str):
        if not self.webhook:
            print("[SYSTEM ALERT] skipped: LARK_WEBHOOK empty", flush=True)
            return

        payload = {
            "msg_type": "text",
            "content": {
                "text": f"GOTOBET SYSTEM ALERT\n\n{title}\n\n{content}",
            },
        }
        self._post(payload, prefix="SYSTEM ALERT")

    def send_match_alert(self, match, reason: str, screenshot_path=None, extra: str = ""):
        if not self.webhook:
            print("[LARK] skipped: LARK_WEBHOOK empty", flush=True)
            return

        minutes = match.get("minutes")
        minute_text = f"{minutes}'" if minutes is not None else "not started"
        display_period = match.get("period") or match.get("scheduled_time") or ""
        match_id = match["match_id"]

        content = (
            "GOTOBET ALERT\n\n"
            f"reason: {reason}\n"
            f"match_id: {match_id}\n"
            f"match: {match.get('team1', '')} vs {match.get('team2', '')}\n"
            f"sport: {match.get('sport', '')}\n"
            f"country: {match.get('country', '')}\n"
            f"league: {match.get('league', '')}\n"
            f"period: {display_period}\n"
            f"minutes: {minute_text}\n"
            f"url: https://gotobet.com/en/matches/{match_id}\n"
        )

        sport_id = match.get("sport_id")
        if sport_id:
            content += f"sport_id: {sport_id}\n"

        if extra:
            content += f"\n{extra}\n"

        if screenshot_path:
            content += f"\nscreenshot: {screenshot_path}\n"

        payload = {
            "msg_type": "text",
            "content": {"text": content},
        }
        self._post(payload, prefix="LARK")

    def _post(self, payload, prefix: str):
        try:
            response = requests.post(self.webhook, json=payload, timeout=15)
            print(f"[{prefix} STATUS] {response.status_code}", flush=True)
            print(f"[{prefix} RESPONSE] {response.text}", flush=True)
        except Exception as exc:
            print(f"[{prefix} ERROR] {exc}", flush=True)
