#!/usr/bin/env python3
"""
Validate the committed data files.

Runs in CI on every push that touches data/, so a hand-edit typo gets caught
immediately rather than silently breaking the app. Also runnable locally:

    python3 scripts/validate_data.py

Exit 0 = all good. Exit 1 = problems (listed).

This checks the FILES ON DISK. It's the guard for human edits.
fetch_results.py has its own, stricter guard for data coming from ESPN.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_results import KNOWN_TEAMS, MAX_PLAUSIBLE_SCORE  # single source of truth

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
VALID_STATUS = {"scheduled", "in", "final"}

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def check_season():
    p = os.path.join(DATA_DIR, "season.json")
    if not os.path.exists(p):
        err("data/season.json is missing")
        return None
    try:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
    except json.JSONDecodeError as e:
        err(f"season.json is not valid JSON: {e}")
        return None
    for k in ("season", "name", "totalWeeks"):
        if k not in s:
            err(f"season.json missing required key {k!r}")
    return s


def check_week_file(path, season):
    name = os.path.relpath(path, REPO_ROOT)
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except json.JSONDecodeError as e:
        err(f"{name}: INVALID JSON - {e}. "
            "Common causes: a trailing comma, a missing bracket, or a score in quotes.")
        return

    if "games" not in d or not isinstance(d["games"], list):
        err(f"{name}: no 'games' list")
        return

    week_no = d.get("week")
    ids = set()
    teams_seen = []

    for i, g in enumerate(d["games"]):
        where = f"{name} game[{i}] (id={g.get('id')})"

        gid = g.get("id")
        if not gid:
            err(f"{where}: missing 'id'. Never delete a game id.")
        elif gid in ids:
            err(f"{where}: duplicate id {gid}")
        else:
            ids.add(gid)

        for side in ("home", "away"):
            t = g.get(side)
            if t not in KNOWN_TEAMS:
                err(f"{where}: {side} team {t!r} is not a known NFL code")
            else:
                teams_seen.append(t)

        ko = g.get("kickoff")
        if not ko:
            err(f"{where}: missing 'kickoff' - this is the lock time, it's required")
        else:
            try:
                datetime.fromisoformat(str(ko).replace("Z", "+00:00"))
            except ValueError:
                err(f"{where}: kickoff {ko!r} isn't a valid UTC timestamp "
                    "(expected e.g. 2026-09-10T00:20Z)")

        st = g.get("status")
        if st not in VALID_STATUS:
            err(f"{where}: status {st!r} invalid. Must be one of {sorted(VALID_STATUS)}")

        hs, as_ = g.get("homeScore"), g.get("awayScore")
        for label, s in (("homeScore", hs), ("awayScore", as_)):
            if s is None:
                continue
            if isinstance(s, str):
                err(f"{where}: {label} is the string {s!r} - remove the quotes, "
                    "scores must be plain numbers")
            elif not isinstance(s, int):
                err(f"{where}: {label} must be a whole number, got {type(s).__name__}")
            elif s < 0 or s > MAX_PLAUSIBLE_SCORE:
                err(f"{where}: {label} of {s} isn't plausible")

        if (hs is None) != (as_ is None):
            err(f"{where}: only one score filled in ({hs}/{as_}). Set both or neither.")

        if st == "final" and hs is None:
            err(f"{where}: status is 'final' but there's no score")
        if st == "scheduled" and hs is not None:
            err(f"{where}: has a score but status is still 'scheduled' - "
                "change it to \"final\"")

    dupes = {t for t in teams_seen if teams_seen.count(t) > 1}
    if dupes:
        err(f"{name}: team(s) play twice in week {week_no}: {sorted(dupes)}")

    if not (12 <= len(d["games"]) <= 16):
        warn(f"{name}: {len(d['games'])} games - unusual for an NFL week (expect 12-16)")


def main():
    season = check_season()
    year = str(season.get("season", 2026)) if season else "2026"
    wdir = os.path.join(DATA_DIR, year)

    if not os.path.isdir(wdir):
        err(f"data/{year}/ directory not found")
    else:
        files = sorted(f for f in os.listdir(wdir)
                       if f.startswith("week-") and f.endswith(".json"))
        if not files:
            err(f"data/{year}/ has no week files")
        for f in files:
            check_week_file(os.path.join(wdir, f), season)
        print(f"Checked {len(files)} week file(s) in data/{year}/")

    for w in warnings:
        print(f"WARNING: {w}")

    if errors:
        print(f"\n{len(errors)} PROBLEM(S) FOUND:\n")
        for e in errors:
            print(f"  ✗ {e}")
        print("\nNothing is broken permanently - fix the file and commit again,")
        print("or revert via the file's History tab on GitHub.")
        return 1

    print("All data files valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
