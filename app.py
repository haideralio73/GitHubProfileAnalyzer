"""
GitHub Profile Analyzer - CLI tool that fetches profile + repo data from the
GitHub REST API, aggregates stats, prints rich tables, and saves charts as PNG.

Usage:
    python app.py --username torvalds
    python app.py --username torvalds --token ghp_xxx   (higher rate limit)
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import requests
from rich.console import Console
from rich.table import Table

GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_json(session, url, params=None):
    """GET a JSON response from the GitHub API.  Raises on 404, 403, or
    network errors so the caller always gets valid data or an exception."""
    resp = session.get(url, params=params, timeout=15)
    if resp.status_code == 403:
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(0, reset - datetime.now(timezone.utc).timestamp())
        raise RuntimeError(
            f"Rate limited.  Resets in {wait:.0f}s.  "
            "Pass --token or set GITHUB_TOKEN for a higher limit."
        )
    if resp.status_code == 404:
        raise ValueError(f"User '{url.rstrip('/').split('/')[-1]}' not found.")
    if resp.status_code != 200:
        raise RuntimeError(
            f"API error {resp.status_code}: {resp.json().get('message', '')}"
        )
    return resp.json()


def fetch_all_repos(session, username):
    """Iterate over paginated /users/{username}/repos until all owner repos
    are collected.  Returns the full list of repository dicts."""
    repos = []
    page = 1
    while True:
        data = fetch_json(
            session,
            f"{GITHUB_API}/users/{username}/repos",
            {"per_page": 100, "page": page, "type": "owner", "sort": "pushed"},
        )
        if not data:
            break
        repos.extend(data)
        page += 1
    return repos


def fetch_orgs(session, username):
    """Fetch organizations the user belongs to."""
    return fetch_json(session, f"{GITHUB_API}/users/{username}/orgs")


def fetch_recent_events(session, username, count=5):
    """Fetch recent public events for the user."""
    data = fetch_json(
        session,
        f"{GITHUB_API}/users/{username}/events",
        {"per_page": count},
    )
    return data[:count]


def aggregate_languages(session, repos):
    """For each repo that has a languages_url, fetch the byte-count breakdown
    and accumulate into a {language: total_bytes} dict."""
    lang_bytes = defaultdict(int)
    for r in repos:
        url = r.get("languages_url")
        if not url:
            continue
        try:
            data = fetch_json(session, url)
        except Exception:
            continue
        for lang, count in data.items():
            lang_bytes[lang] += count
    return lang_bytes


# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------

def build_profile_table(username, profile, stats, top_repos, top_forked,
                        orgs, events):
    """Return a rich Table object summarising the user's GitHub profile."""
    t = Table(title=f"GitHub Profile - {username}", title_justify="left")
    t.add_column("Metric", style="cyan", no_wrap=True)
    t.add_column("Value", style="white")

    t.add_row("Name", profile.get("name") or username)
    t.add_row("Bio", (profile.get("bio") or "No bio")[:80])
    t.add_row("Followers", str(profile["followers"]))
    t.add_row("Following", str(profile["following"]))
    t.add_row("Public repos", str(profile["public_repos"]))
    t.add_row("Member since", profile["created_at"][:10])
    t.add_row("Account age", stats["account_age"])
    t.add_row("")

    t.add_row("[bold]Repository stats[/]", "")
    t.add_row("  Repos fetched", str(stats["repo_count"]))
    t.add_row("  Total stars", str(stats["total_stars"]))
    t.add_row("  Total forks", str(stats["total_forks"]))
    t.add_row("  Code size (MB)", str(stats["total_size_mb"]))
    t.add_row("  Stars per repo", stats["stars_per_repo"])
    t.add_row("  Unique languages", str(stats["unique_languages"]))
    t.add_row("  Inactive repos", str(stats["inactive_count"]))

    if orgs:
        t.add_section()
        t.add_row("[bold]Organizations ({})[/]".format(len(orgs)), "")
        for o in orgs:
            t.add_row("  " + o["login"], o.get("description", "") or "")

    if events:
        t.add_section()
        t.add_row("[bold]Recent activity[/]", "")
        for e in events:
            kind = e["type"].replace("Event", "")
            repo_name = e["repo"]["name"]
            created = e.get("created_at", "")[:10]
            t.add_row(f"  {kind}", f"{repo_name} ({created})")

    t.add_section()
    t.add_row("[bold]Top 5 repos by stars[/]", "")
    for i, r in enumerate(top_repos, 1):
        name = r["name"]
        stars = r["stargazers_count"]
        forks = r["forks_count"]
        lang = r["language"] or "-"
        pushed = r["pushed_at"][:10]
        t.add_row(
            f"  {i}. {name}",
            f"* {stars} stars | {forks} forks | {lang} | pushed: {pushed}",
        )

    if top_forked:
        t.add_section()
        t.add_row("[bold]Top 5 repos by forks[/]", "")
        for i, r in enumerate(top_forked, 1):
            name = r["name"]
            stars = r["stargazers_count"]
            forks = r["forks_count"]
            pushed = r["pushed_at"][:10]
            t.add_row(
                f"  {i}. {name}",
                f"* {forks} forks | {stars} stars | pushed: {pushed}",
            )

    return t


