# Hit Paydirt NFL League

A six-player NFL prediction league for the **2026 season** (Wed 9 Sep 2026 –
Sun 10 Jan 2027, 18 weeks, 272 games). Bragging rights only, no money.

This repo holds the **schedule/results data pipeline**. The app itself
(`index.html`) reads these files.

---

## How it works in one paragraph

A GitHub Action runs a few times a week, pulls NFL scores from ESPN's free
public endpoint, validates them hard, and commits them into `data/2026/week-NN.json`.
The app reads those files. Every game locks at its own kickoff. If the fetch
ever returns something suspicious, **nothing is written** and GitHub emails
Richard. Cost: £0.

---

## Layout

```
data/
  season.json           Season-level info (weeks, playoff dates, staleness threshold)
  2026/
    week-01.json        One file per week. Fixtures + scores.
    ...   week-18.json
  HOW-TO-EDIT.md        Manual score entry guide (for when the feed breaks)
scripts/
  fetch_results.py      The fetcher. Pulls, validates, merges, writes.
  validate_data.py      Guards hand-edits. Runs in CI on every data change.
.github/workflows/
  fetch-results.yml     Scheduled fetcher (Sun/Mon/Tue/Thu/Fri)
  validate-data.yml     Runs validate_data.py on any push touching data/
```

**One file per week is deliberate.** A hand-edit means opening a ~200-line file,
not a 3,000-line one; a fetcher bug has a blast radius of one week; and git
history stays readable.

---

## Key design decisions (and why)

### Per-game locks. No weekly lock.
Each game locks at its own `kickoff`. **There is no `lockMode` flag and no
weekly lock** — earlier designs had these and they were wrong.

The 2026 schedule proves why: the season opens **Wednesday 9 Sep** (NE @ SEA),
Week 1 also has a **Thursday game in Melbourne** (SF @ LAR), plus Sunday and
Monday games. Any "week locks Thursday 9pm" rule would have let people pick the
Wednesday opener *after it finished*. Per-game locking handles that, plus
Thanksgiving, Thanksgiving Eve and Christmas (Friday, 25 Dec 2026), with **no
special cases**.

It also means **pick-ahead is free**: a game that hasn't kicked off is open, so
anyone can fill in the whole season on day one if they like.

### Fail-safe, not fail-broken.
The dangerous failure is silent: ESPN changes shape, the fetch "succeeds", and
we commit garbage. So `fetch_results.py` refuses to write unless every check
passes. Old good data survives. A failed Action emails Richard — **that's the
alarm**.

### Final scores are immutable.
Once a game is `final` in our files, the fetcher will never overwrite it, and
will error out if the feed disagrees. History is protected.

### Kickoffs move; that's expected.
The NFL flexes games, and Weeks 17–18 times aren't set until after Weeks 15/17.
So changing an **unplayed** game's kickoff is allowed and normal — we record the
original in `movedFrom` so the app can show a ⚠️ flag. Changing a **played**
game is rejected.

### No betting data.
ESPN's payload is full of DraftKings odds. This league is bragging rights only.
The parser deliberately ignores all of it.

---

## Data format

`data/2026/week-01.json`:

```json
{
  "week": 1,
  "season": 2026,
  "updated": "2026-07-16T22:20:32Z",
  "games": [
    {
      "id": "401872656",
      "kickoff": "2026-09-10T00:20Z",
      "home": "SEA",
      "away": "NE",
      "homeScore": null,
      "awayScore": null,
      "status": "scheduled",
      "venue": "Lumen Field",
      "neutralSite": false,
      "tbdFlex": false
    }
  ]
}
```

| Field | Notes |
|---|---|
| `id` | ESPN event id. **The pick key. Never regenerate or delete it.** |
| `kickoff` | ISO8601 **UTC**. This IS the lock time. |
| `homeScore`/`awayScore` | `null` until final. Never `0` for an unplayed game. |
| `status` | `scheduled` \| `in` \| `final` |
| `movedFrom` | Present only if kickoff moved. Original time. Drives the ⚠️ flag. |
| `tbdFlex` | ESPN's own "this may be flexed" hint. |

---

## Running it

```bash
# Initial build of the whole season
python3 scripts/fetch_results.py --all

# What the Action runs: current + previous week
python3 scripts/fetch_results.py --auto

# Specific weeks
python3 scripts/fetch_results.py --weeks 9 10

# Check without writing
python3 scripts/fetch_results.py --auto --dry-run

# Validate committed files
python3 scripts/validate_data.py
```

Manual run from GitHub: **Actions → Fetch NFL results → Run workflow**
(optionally give it week numbers, or tick dry run).

---

## When it breaks

Expect roughly **one break per season** — the ESPN endpoint is undocumented and
unofficial, with no support and no stability promise.

1. You get a GitHub email: "Fetch NFL results" failed.
2. Open the run log. The error names the exact check that failed.
3. Meanwhile the league keeps working on the last good data.
4. Enter that week's scores by hand: see **`data/HOW-TO-EDIT.md`**.
5. For a real fix, hand Claude: this repo, the failed log, the affected week.

**Claude has no memory between conversations.** Everything needed to pick this
up cold is in this README, the docstring at the top of `fetch_results.py`, and
`HOW-TO-EDIT.md`. Keep them accurate.

### Second alarm
GitHub disables scheduled workflows on repos idle for 60 days. As a backstop,
the app shows a scorer-only banner if data is more than `staleAfterDays` (8)
old during the season.

---

## The endpoint

```
https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  ?dates=2026&seasontype=2&week=1
```

`seasontype`: 1=preseason, 2=regular, 3=postseason. No key, no auth, free.
Unofficial — use at your own risk, which is exactly why the validation gate exists.

---

## Status

- [x] Per-week schema + `season.json`
- [x] Fetcher with validation gate (17/17 logic tests passing)
- [x] Scheduled Action (Sun/Mon/Tue/Thu/Fri) + manual trigger
- [x] Hand-edit validator + CI guard
- [x] Manual editing guide
- [ ] **Initial season build** — run `--all` to populate weeks 1–18 (see below)
- [ ] App rewired to per-week files + per-game locks (build item 3)
- [ ] Join links + invite-only (build item 2)
- [ ] Own-league stats + weekly winners (build item 4)

### Populating the real schedule
`data/2026/week-01.json` currently holds a **sample generated from the real
ESPN response shape** — the first 12 games are genuine Week 1 2026 fixtures
(including the Wednesday opener and the Melbourne game); the last 4 are
plausible fillers, because the sandbox that built this couldn't reach ESPN
directly.

**Before the season starts, run `python3 scripts/fetch_results.py --all`** (or
trigger the Action manually with no week specified). That overwrites everything
with the real 272-game schedule. Until you do, treat the data as provisional.
