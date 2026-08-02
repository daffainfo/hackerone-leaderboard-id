# Indonesia All-Time HackerOne Leaderboard

Lifetime HackerOne reputation ranking for hackers in Indonesia. Updated daily.

**→ [daffainfo.github.io/hackerone-leaderboard-id](https://daffainfo.github.io/hackerone-leaderboard-id/)**

Data: [`data/leaderboard_ID.csv`](data/leaderboard_ID.csv) — 849 hackers, ranked by lifetime points.

## How it works

HackerOne has no all-time per-country leaderboard, so this builds one. Every entry on
their dated country boards embeds the hacker's *lifetime* reputation and worldwide rank —
so the job is just finding everyone. A daily GitHub Action sweeps every country board from
2020 on (yearly and quarterly), dedupes, and sorts by lifetime points.

No API key needed. These queries are public.

## Notes

- Hackers with no points, and deleted accounts, are excluded.
- Anyone who last placed before 2020 can't be found — those country boards are empty.
- Blank `worldwide_rank` means they're below HackerOne's global ranking cutoff.

## Run it yourself

```bash
python scripts/scrape.py               # -> data/leaderboard_ID.csv
python scripts/scrape.py --country US  # any country code
python -m http.server 8000             # preview the site
```

Takes ~10 minutes. Python 3, no dependencies.

---

Unofficial. Not affiliated with HackerOne. Built from public data.