def build_lang_table(lang_dist):
    """Return a rich Table with language -> bytes and percentage."""
    t = Table(title="Language distribution (bytes)", title_justify="left")
    t.add_column("Language", style="green")
    t.add_column("Bytes", justify="right")
    t.add_column("%", justify="right")

    total = sum(b for _, b in lang_dist)
    for lang, bytes_ in lang_dist:
        pct = bytes_ / total * 100
        t.add_row(lang, f"{bytes_:,}", f"{pct:.1f}")

    return t


def build_inactive_table(inactive_repos):
    """Return a table of repos that haven't been pushed to in over 1 year."""
    t = Table(title="Inactive repos (>1 year since last push)",
              title_justify="left")
    t.add_column("Repo", style="red")
    t.add_column("Last push", justify="right")
    t.add_column("Stars", justify="right")
    t.add_column("Forks", justify="right")

    for r in inactive_repos:
        t.add_row(
            r["name"],
            r["pushed_at"][:10],
            str(r["stargazers_count"]),
            str(r["forks_count"]),
        )
    return t


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def save_pie_chart(lang_dist, username):
    """Create a matplotlib pie chart of the language breakdown and save it
    as {username}_profile.png.  Returns the filename."""
    filename = f"{username}_profile.png"

    if not lang_dist:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "No language data available",
                ha="center", va="center", fontsize=14)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        fig.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return filename

    labels, sizes = zip(*lang_dist)
    total = sum(sizes)

    label_texts = [
        f"{l}\n({s/total*100:.1f}%)" if s / total >= 0.03 else ""
        for l, s in zip(labels, sizes)
    ]

    colors = plt.cm.Set3([i / len(labels) for i in range(len(labels))])

    fig, ax = plt.subplots(figsize=(9, 7))
    ax.pie(
        sizes,
        labels=label_texts,
        colors=colors,
        startangle=140,
    )
    ax.set_title(
        f"Language Distribution - {username}",
        fontsize=14, fontweight="bold", pad=20,
    )

    fig.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return filename


