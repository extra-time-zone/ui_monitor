import re
from datetime import datetime


def reset_scroll_to_top(page):
    page.evaluate(
        """
        () => {
          window.scrollTo(0, 0);

          [...document.querySelectorAll("*")].forEach(el => {
            if (el.scrollHeight > el.clientHeight + 50) {
              el.scrollTop = 0;
            }
          });
        }
        """
    )


def scroll_down_once(page, amount=900):
    page.evaluate(
        """
        amount => {
          window.scrollBy(0, amount);

          [...document.querySelectorAll("*")].forEach(el => {
            if (el.scrollHeight > el.clientHeight + 50) {
              el.scrollTop += amount;
            }
          });
        }
        """,
        amount,
    )


def scroll_to_match(page, match_id, max_steps=100):
    selector = f'a[href*="/matches/{match_id}"]'

    reset_scroll_to_top(page)
    page.wait_for_timeout(800)

    for _ in range(max_steps):
        locator = page.locator(selector).first

        try:
            if locator.count() > 0:
                locator.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(800)
                return locator
        except Exception:
            pass

        scroll_down_once(page, 700)
        page.wait_for_timeout(500)

    return None


def get_page_counts(page):
    text = page.locator("body").inner_text(timeout=30000)

    top = re.search(r"\bLive\s+(\d+)\b", text, re.I)
    right = re.search(r"\bMATCHES\s+(\d+)\b", text, re.I)

    return {
        "top_live_count": int(top.group(1)) if top else None,
        "right_matches_count": int(right.group(1)) if right else None,
    }


def parse_visible_matches(page):
    return page.evaluate(
        """
        () => {
          const links = [...document.querySelectorAll('a[href*="/matches/"]')];
          const out = [];

          for (const a of links) {
            const href = a.href || a.getAttribute("href") || "";
            const matchId = (href.match(/\\/matches\\/(\\d+)/) || [])[1] || "";
            const title = (a.innerText || "").trim();

            if (!matchId || !title || !title.includes(" vs ")) continue;

            let best = null;
            let el = a;

            for (let i = 0; i < 12 && el; i++) {
              const txt = (el.innerText || "").trim();

              if (
                txt.includes(title) &&
                txt.length > title.length &&
                txt.length < 4500
              ) {
                best = txt;
                break;
              }

              el = el.parentElement;
            }

            out.push({
              match_id: matchId,
              title,
              raw: best || a.parentElement?.innerText || title
            });
          }

          return out;
        }
        """
    )


def parse_match(item, sport_id=None, sport_name=None):
    raw = item["raw"]
    title = item["title"]

    lines = [line.strip() for line in raw.splitlines() if line.strip()]

    parts = title.split(" vs ")
    team1 = parts[0].strip()
    team2 = " vs ".join(parts[1:]).strip()

    title_index = lines.index(title) if title in lines else 0
    after = lines[title_index + 1 :]

    sport = sport_name or (after[0] if len(after) > 0 else "")
    country = after[1] if len(after) > 1 else ""
    league = after[2] if len(after) > 2 else ""

    period = ""
    minutes = None
    scheduled_time = ""
    clock_time = ""
    negative_time = ""

    for line in after:
        if re.search(
            r"\d+(st|nd|rd|th)\s+(Set|Half|Quarter)"
            r"|LIVE"
            r"|Break Time"
            r"|Half Time"
            r"|today,\s*\d{2}:\d{2}",
            line,
            re.I,
        ):
            period = line

        if re.search(r"today,\s*\d{2}:\d{2}", line, re.I):
            scheduled_time = line

        minute_match = re.search(r"(\d+)'", line)
        if minute_match:
            minutes = int(minute_match.group(1))

        negative_match = re.search(r"-\d{1,3}:\d{2}|-\d+'", line)
        if negative_match:
            negative_time = negative_match.group(0)

        clock_match = re.search(r"(?<!-)\b\d{1,3}:\d{2}\b", line)
        if clock_match:
            clock_time = clock_match.group(0)

    status_missing = (
        not period
        and not scheduled_time
        and minutes is None
        and not clock_time
        and not negative_time
    )

    return {
        "match_id": item["match_id"],
        "title": title,
        "team1": team1,
        "team2": team2,
        "sport": sport,
        "sport_id": sport_id,
        "country": country,
        "league": league,
        "period": period,
        "scheduled_time": scheduled_time,
        "minutes": minutes,
        "clock_time": clock_time,
        "negative_time": negative_time,
        "status_missing": status_missing,
        "raw": raw,
    }


def collect_all_matches(
    page,
    sport_id=None,
    sport_name=None,
    max_scrolls=100,
    stable_round_limit=12,
    scroll_wait_ms=650,
):
    collected = {}

    reset_scroll_to_top(page)
    page.wait_for_timeout(1000)

    stable_rounds = 0
    last_count = 0

    for _ in range(max_scrolls):
        visible = parse_visible_matches(page)

        for item in visible:
            parsed = parse_match(item, sport_id=sport_id, sport_name=sport_name)
            collected[parsed["match_id"]] = parsed

        current_count = len(collected)

        if current_count == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0

        last_count = current_count

        if stable_rounds >= stable_round_limit:
            break

        scroll_down_once(page, 900)
        page.wait_for_timeout(scroll_wait_ms)

    return list(collected.values())


def has_decimal_odds(text):
    return bool(re.search(r"\b\d+\.\d+\b", text or ""))


def market_status_of_match(match):
    raw = match.get("raw", "")

    if has_decimal_odds(raw):
        return "normal"

    if "Live market offers will be back soon" in raw:
        return "unavailable"

    if "Under/Over" in raw or "Home" in raw or "Away" in raw:
        return "unavailable"

    return "unavailable"


def check_all_markets_down(matches):
    if not matches:
        return False, 0, 0

    normal = 0
    unavailable = 0

    for match in matches:
        status = market_status_of_match(match)
        if status == "normal":
            normal += 1
        else:
            unavailable += 1

    return normal == 0 and unavailable == len(matches), normal, unavailable


def scheduled_time_is_stale(scheduled_time: str, grace_minutes: int) -> bool:
    match = re.search(r"today,\s*(\d{2}):(\d{2})", scheduled_time or "", re.I)
    if not match:
        return False

    hour = int(match.group(1))
    minute = int(match.group(2))

    now = datetime.now()
    scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return (now - scheduled_at).total_seconds() >= grace_minutes * 60


def has_negative_time(match) -> bool:
    if match.get("negative_time"):
        return True
    return bool(re.search(r"-\d{1,3}:\d{2}|-\d+'", match.get("raw") or ""))


def has_missing_status_field(match) -> bool:
    return bool(match.get("status_missing"))
