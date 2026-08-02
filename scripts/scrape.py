#!/usr/bin/env python3
"""Build an all-time (lifetime) HackerOne leaderboard for one country, as CSV.

HackerOne exposes no such board:
  - ALL_TIME_REPUTATION is capped at the global top 100 and silently ignores the
    `filter` (country) argument - passing a country returns the global list.
  - HIGHEST_REPUTATION_BY_COUNTRY returns HTTP 500 without a `year`.
  - users(where:) has no country field.

So it is reconstructed. Every leaderboard entry embeds `user.rank` and
`user.reputation`, and those are all-time worldwide values rather than per-year
ones - verified against the global ALL_TIME_REPUTATION board, where
entry.rank == user.rank and entry.reputation == user.reputation. That means the
only hard part is *finding* every hacker in the country, not ranking them.

Discovery sweeps every dated country board: each year from --start to the
current one, annually and per quarter, across engagement types and user types.
The quarterly boards carry the sweep - recent annual boards truncate at 100
entries while a single quarter can return ~200.

Hackers with no reputation are dropped. That set is 1) accounts that no longer
exist, whose leaderboard entries outlive them, and 2) live accounts that have
not earned a point. Neither belongs on a ranking.

Known limit: a hacker who earned reputation only before 2020 and has not placed
on a country board since cannot be discovered - the by-country leaderboards
return nothing for those years.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://hackerone.com/graphql"

# No authentication: the leaderboard queries are public. Only the `me { ... }`
# field in HackerOne's own version of this query requires a session.
QUERY = """
query CountryBoard(
  $key: LeaderboardKeyEnum!, $year: Int, $quarter: Int, $first: Int,
  $after: String, $filter: String, $user_type: String, $engagement_type: String
) {
  leaderboard_entries(
    key: $key, year: $year, quarter: $quarter, first: $first, after: $after,
    filter: $filter, user_type: $user_type, engagement_type: $engagement_type
  ) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        ... on HighRepByEngagementTypeAndCountryLeaderboardEntry { user { ...U } }
        ... on HighestReputationByCountryLeaderboardEntry { user { ...U } }
      }
    }
  }
}
fragment U on User {
  id username country reputation rank signal impact
  resolved_report_count thanks_items_total_count
}
"""

ENGAGEMENTS = [
    ("bbp", "HIGHEST_REPUTATION_BY_ENGAGEMENT_TYPE_AND_COUNTRY"),
    ("vdp", "HIGHEST_REPUTATION_BY_ENGAGEMENT_TYPE_AND_COUNTRY"),
    (None, "HIGHEST_REPUTATION_BY_COUNTRY"),
]
USER_TYPES = ("individual", "business")

COLUMNS = [
    "country_rank",
    "username",
    "reputation",
    "worldwide_rank",
    "resolved_reports",
    "thanks_items",
    "signal",
    "impact",
    "user_type",
    "profile",
    "user_id",
]


class GraphQLError(RuntimeError):
    """The server answered but rejected the query. Retrying will not help."""


def post(query, variables, retries=5):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "content-type": "application/json",
            "accept": "*/*",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
            "x-product-area": "leaderboard",
            "x-product-feature": "details",
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            if "errors" in payload:
                raise GraphQLError(str(payload["errors"])[:200])
            return payload["data"]
        except GraphQLError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport hiccup, worth a retry
            if attempt == retries - 1:
                raise
            print(f"    ! {exc} - retry {attempt + 1}", file=sys.stderr)
            time.sleep(2**attempt)


def sweep(base, delay):
    """Page through one leaderboard slice, yielding user dicts."""
    cursor = None
    while True:
        conn = post(QUERY, {**base, "first": 100, "after": cursor})["leaderboard_entries"]
        for edge in conn["edges"]:
            user = (edge.get("node") or {}).get("user")
            if user:
                yield user
        if not conn["pageInfo"]["hasNextPage"]:
            return
        cursor = conn["pageInfo"]["endCursor"]
        time.sleep(delay)


def discover(country, start, end, delay):
    """Every hacker in `country` findable on a dated leaderboard."""
    hackers = {}
    periods = [(y, q) for y in range(start, end + 1) for q in (None, 1, 2, 3, 4)]

    for year, quarter in periods:
        label = f"{year}" + (f" Q{quarter}" if quarter else " annual")
        before = len(hackers)
        for engagement, key in ENGAGEMENTS:
            for user_type in USER_TYPES:
                base = {
                    "key": key,
                    "year": year,
                    "quarter": quarter,
                    "filter": country,
                    "user_type": user_type,
                    "engagement_type": engagement,
                }
                try:
                    for user in sweep(base, delay):
                        # Guard in case the API ever ignores the country filter.
                        if user.get("country") and user["country"] != country:
                            continue
                        hackers[user["username"]] = {**user, "user_type": user_type}
                except Exception as exc:  # noqa: BLE001 - one slice must not sink the run
                    print(f"  ! {label} {engagement}/{user_type}: {exc}", file=sys.stderr)
                time.sleep(delay)
        print(f"{label}: +{len(hackers) - before} new (total {len(hackers)})", file=sys.stderr)
    return hackers


def rank(hackers):
    """Drop the unrankable, order by lifetime reputation, number 1..N."""
    scored = [u for u in hackers.values() if (u.get("reputation") or 0) > 0]
    dropped = len(hackers) - len(scored)

    # Tie-break on the immutable user id, never on worldwide rank. Worldwide rank
    # drifts daily as hackers elsewhere earn points, which would reshuffle every
    # tied cluster and make the daily diff claim ranks moved when nothing did.
    # Ordering within a tie is arbitrary anyway - only stability matters here.
    scored.sort(key=lambda u: (-u["reputation"], u.get("id") or "", u["username"]))

    rows = [
        {
            "country_rank": i,
            "username": u["username"],
            "reputation": u["reputation"],
            "worldwide_rank": u.get("rank"),
            "resolved_reports": u.get("resolved_report_count"),
            "thanks_items": u.get("thanks_items_total_count"),
            "signal": None if u.get("signal") is None else round(u["signal"], 2),
            "impact": None if u.get("impact") is None else round(u["impact"], 2),
            "user_type": u["user_type"],
            "profile": f"https://hackerone.com/{u['username']}",
            "user_id": u.get("id"),
        }
        for i, u in enumerate(scored, 1)
    ]
    return rows, dropped


def existing_row_count(path):
    if not os.path.exists(path):
        return 0
    with open(path, newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="ID", help="ISO 3166-1 alpha-2 code")
    ap.add_argument("--start", type=int, default=2020, help="country boards are empty before 2020")
    ap.add_argument("--end", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--delay", type=float, default=0.2, help="seconds between requests")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument(
        "--max-shrink",
        type=float,
        default=0.15,
        help="abort without writing if the board shrinks by more than this fraction, "
        "so a partly-failed scrape cannot overwrite good data",
    )
    args = ap.parse_args()

    hackers = discover(args.country, args.start, args.end, args.delay)
    rows, dropped = rank(hackers)
    if not rows:
        sys.exit("no hackers found - refusing to write an empty file")

    print(f"\n{len(rows)} ranked, {dropped} dropped (no reputation)", file=sys.stderr)

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"leaderboard_{args.country}.csv")

    previous = existing_row_count(path)
    if previous:
        floor = previous * (1 - args.max_shrink)
        if len(rows) < floor:
            sys.exit(
                f"refusing to write: {len(rows)} rows vs {previous} previously "
                f"(floor {floor:.0f}). Likely a partial scrape - rerun."
            )

    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path} ({previous} -> {len(rows)} rows)", file=sys.stderr)

    # The CSV deliberately carries no timestamp column - it would dirty the diff
    # every day even when no rank moved. The site reads the date from here.
    meta_path = os.path.join(args.out_dir, f"meta_{args.country}.json")
    with open(meta_path, "w") as fh:
        json.dump(
            {
                "country": args.country,
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "ranked": len(rows),
                "discovered": len(hackers),
                "dropped_no_reputation": dropped,
                "years_swept": [args.start, args.end],
            },
            fh,
            indent=2,
        )
        fh.write("\n")

    for r in rows[:10]:
        print(
            f"{r['country_rank']:>4}  {r['username']:<24} {r['reputation']:>8} pts  "
            f"WW #{r['worldwide_rank']}"
        )


if __name__ == "__main__":
    main()