def save_star_fork_chart(repos, username):
    """Create a grouped bar chart comparing stars vs forks for the top 10
    repos and save as {username}_star_fork.png.  Returns the filename."""
    filename = f"{username}_star_fork.png"

    if not repos:
        return None

    top10 = sorted(repos, key=lambda r: r["stargazers_count"], reverse=True)[:10]
    names = [r["name"][:20] for r in top10]
    stars = [r["stargazers_count"] for r in top10]
    forks = [r["forks_count"] for r in top10]

    x = np.arange(len(names))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))
    bars1 = ax.bar(x - width / 2, stars, width, label="Stars", color="#f1c40f")
    bars2 = ax.bar(x + width / 2, forks, width, label="Forks", color="#3498db")

    ax.set_xlabel("Repository", fontsize=11)
    ax.set_ylabel("Count", fontsize=11)
    ax.set_title(f"Top 10 Repos - Stars vs Forks ({username})",
                 fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=9)
    ax.legend()

    for bar in bars1:
        h = bar.get_height()
        if h:
            ax.annotate(str(h), xy=(bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8)
    for bar in bars2:
        h = bar.get_height()
        if h:
            ax.annotate(str(h), xy=(bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return filename


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Analyse a GitHub user's profile and repositories."
    )
    p.add_argument("--username", "-u", required=True, help="GitHub username")
    p.add_argument(
        "--token",
        help="GitHub personal access token (or set GITHUB_TOKEN env var)",
    )
    return p.parse_args()


def main():
    args = parse_args()
    username = args.username.strip().lower()

    token = args.token or os.getenv("GITHUB_TOKEN")

    session = requests.Session()
    session.headers.update({
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GitHubProfileAnalyzer/1.0",
    })
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    console = Console()

    try:
        with console.status(f"Fetching profile for @{username} ..."):
            profile = fetch_json(session, f"{GITHUB_API}/users/{username}")

        with console.status("Fetching repositories ..."):
            repos = fetch_all_repos(session, username)

        with console.status("Analysing languages ..."):
            lang_bytes = aggregate_languages(session, repos)

        with console.status("Fetching organizations ..."):
            try:
                orgs = fetch_orgs(session, username)
            except Exception:
                orgs = []

        with console.status("Fetching recent activity ..."):
            try:
                events = fetch_recent_events(session, username)
            except Exception:
                events = []

    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        sys.exit(1)

    # --- Compute stats ---------------------------------------------------

    total_stars = sum(r["stargazers_count"] for r in repos)
    total_forks = sum(r["forks_count"] for r in repos)
    total_size_mb = round(sum(r["size"] for r in repos) / 1024, 1)

    created = datetime.fromisoformat(profile["created_at"].replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - created).days
    age_years = age_days / 365.25

    unique_langs = len({r["language"] for r in repos if r["language"]})

    now = datetime.now(timezone.utc)
    inactive_repos = []
    for r in repos:
        pushed = r.get("pushed_at", "")
        if pushed:
            pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            if (now - pushed_dt).days > 365:
                inactive_repos.append(r)
    inactive_repos.sort(key=lambda r: r["pushed_at"])

    top_repos = sorted(
        repos, key=lambda r: r["stargazers_count"], reverse=True
    )[:5]
    top_forked = sorted(
        repos, key=lambda r: r["forks_count"], reverse=True
    )[:5]

    stars_per_repo = (
        f"{total_stars / len(repos):.1f}" if repos else "0"
    )

    stats = {
        "repo_count": len(repos),
        "total_stars": total_stars,
        "total_forks": total_forks,
        "total_size_mb": total_size_mb,
        "account_age": f"{age_years:.1f} years ({age_days} days)",
        "stars_per_repo": stars_per_repo,
        "unique_languages": unique_langs,
        "inactive_count": len(inactive_repos),
    }

    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)
    lang_dist = sorted_langs[:8]
    other_bytes = sum(b for _, b in sorted_langs[8:])
    if other_bytes > 0:
        lang_dist.append(("Other", other_bytes))

    # --- Render output ---------------------------------------------------

    console.print()
    console.print(
        build_profile_table(
            username, profile, stats, top_repos, top_forked, orgs, events,
        )
    )
    console.print()

    if lang_dist:
        console.print(build_lang_table(lang_dist))
        console.print()

    if inactive_repos:
        console.print(build_inactive_table(inactive_repos[:10]))
        console.print()

    with console.status("Saving pie chart ..."):
        chart_file = save_pie_chart(lang_dist, username)

    with console.status("Saving star/fork bar chart ..."):
        bar_file = save_star_fork_chart(repos, username)

    console.print(f"[green]v[/] Chart saved as [bold]{chart_file}[/]")
    if bar_file:
        console.print(f"[green]v[/] Chart saved as [bold]{bar_file}[/]")
    console.print()


if __name__ == "__main__":
    main()
