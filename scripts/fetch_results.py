#!/usr/bin/env python3
"""
Hit Paydirt NFL League — schedule & results fetcher
===================================================

WHAT THIS DOES
--------------
Pulls the NFL schedule/scores from ESPN's free public endpoint and writes them
into data/2026/week-NN.json, one file per week. Run on a schedule by GitHub
Actions (see .github/workflows/fetch-results.yml).

WHY IT'S BUILT THIS WAY (read before changing anything)
-------------------------------------------------------
1. FAIL-SAFE, NOT FAIL-BROKEN. The dangerous failure isn't a crash - it's a
   silent one, where ESPN changes shape, the fetch "succeeds", and we commit
   an empty/garbage schedule. So NOTHING is written unless every validation
   passes. If validation fails we exit non-zero, GitHub emails Richard, and
   the previous good data stays untouched.

2. FINAL SCORES ARE IMMUTABLE. Once a game has a final score in our file, we
   never overwrite it. Protects historic results from an upstream glitch.

3. KICKOFFS MOVE, AND THAT'S EXPECTED. The NFL flexes games. Weeks 17-18 times
   aren't even set until after Weeks 15/17. So changing the date/time of an
   UNPLAYED game is normal and allowed - we just record that it moved so the
   app can flag it. Changing a PLAYED game is not allowed.

4. NO BETTING DATA. The ESPN payload is full of DraftKings odds. This league is
   bragging rights only. We deliberately strip all of it and never store it.

ESPN ENDPOINT (undocumented, unofficial, free)
----------------------------------------------
  https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
    ?dates=2026&seasontype=2&week=N
  seasontype: 1=preseason, 2=regular, 3=postseason
  Expect this to break roughly once a season. When it does, the validation
  error will say which check failed - that's the starting point for a fix.

USAGE
  python3 scripts/fetch_results.py --weeks 1 2 3     # specific weeks
  python3 scripts/fetch_results.py --auto            # current + previous week
  python3 scripts/fetch_results.py --all             # full season (initial build)
  python3 scripts/fetch_results.py --auto --dry-run  # show changes, write nothing
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SEASON_YEAR = 2026
SEASON_TYPE_REGULAR = 2
TOTAL_WEEKS = 18

BASE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    "?dates={year}&seasontype={stype}&week={week}"
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data", str(SEASON_YEAR))

# The 32 team abbreviations we expect from ESPN. If a code appears that isn't
# in here, something upstream changed (relocation, rebrand, or schema change)
# and we should stop rather than write junk.
KNOWN_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB",  "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV",  "MIA", "MIN", "NE",  "NO",  "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF",  "TB",  "TEN", "WSH",
}

# Sanity bounds for a final score. The record NFL team score is 73.
# Anything above MAX_PLAUSIBLE_SCORE means the field isn't what we think it is.
MAX_PLAUSIBLE_SCORE = 100

# A week should have 13-16 games (byes reduce it from 16).
# Week 1 has no byes so it's always 16.
MIN_GAMES_PER_WEEK = 12
MAX_GAMES_PER_WEEK = 16

# If more than this fraction of a week's games change identity (teams), assume
# the feed is wrong rather than that the NFL rewrote the schedule.
MAX_MATCHUP_CHURN = 0.25


class ValidationError(Exception):
    """Raised when fetched data fails a safety check. Nothing gets written."""


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_week(week, retries=3, timeout=30):
    """GET one week of the scoreboard. Retries on transient network errors."""
    url = BASE_URL.format(year=SEASON_YEAR, stype=SEASON_TYPE_REGULAR, week=week)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    # ESPN 403s a bare urllib UA.
                    "User-Agent": "Mozilla/5.0 (compatible; HitPaydirtLeague/1.0)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise ValidationError(f"Week {week}: HTTP {resp.status}")
                raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValidationError(
                    f"Week {week}: response was not valid JSON ({e}). "
                    "ESPN may be returning an error page."
                )
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 * attempt)
            continue
    raise ValidationError(f"Week {week}: network failed after {retries} tries: {last_err}")


# ---------------------------------------------------------------------------
# Parse — turn ESPN's sprawling payload into our small, clean shape
# ---------------------------------------------------------------------------

def parse_game(event):
    """
    Extract only what we need from one ESPN event.

    Our shape:
      id        - ESPN event id (stable, used as the pick key. NEVER regenerate)
      kickoff   - ISO8601 UTC. Single source of truth for per-game locking.
      home/away - team abbreviations
      homeScore/awayScore - ints, or None if not final
      status    - scheduled | in | final
      venue, neutralSite, tbdFlex - context/flags
    """
    comps = event.get("competitions") or []
    if not comps:
        raise ValidationError(f"Event {event.get('id')} has no competitions block")
    comp = comps[0]

    competitors = comp.get("competitors") or []
    if len(competitors) != 2:
        raise ValidationError(
            f"Event {event.get('id')} has {len(competitors)} competitors, expected 2"
        )

    home = away = None
    for c in competitors:
        abbr = (c.get("team") or {}).get("abbreviation")
        score_raw = c.get("score")
        side = {"abbr": abbr, "score": score_raw}
        if c.get("homeAway") == "home":
            home = side
        elif c.get("homeAway") == "away":
            away = side

    if not home or not away:
        raise ValidationError(f"Event {event.get('id')}: missing home or away side")

    status_block = (comp.get("status") or {}).get("type") or {}
    completed = bool(status_block.get("completed"))
    state = status_block.get("state")  # pre | in | post

    if completed:
        status = "final"
    elif state == "in":
        status = "in"
    else:
        status = "scheduled"

    def to_score(v):
        # Only trust scores on completed games. ESPN reports "0" for
        # not-yet-played games, which must NOT become a real 0-0 result.
        if not completed:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Event {event.get('id')}: score {v!r} is not an integer"
            )

    venue = (comp.get("venue") or {}).get("fullName")

    return {
        "id": str(event.get("id")),
        "kickoff": comp.get("date") or event.get("date"),
        "home": home["abbr"],
        "away": away["abbr"],
        "homeScore": to_score(home["score"]),
        "awayScore": to_score(away["score"]),
        "status": status,
        "venue": venue,
        "neutralSite": bool(comp.get("neutralSite")),
        "tbdFlex": bool((comp.get("status") or {}).get("isTBDFlex")),
    }
    # NOTE: comp["odds"] is deliberately ignored. No betting data. See docstring.


def parse_week(payload, week):
    events = payload.get("events")
    if events is None:
        raise ValidationError(
            f"Week {week}: no 'events' key in response. ESPN schema likely changed."
        )
    games = [parse_game(e) for e in events]
    games.sort(key=lambda g: (g["kickoff"] or "", g["id"]))
    return {
        "week": week,
        "season": SEASON_YEAR,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "games": games,
    }


# ---------------------------------------------------------------------------
# Validate — the gate. Nothing is written unless all of this passes.
# ---------------------------------------------------------------------------

def validate_week(new, old, week):
    """Raise ValidationError on anything suspicious. Silence = pass."""
    games = new["games"]

    # 1. Plausible number of games.
    if not (MIN_GAMES_PER_WEEK <= len(games) <= MAX_GAMES_PER_WEEK):
        raise ValidationError(
            f"Week {week}: got {len(games)} games, expected "
            f"{MIN_GAMES_PER_WEEK}-{MAX_GAMES_PER_WEEK}. Refusing to write."
        )

    # 2. Known teams only, and nobody plays twice in a week.
    seen = []
    for g in games:
        for t in (g["home"], g["away"]):
            if t not in KNOWN_TEAMS:
                raise ValidationError(
                    f"Week {week}: unknown team code {t!r} in game {g['id']}. "
                    "ESPN schema may have changed."
                )
            seen.append(t)
    dupes = {t for t in seen if seen.count(t) > 1}
    if dupes:
        raise ValidationError(f"Week {week}: team(s) appear twice: {sorted(dupes)}")

    # 3. Every game needs a parseable kickoff — it IS the lock time.
    for g in games:
        if not g["kickoff"]:
            raise ValidationError(f"Week {week}: game {g['id']} has no kickoff time")
        try:
            datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError(
                f"Week {week}: game {g['id']} kickoff {g['kickoff']!r} unparseable"
            )

    # 4. Scores must be sane, and complete (never one-sided).
    for g in games:
        hs, as_ = g["homeScore"], g["awayScore"]
        if (hs is None) != (as_ is None):
            raise ValidationError(
                f"Week {week}: game {g['id']} has only one score ({hs}/{as_})"
            )
        for s in (hs, as_):
            if s is None:
                continue
            if not isinstance(s, int) or s < 0 or s > MAX_PLAUSIBLE_SCORE:
                raise ValidationError(
                    f"Week {week}: game {g['id']} implausible score {s}"
                )
        if g["status"] == "final" and hs is None:
            raise ValidationError(
                f"Week {week}: game {g['id']} is final but has no score"
            )

    if old is None:
        return  # First write for this week; nothing to diff against.

    old_by_id = {g["id"]: g for g in old.get("games", [])}

    # 5. NEVER change a game that already had a final score.
    for g in games:
        prev = old_by_id.get(g["id"])
        if not prev:
            continue
        if prev.get("status") == "final" and prev.get("homeScore") is not None:
            if (g["homeScore"], g["awayScore"]) != (prev["homeScore"], prev["awayScore"]):
                raise ValidationError(
                    f"Week {week}: game {g['id']} already final "
                    f"{prev['homeScore']}-{prev['awayScore']}, feed now says "
                    f"{g['homeScore']}-{g['awayScore']}. Refusing to rewrite history."
                )
            if (g["home"], g["away"]) != (prev["home"], prev["away"]):
                raise ValidationError(
                    f"Week {week}: game {g['id']} matchup changed after being played"
                )

    # 6. Matchups shouldn't churn. Kickoff times moving is fine (flex);
    #    teams swapping wholesale means we're looking at the wrong data.
    changed = 0
    for g in games:
        prev = old_by_id.get(g["id"])
        if prev and (g["home"], g["away"]) != (prev["home"], prev["away"]):
            changed += 1
    if old_by_id and changed / max(len(games), 1) > MAX_MATCHUP_CHURN:
        raise ValidationError(
            f"Week {week}: {changed}/{len(games)} matchups changed. "
            "That's implausible - refusing to write."
        )

    # 7. Games shouldn't vanish.
    missing = set(old_by_id) - {g["id"] for g in games}
    if missing:
        raise ValidationError(
            f"Week {week}: {len(missing)} game(s) disappeared: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# Merge — preserve history, record flex moves
# ---------------------------------------------------------------------------

def merge_week(new, old):
    """
    Combine fetched data with what we already have.
      - A game already final keeps its stored scores (belt & braces; validation
        already guarantees they match).
      - An unplayed game whose kickoff moved gets movedFrom set, so the app can
        show the flex flag.
    """
    if old is None:
        return new

    old_by_id = {g["id"]: g for g in old.get("games", [])}
    for g in new["games"]:
        prev = old_by_id.get(g["id"])
        if not prev:
            continue

        if prev.get("status") == "final":
            g["homeScore"] = prev["homeScore"]
            g["awayScore"] = prev["awayScore"]
            g["status"] = "final"
            # Keep any flex marker it already carried.
            if prev.get("movedFrom"):
                g["movedFrom"] = prev["movedFrom"]
            continue

        # Unplayed: did kickoff move? Record the ORIGINAL time once, so we
        # always show the move relative to when it was first published.
        if prev.get("kickoff") and prev["kickoff"] != g["kickoff"]:
            g["movedFrom"] = prev.get("movedFrom") or prev["kickoff"]
        elif prev.get("movedFrom"):
            g["movedFrom"] = prev["movedFrom"]

    return new


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def week_path(week):
    return os.path.join(DATA_DIR, f"week-{week:02d}.json")


def load_week(week):
    p = week_path(week)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_week(week, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(week_path(week), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def content_changed(new, old):
    """Ignore the 'updated' timestamp so we don't commit no-op churn."""
    if old is None:
        return True
    return new.get("games") != old.get("games")


