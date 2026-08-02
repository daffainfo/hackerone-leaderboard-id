# HackerOne country leaderboard

An all-time (lifetime) HackerOne leaderboard for a single country, refreshed daily
by GitHub Actions. Defaults to Indonesia.

**[`data/leaderboard_ID.csv`](data/leaderboard_ID.csv)** — one row per hacker, ranked by lifetime reputation.

| column | meaning |
| --- | --- |
| `country_rank` | rank within the country, by lifetime reputation |
| `username` | HackerOne username |
| `reputation` | **lifetime** total points (not per-year) |
| `worldwide_rank` | **lifetime** global rank; empty for hackers below HackerOne's global ranking cutoff |
| `resolved_reports` | resolved report count |
| `thanks_items` | thanks items received |
| `signal` / `impact` | current signal and impact, 2dp |
| `user_type` | `individual` or `business` |
| `profile` | profile URL |
| `user_id` | stable global ID — survives username changes |

The file is overwritten in place, so **the git history of that one file is the time
series**: `git log -p data/leaderboard_ID.csv` shows how ranks moved.

## Why this repo exists

HackerOne has no all-time-per-country leaderboard, and no endpoint returns one:

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
them. `scripts/scrape.py` sweeps every dated country board — each year from 2020 to now,
annually and per quarter, across engagement types (`bbp`, `vdp`, all) and user types
(individual, business) — then dedupes and sorts by lifetime reputation.

**The quarterly boards carry the sweep.** Recent annual boards truncate at 100 entries
while a single quarter can return ~200, so the quarters surface hundreds of hackers the
annual boards hide. For Indonesia they took the result from ~400 to ~900.

No authentication is needed. These queries are public; only the `me { ... }` field in
HackerOne's own version of the query requires a session, and it is not used here.

## Known limits

- **Discovery floor at 2020.** A hacker who earned reputation only in 2014–2019 and has
  not placed on a country board since is invisible to this method — the by-country
  boards return nothing for those years. Their lifetime points still count on
  HackerOne's side; they just cannot be enumerated by country.
- **Hackers with no reputation are dropped.** That set is deleted accounts whose
  leaderboard entries outlive them, plus live accounts that never earned a point.
- Some ranked hackers have an empty `worldwide_rank` — they have lifetime points but sit
  below HackerOne's global ranking cutoff.
- Ties in reputation are broken by worldwide rank, matching HackerOne's own ordering.

## Running it

```bash
python scripts/scrape.py                      # Indonesia -> data/leaderboard_ID.csv
python scripts/scrape.py --country US         # any ISO 3166-1 alpha-2 code
python scripts/scrape.py --delay 0.5          # go easier on the endpoint
```

Takes roughly 10 minutes — a few hundred paginated requests. No dependencies beyond the
Python 3 standard library.

If a scrape partly fails, the run **refuses to overwrite** a good file when the board
shrinks by more than 15% (`--max-shrink`), so a bad day cannot destroy the history.

### Optional: per-year breakdown

`scripts/yearly.py` writes the per-year boards instead — rank, reputation, signal and
impact *earned in each individual year*, 2020 onward. Not run by CI.

```bash
python scripts/yearly.py --engagement bbp     # -> data/yearly_ID_bbp_individual.csv
```

## Automation

`.github/workflows/update-leaderboard.yml` runs daily at 01:00 UTC (08:00 WIB) and
commits only when the data actually changes. It also accepts a manual run with a
different country via **Actions → Update leaderboard → Run workflow**.

The workflow needs `contents: write`, which is declared in the file. If pushes are
rejected, enable **Settings → Actions → General → Workflow permissions → Read and write**.
