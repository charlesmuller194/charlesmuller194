"""Fetch the numbers shown on the profile card and the Pac-Man board.

Writes:
    cache/stats.json     repos, stars, followers, commits, lines of code
    cache/calendar.json  the last year of the contribution calendar
    cache/loc.json       per-repo line counts, keyed by head commit, so the
                         next run only re-walks repos whose head moved

Tokens, read from the environment:
    STATS_TOKEN   optional personal access token (classic, scopes: repo, read:user).
                  With it the numbers include private repositories and private
                  commits, because the API answers as you, the owner.
    GITHUB_TOKEN  the Actions token, used when STATS_TOKEN is missing or has
                  expired. It only sees public data.

This repository is public, and so are its Actions logs and cache/ files, so
private repository names are never printed or stored: loc.json is keyed by a
hash of the repository name.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
API = "https://api.github.com/graphql"

_token: str | None = None


class Unauthorized(Exception):
    pass


def _post(token: str, query: str, variables: dict) -> dict:
    resp = None
    for attempt in range(4):
        resp = requests.post(
            API,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"bearer {token}"},
            timeout=60,
        )
        if resp.status_code == 401:
            raise Unauthorized
        if resp.status_code in (502, 503, 504) or (resp.status_code == 403 and "rate" in resp.text.lower()):
            time.sleep(5 * (attempt + 1))
            continue
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(json.dumps(body["errors"], indent=2))
        return body["data"]
    raise RuntimeError(f"GitHub API kept failing: {resp.status_code}")


def gql(query: str, **variables) -> dict:
    assert _token, "pick_token() must run first"
    return _post(_token, query, variables)


def pick_token(login: str) -> bool:
    """Choose the token to use. Returns True when the API answers as the owner."""
    global _token
    personal = os.environ.get("STATS_TOKEN", "").strip()
    actions = os.environ.get("GITHUB_TOKEN", "").strip()
    if personal:
        try:
            viewer = _post(personal, "query { viewer { login } }", {})["viewer"]["login"]
            _token = personal
            if viewer.lower() == login.lower():
                print("using STATS_TOKEN: private repositories and commits are counted")
                return True
            print(f"::warning::STATS_TOKEN belongs to another account; private data of {login} is not visible")
            return False
        except Unauthorized:
            print("::warning::STATS_TOKEN was rejected (expired or revoked?). "
                  "Falling back to the Actions token: only public data is counted until it is replaced.")
    if not actions:
        sys.exit("neither STATS_TOKEN nor GITHUB_TOKEN is set")
    _token = actions
    if not personal:
        print("no STATS_TOKEN secret: only public repositories and commits are counted")
    return False


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
      nodes { stargazerCount isPrivate }
    }
  }
}
"""

# Every repository the user can push to: their own, ones they collaborate on,
# and their organisations'. Lines of code are counted across all of them, only
# for commits the user authored.
CODE_REPOS_Q = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        isPrivate
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
      restrictedContributionsCount
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


def paged(query: str, login: str) -> tuple[dict, list[dict]]:
    nodes, after, user = [], None, None
    while True:
        user = gql(query, login=login, after=after)["user"]
        page = user["repositories"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return user, nodes
        after = page["pageInfo"]["endCursor"]


def repo_key(full_name: str) -> str:
    return hashlib.sha256(full_name.lower().encode()).hexdigest()[:16]


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
    as_owner = pick_token(login)

    user, owned = paged(USER_Q, login)
    _, code_repos = paged(CODE_REPOS_Q, login)
    print(f"owned repositories: {len(owned)} ({sum(r['isPrivate'] for r in owned)} private)")

    # Lines of code: only re-walk repos whose head commit changed.
    old = load_json(CACHE / "loc.json", {})
    loc, walked, failed = {}, 0, 0
    for repo in code_repos:
        name = repo["nameWithOwner"]
        key = repo_key(name)
        head = ((repo.get("defaultBranchRef") or {}).get("target") or {}).get("oid")
        if not head:
            continue
        if old.get(key, {}).get("head") == head:
            loc[key] = old[key]
            continue
        try:
            add, dele, n = repo_lines(name, user["id"])
        except Exception:  # noqa: BLE001 - one unreadable repo must not stop the card
            failed += 1
            if key in old:
                loc[key] = old[key]
            continue
        loc[key] = {"head": head, "add": add, "del": dele, "commits": n}
        walked += 1
    # Without the personal token private repos are invisible; keep their last
    # known counts rather than letting the total drop until the token is back.
    if not as_owner:
        seen = {repo_key(r["nameWithOwner"]) for r in code_repos}
        for key, value in old.items():
            if key not in seen and value.get("private"):
                loc[key] = value
    for repo in code_repos:
        key = repo_key(repo["nameWithOwner"])
        if key in loc:
            loc[key]["private"] = repo["isPrivate"]
    print(f"lines of code: {len(loc)} repositories, {walked} re-walked")
    if failed:
        print(f"::warning::{failed} repositories could not be read and kept their last known line counts")

    # Commits: every year since the account was created.
    created = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    commits = 0
    for year in range(created.year, now.year + 1):
        start = max(created, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
        end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        cc = gql(YEAR_Q, login=login, **{"from": start.isoformat(), "to": end.isoformat()})
        commits += cc["user"]["contributionsCollection"]["totalCommitContributions"]

    collection = gql(CALENDAR_Q, login=login)["user"]["contributionsCollection"]
    calendar = collection["contributionCalendar"]
    print(f"contributions in the last year: {calendar['totalContributions']} "
          f"(anonymized private ones included: {collection['restrictedContributionsCount']})")

    stats = {
        "repos": user["repositories"]["totalCount"],
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in owned),
        "followers": user["followers"]["totalCount"],
        "commits": commits,
        "loc_add": sum(v["add"] for v in loc.values()),
        "loc_del": sum(v["del"] for v in loc.values()),
    }
    # Remember the private-inclusive figures from the last run that had the
    # personal token, so the card does not shrink while that token is missing.
    if as_owner:
        stats["last_owner_run"] = {k: stats[k] for k in ("repos", "commits")}
    else:
        floor = load_json(CACHE / "stats.json", {}).get("last_owner_run")
        if floor:
            for k, v in floor.items():
                stats[k] = max(stats[k], v)
            stats["last_owner_run"] = floor

    (CACHE / "loc.json").write_text(json.dumps(loc, indent=1, sort_keys=True) + "\n")
    (CACHE / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    (CACHE / "calendar.json").write_text(json.dumps(calendar) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
