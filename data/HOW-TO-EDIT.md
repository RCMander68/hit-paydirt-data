# How to enter results by hand

**You only need this if the automatic fetcher has broken.** Normally results
arrive on their own and you do nothing.

You'll know it's broken because **GitHub emails you** saying the "Fetch NFL
results" job failed, or the app shows a "results haven't updated" banner.

Do this on a **laptop**, not your phone. It's fiddly on a small screen.

---

## Entering a score — the 60-second version

1. On GitHub, open the file for the week you want:
   `data/2026/week-09.json` (for Week 9, etc.)
2. Click the **pencil icon** (top right) to edit.
3. Find the game. Use **Ctrl+F** and search the team code, e.g. `"KC"`.
4. Change **three** things on that game — and nothing else:
   - `"homeScore": null` → `"homeScore": 27`
   - `"awayScore": null` → `"awayScore": 20`
   - `"status": "scheduled"` → `"status": "final"`
5. Scroll down, click **Commit changes**.

Done. The app picks it up on the next refresh.

---

## What a game looks like

```json
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
```

After Seattle beat New England 27-20, the same game reads:

```json
{
  "id": "401872656",
  "kickoff": "2026-09-10T00:20Z",
  "home": "SEA",
  "away": "NE",
  "homeScore": 27,
  "awayScore": 20,
  "status": "final",
  "venue": "Lumen Field",
  "neutralSite": false,
  "tbdFlex": false
}
```

**`home` is the first score, `away` is the second.** Get these the right way
round or the league table will be wrong.

---

## The rules (breaking these breaks things)

| Do | Don't |
|---|---|
| Change `homeScore`, `awayScore`, `status` | Change `id` — it's the key linking picks to games. **Never touch it.** |
| Use plain numbers: `27` | Use quotes: `"27"` — that's a string, not a number |
| Set `status` to exactly `"final"` | Invent statuses like `"finished"` or `"FT"` |
| Leave unplayed games as `null` | Put `0` in an unplayed game — that's a real 0-0 draw |
| Keep every comma and bracket exactly as-is | Add a trailing comma after the last item |

Valid `status` values, and nothing else: `"scheduled"`, `"in"`, `"final"`.

---

## Kickoff times and flexed games

`kickoff` is in **UTC** (the `Z` on the end means UTC), not UK time.
In summer (BST) UK is UTC+1; in winter (GMT) UK is UTC.

`"kickoff": "2026-09-10T00:20Z"` = 1:20am UK on 10 September.

**This field is the lock.** A game is open for picks until its kickoff passes,
then it locks automatically. There's no separate lock setting to manage.

If the NFL moves a game, change `kickoff` to the new UTC time. If you want the
app to show the ⚠️ moved flag, also add `"movedFrom"` with the *original* time:

```json
"kickoff": "2026-12-20T01:20Z",
"movedFrom": "2026-12-19T18:00Z",
```

---

## Did I break it?

After committing, check the **Actions** tab. A validation job runs on every
change to `data/`. Green tick = fine. Red cross = click it, read the error,
it names exactly what's wrong.

You can also check before committing: paste the file into a JSON validator, or
just look for GitHub's syntax highlighting going haywire.

**Nothing you do here is unrecoverable.** Every change is a git commit. If it
goes wrong, open the file's History and revert to the previous version.

---

## Adding a whole missing week

If the fetcher never managed to write a week at all, don't hand-type 16 games.
Go to the **Actions** tab → **Fetch NFL results** → **Run workflow**, and put
the week number in the box (e.g. `9`). That re-runs just that week.

If that still fails, the feed itself is broken — that's a job for Claude.
Send it: the failed run's log, this repo, and which week is affected.
