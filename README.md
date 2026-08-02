# Indonesia All-Time HackerOne Leaderboard

A static site showing the **lifetime** HackerOne reputation ranking for hackers in
Indonesia, refreshed daily by GitHub Actions and served from GitHub Pages.

- **Site** — `index.html`, a single self-contained page (no dependencies, no build step)
- **Data** — [`data/leaderboard_ID.csv`](data/leaderboard_ID.csv), one row per hacker
- **Scraper** — [`scripts/scrape.py`](scripts/scrape.py), Python 3 standard library only

The CSV is overwritten in place, so **the git history of that one file is the time
series**: `git log -p data/leaderboard_ID.csv` shows how ranks moved over time.

## Why this exists

HackerOne publishes no all-time per-country leaderboard, and no endpoint returns one:

- `ALL_TIME_REPUTATION` is capped at the **global top 100** and **silently ignores** the
  `filter` (country) argument — passing `filter:"ID"` returns the same global list.
- `HIGHEST_REPUTATION_BY_COUNTRY` returns **HTTP 500** without a `year`. Country boards
  are inherently dated.
- `users(where:)` has no country field.

So it is reconstructed, resting on one observation: every leaderboard entry embeds
`user.rank` and `user.reputation`, and those are **all-time worldwide values**, not
per-year ones. Verified against the global `ALL_TIME_REPUTATION` board, where
`entry.rank == user.rank` and `entry.reputation == user.reputation` exactly.

That reduces the problem to *finding* every hacker in the country rather than ranking
them. The scraper sweeps every dated country board — each year from 2020 to now,
annually and per quarter, across engagement types (`bbp`, `vdp`, all) and user types
(individual, business) — then dedupes and sorts by lifetime reputation.

**The quarterly boards carry the sweep.** Recent annual boards truncate at 100 entries
while a single quarter can return ~200, so the quarters surface hundreds of hackers the
annual boards hide. For Indonesia they took the result from ~400 to ~900.

No authentication is needed. These queries are public; only the `me { ... }` field in
HackerOne's own version of the query requires a session, and it is not used here.

## Data

| column | meaning |
| --- | --- |
| `country_rank` | rank within Indonesia, by lifetime reputation |
| `username` | HackerOne username |
| `reputation` | **lifetime** total points (not per-year) |
| `worldwide_rank` | **lifetime** global rank; empty below HackerOne's ranking cutoff |
| `resolved_reports` | resolved report count |
| `thanks_items` | thanks items received |
| `signal` / `impact` | current signal and impact, 2dp |
| `user_type` | `individual` or `business` |
| `profile` | profile URL |
| `user_id` | stable global ID — survives username changes |

`data/meta_ID.json` carries the generation timestamp and row counts. The timestamp lives
there rather than in the CSV so the daily diff stays meaningful — a `fetched_at` column
would dirty every row even when no rank moved.

### Known limits

- **Discovery floor at 2020.** A hacker who earned reputation only in 2014–2019 and has
  not placed on a country board since is invisible to this method — the by-country
  boards return nothing for those years. Their lifetime points still count on
  HackerOne's side; they just cannot be enumerated by country.
- **Hackers with no reputation are excluded.** That set is deleted accounts whose
  leaderboard entries outlive them, plus live accounts that never earned a point.
- Some ranked hackers have an empty `worldwide_rank` — they have lifetime points but sit
  below HackerOne's global ranking cutoff.
- Ties in reputation are broken by the immutable user id, not by worldwide rank.
  Worldwide rank drifts daily as hackers elsewhere earn points, so tie-breaking on it
  would reshuffle every tied cluster and make the daily diff claim Indonesian ranks
  moved when nothing did. `country_rank` now changes only when reputation does.

## Enabling GitHub Pages

**Settings → Pages → Source: Deploy from a branch**, branch `master`, folder `/ (root)`.

No Pages workflow is needed — the daily data commit republishes the site automatically.
`.nojekyll` is present so files are served verbatim.

## Running locally

```bash
python scripts/scrape.py                 # -> data/leaderboard_ID.csv + data/meta_ID.json
python scripts/scrape.py --country US    # any ISO 3166-1 alpha-2 code
python scripts/scrape.py --delay 0.5     # go easier on the endpoint

python -m http.server 8000               # then open http://localhost:8000
```

A scrape takes roughly 10 minutes — a few hundred paginated requests.

If one partly fails, the run **refuses to overwrite** a good file when the board shrinks
by more than 15% (`--max-shrink`) and exits non-zero, so a bad day cannot destroy the
history or publish a gutted page.

## Automation

`.github/workflows/update-leaderboard.yml` runs daily at 01:00 UTC (08:00 WIB) and
commits only when the data actually changes. It can also be run manually against a
different country via **Actions → Update leaderboard → Run workflow**.

The workflow needs `contents: write`, declared in the file. If pushes are rejected,
enable **Settings → Actions → General → Workflow permissions → Read and write**.

---

Unofficial. Not affiliated with HackerOne. Built from public data.
