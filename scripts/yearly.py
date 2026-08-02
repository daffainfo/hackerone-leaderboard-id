#!/usr/bin/env python3
"""Scrape the HackerOne Indonesia country leaderboard for a range of years.

The public GraphQL endpoint needs no auth for these queries, so the cookies /
CSRF token from a browser request can be dropped entirely.

Per year it collects, for every Indonesian hacker on the leaderboard:
  - rank within Indonesia for that year (+ previous_rank)
  - reputation / signal / impact earned in that year
  - the hacker's all-time total reputation and all-time worldwide rank
  - worldwide rank for that year, when the hacker made the global top 100
    (HackerOne only exposes the top 100 of the worldwide board)
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://hackerone.com/graphql"

COUNTRY_QUERY = """
query CountryLeaderboard(
  $year: Int!, $first: Int, $after: String, $filter: String,
  $user_type: String, $engagement_type: String, $key: LeaderboardKeyEnum!
) {
  leaderboard_entries(
    key: $key, year: $year, first: $first, after: $after, filter: $filter,
    user_type: $user_type, engagement_type: $engagement_type
  ) {
    total_count
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        ... on HighRepByEngagementTypeAndCountryLeaderboardEntry {
          rank previous_rank reputation signal impact
          user { id username country reputation rank resolved_report_count }
        }
        ... on HighestReputationByCountryLeaderboardEntry {
          rank previous_rank reputation signal impact
          user { id username country reputation rank resolved_report_count }
        }
      }
    }
  }
}
"""

WORLD_QUERY = """
query WorldLeaderboard(
  $year: Int!, $first: Int, $after: String,
  $user_type: String, $engagement_type: String, $key: LeaderboardKeyEnum!
) {
  leaderboard_entries(
    key: $key, year: $year, first: $first, after: $after,
    user_type: $user_type, engagement_type: $engagement_type
  ) {
    total_count
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        ... on HighestReputationByEngagementTypeLeaderboardEntry {
          rank reputation user { username country }
        }
        ... on HighestReputationLeaderboardEntry {
          rank reputation user { username country }
        }
      }
    }
  }
}
"""


def post(query, variables, retries=4):
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
                raise RuntimeError(payload["errors"])
            return payload["data"]
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  ! {exc} - retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


def paginate(query, variables, page_size, cap=None):
    """Walk the relay connection until exhausted (or `cap` nodes collected)."""
    nodes, cursor = [], None
    while True:
        data = post(query, {**variables, "first": page_size, "after": cursor})
        conn = data["leaderboard_entries"]
        nodes.extend(e["node"] for e in conn["edges"] if e["node"])
        info = conn["pageInfo"]
        if not info["hasNextPage"] or (cap and len(nodes) >= cap):
            return nodes
        cursor = info["endCursor"]
        time.sleep(0.3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="ID")
    ap.add_argument("--start", type=int, default=2014)
    ap.add_argument("--end", type=int, default=2026)
    ap.add_argument(
        "--engagement",
        default="bbp",
        choices=["bbp", "vdp", "all"],
        help="bbp = bug bounty programs (default, matches the leaderboard UI tab); "
        "all = every engagement type combined",
    )
    ap.add_argument("--user-type", default="individual", choices=["individual", "business"])
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()

    if args.engagement == "all":
        country_key, world_key, engagement = (
            "HIGHEST_REPUTATION_BY_COUNTRY",
            "HIGHEST_REPUTATION",
            None,
        )
    else:
        country_key, world_key, engagement = (
            "HIGHEST_REPUTATION_BY_ENGAGEMENT_TYPE_AND_COUNTRY",
            "HIGHEST_REPUTATION_BY_ENGAGEMENT_TYPE",
            args.engagement,
        )

    rows = []
    for year in range(args.start, args.end + 1):
        base = {
            "year": year,
            "user_type": args.user_type,
            "engagement_type": engagement,
        }

        # Worldwide board is capped at the top 100 by the API.
        world_rank = {}
        try:
            for node in paginate(WORLD_QUERY, {**base, "key": world_key}, args.page_size, cap=100):
                world_rank[node["user"]["username"]] = node["rank"]
        except Exception as exc:  # noqa: BLE001 - worldwide slice is a bonus, not the point
            print(f"  ! {year} worldwide fetch failed: {exc}", file=sys.stderr)

        entries = paginate(
            COUNTRY_QUERY, {**base, "key": country_key, "filter": args.country}, args.page_size
        )
        print(f"{year}: {len(entries)} {args.country} hackers", file=sys.stderr)

        for node in entries:
            user = node["user"] or {}
            rows.append(
                {
                    "year": year,
                    "username": user.get("username"),
                    "country_rank": node["rank"],
                    "country_rank_prev_year": node.get("previous_rank"),
                    "reputation_this_year": node["reputation"],
                    "signal_this_year": node.get("signal"),
                    "impact_this_year": node.get("impact"),
                    "worldwide_rank_this_year": world_rank.get(user.get("username")),
                    "worldwide_rank_alltime": user.get("rank"),
                    "reputation_alltime": user.get("reputation"),
                    "resolved_reports_alltime": user.get("resolved_report_count"),
                    "user_id": user.get("id"),
                }
            )
        time.sleep(0.4)

    import os

    os.makedirs(args.out_dir, exist_ok=True)
    csv_path = os.path.join(
        args.out_dir, f"yearly_{args.country}_{args.engagement}_{args.user_type}.csv"
    )
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{len(rows)} rows -> {csv_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
