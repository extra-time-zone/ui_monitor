import time


class MatchStateStore:
    def __init__(self, name: str):
        self.name = name
        self.states = {}

    def mark_seen(self, match_id: str, now: float, reappear_alert_seconds: int):
        is_new = match_id not in self.states
        is_reappeared = False
        reappeared_after = 0

        if is_new:
            self.states[match_id] = {
                "visible": True,
                "first_seen": now,
                "last_seen": now,
                "missing_count": 0,
                "reappear_count": 0,
                "last_disappeared_at": None,
            }
            return is_new, is_reappeared, reappeared_after, self.states[match_id]

        state = self.states[match_id]
        if state["visible"] is False:
            disappeared_at = state.get("last_disappeared_at")
            reappeared_after = int(now - disappeared_at) if disappeared_at else 0

            if reappeared_after >= reappear_alert_seconds:
                is_reappeared = True
                state["reappear_count"] += 1
                print(
                    f"[REAPPEARED] {self.name} {match_id} "
                    f"after {reappeared_after}s",
                    flush=True,
                )

        state["visible"] = True
        state["last_seen"] = now
        state["missing_count"] = 0
        return is_new, is_reappeared, reappeared_after, state

    def mark_missing(self, current_ids, missing_threshold: int, now: float):
        for match_id, state in list(self.states.items()):
            if match_id in current_ids:
                continue

            state["missing_count"] += 1

            if state["missing_count"] >= missing_threshold and state["visible"] is True:
                state["visible"] = False
                state["last_disappeared_at"] = now
                print(
                    f"[DISAPPEARED] {self.name} {match_id} "
                    f"missing_count={state['missing_count']}",
                    flush=True,
                )

    def cleanup_old(self, expire_seconds: int):
        now = time.time()
        expired = [
            match_id
            for match_id, state in self.states.items()
            if now - state.get("last_seen", 0) > expire_seconds
        ]

        for match_id in expired:
            del self.states[match_id]

        if expired:
            print(
                f"[CLEANUP] {self.name} removed {len(expired)} old matches",
                flush=True,
            )
