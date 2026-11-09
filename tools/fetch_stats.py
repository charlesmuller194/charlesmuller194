"""Fetch the numbers shown on the profile card and the Pac-Man board.

Writes:
    cache/stats.json     repos, stars, followers, commits, lines of code
    cache/calendar.json  the last year of the contribution calendar
    cache/loc.json       per-repo line counts, keyed by head commit, so the
                         next run only re-walks repos whose head moved

Needs GITHUB_TOKEN in the environment. The Actions token is enough for public
data; a personal token with read:user also counts private contributions.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
API = "https://api.github.com/graphql"


def gql(query: str, **variables) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    for attempt in range(4):
        resp = requests.post(
            API,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"bearer {token}"},
            timeout=60,
        )
        if resp.status_code in (502, 503, 504) or (resp.status_code == 403 and "rate" in resp.text.lower()):
            time.sleep(5 * (attempt + 1))
            continue
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(json.dumps(body["errors"], indent=2))
        return body["data"]
    raise RuntimeError(f"GitHub API kept failing: {resp.status_code} {resp.text[:200]}")


USER_Q = """
query($login: String!, $after: String) {
  user(login: $login) {
    id
    createdAt
    followers { totalCount }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW]) { totalCount }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        stargazerCount
        defaultBranchRef { target { ... on Commit { oid } } }
      }
    }
  }
}
"""

CALENDAR_Q = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date weekday contributionCount contributionLevel } }
      }
    }
  }
}
"""

YEAR_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""

HISTORY_Q = """
query($owner: String!, $name: String!, $author: ID!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $after, author: { id: $author }) {
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions }
          }
        }
      }
    }
  }
}
"""


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def repo_lines(full_name: str, author_id: str) -> tuple[int, int, int]:
    owner, name = full_name.split("/", 1)
    added = deleted = commits = 0
    after = None
    while True:
        data = gql(HISTORY_Q, owner=owner, name=name, author=author_id, after=after)
        ref = (data.get("repository") or {}).get("defaultBranchRef")
        if not ref:
            return 0, 0, 0
        hist = ref["target"]["history"]
        for node in hist["nodes"]:
            added += node["additions"]
            deleted += node["deletions"]
            commits += 1
        if not hist["pageInfo"]["hasNextPage"]:
            return added, deleted, commits
        after = hist["pageInfo"]["endCursor"]


def main() -> None:
    profile = json.loads((ROOT / "profile.json").read_text())
    login = profile["login"]
    CACHE.mkdir(exist_ok=True)

    repos, after, user = [], None, None
    while True:
        user = gql(USER_Q, login=login, after=after)["user"]
        page = user["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    # Lines of code: only re-walk repos whose head commit changed.
    old = load_json(CACHE / "loc.json", {})
    loc = {}
    for repo in repos:
        name = repo["nameWithOwner"]
        head = ((repo.get("defaultBranchRef") or {}).get("target") or {}).get("oid")
        if not head:
            continue
        if old.get(name, {}).get("head") == head:
            loc[name] = old[name]
            continue
        add, dele, n = repo_lines(name, user["id"])
        loc[name] = {"head": head, "add": add, "del": dele, "commits": n}
        print(f"walked {name}: +{add} -{dele} in {n} commits")

    # Commits: every year since the account was created.
    created = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    commits = 0
    for year in range(created.year, now.year + 1):
        start = max(created, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
        end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        cc = gql(YEAR_Q, login=login, **{"from": start.isoformat(), "to": end.isoformat()})
        commits += cc["user"]["contributionsCollection"]["totalCommitContributions"]

    stats = {
        "repos": user["repositories"]["totalCount"],
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": user["followers"]["totalCount"],
        "commits": commits,
        "loc_add": sum(v["add"] for v in loc.values()),
        "loc_del": sum(v["del"] for v in loc.values()),
    }
    calendar = gql(CALENDAR_Q, login=login)["user"]["contributionsCollection"]["contributionCalendar"]

    (CACHE / "loc.json").write_text(json.dumps(loc, indent=1, sort_keys=True) + "\n")
    (CACHE / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    (CACHE / "calendar.json").write_text(json.dumps(calendar) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