def current_week_guess(payload):
    """ESPN tells us which week it thinks it is."""
    try:
        return int((payload.get("week") or {}).get("number"))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Fetch NFL results into week files")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--weeks", nargs="+", type=int, help="Specific week numbers")
    g.add_argument("--auto", action="store_true",
                   help="Current week + previous (catches late corrections)")
    g.add_argument("--all", action="store_true", help="All 18 weeks")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate and report, write nothing")
    args = ap.parse_args()

    if args.all:
        weeks = list(range(1, TOTAL_WEEKS + 1))
    elif args.weeks:
        weeks = args.weeks
    else:
        probe = fetch_week(1)
        cur = current_week_guess(probe) or 1
        weeks = sorted({max(1, cur - 1), cur})
        print(f"[auto] ESPN reports current week {cur} -> fetching {weeks}")

    for w in weeks:
        if not (1 <= w <= TOTAL_WEEKS):
            print(f"ERROR: week {w} out of range 1-{TOTAL_WEEKS}", file=sys.stderr)
            return 1

    changed_any = False
    for w in weeks:
        print(f"\n--- Week {w} ---")
        payload = fetch_week(w)
        new = parse_week(payload, w)
        old = load_week(w)

        validate_week(new, old, w)          # raises -> job fails -> email
        merged = merge_week(new, old)

        finals = sum(1 for x in merged["games"] if x["status"] == "final")
        moved = [x["id"] for x in merged["games"] if x.get("movedFrom")]
        print(f"  {len(merged['games'])} games, {finals} final, {len(moved)} moved")

        if not content_changed(merged, old):
            print("  no change")
            continue

        if args.dry_run:
            print("  [dry-run] would write")
        else:
            write_week(w, merged)
            print(f"  written -> {os.path.relpath(week_path(w), REPO_ROOT)}")
        changed_any = True
        time.sleep(1)  # be polite to a free endpoint

    print("\nDone." + ("" if changed_any else " Nothing to commit."))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as e:
        # This is the alarm. Non-zero exit -> GitHub Actions fails -> email.
        print(f"\n!! VALIDATION FAILED: {e}", file=sys.stderr)
        print("!! Nothing was written. Existing data is untouched.", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
