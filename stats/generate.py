#!/usr/bin/env python3
"""Writes stats/streak.svg and stats/langs.svg from the GitHub GraphQL API.

Needs GITHUB_TOKEN. A personal token (read:user, repo) also counts private repos.
"""
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape

LOGIN = os.environ.get("GITHUB_LOGIN", "bebopkenny")
OUT = os.path.dirname(os.path.abspath(__file__))
TOP_LANGS = 5  # the rest are grouped as "Other"

CALENDAR_Q = """query($l:String!,$f:DateTime!,$t:DateTime!){user(login:$l){
contributionsCollection(from:$f,to:$t){contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}"""
REPOS_Q = """query($l:String!,$c:String){user(login:$l){
repositories(first:100,after:$c,ownerAffiliations:OWNER,isFork:false){pageInfo{hasNextPage endCursor}
nodes{languages(first:20){edges{size node{name color}}}}}}}"""

# Follows the viewer's light/dark setting; colors are GitHub's own (light / dark dimmed).
STYLE = """<style>
svg{--bg:#ffffff;--border:#d0d7de;--text:#1f2328;--muted:#59636e;--accent:#0969da}
@media (prefers-color-scheme:dark){svg{--bg:#22272e;--border:#444c56;--text:#adbac7;--muted:#768390;--accent:#539bf5}}
text{font:400 12px -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;fill:var(--muted)}
.big{font-size:28px;font-weight:600;fill:var(--text)}.label{font-size:14px;fill:var(--text)}.accent{fill:var(--accent)}
</style>"""


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if body.get("errors"):
        sys.exit(f"GraphQL error: {body['errors']}")
    return body["data"]["user"]


def contribution_days():
    """[(iso date, count)] for every day since the account was created, oldest first."""
    start = datetime.fromisoformat(gql("query($l:String!){user(login:$l){createdAt}}", l=LOGIN)["createdAt"])
    now = datetime.now(timezone.utc)
    days = {}
    while start < now:  # the API returns at most one year per call
        end = min(start + timedelta(days=365), now)
        cal = gql(CALENDAR_Q, l=LOGIN, f=start.isoformat(), t=end.isoformat())
        for week in cal["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = max(days.get(d["date"], 0), d["contributionCount"])  # boundary days appear twice
        start = end
    return sorted(days.items())


def streaks(days):
    """(current, longest), each [length, first date, last date]. A quiet today doesn't break the current streak."""
    runs, run = [], None
    for d, count in days:
        if count:
            run = [run[0] + 1, run[1], d] if run else [1, d, d]
        elif run:
            runs.append(run)
            run = None
    if run:
        runs.append(run)
    none = [0, None, None]
    recent = {d for d, _ in days[-2:]}
    return (runs[-1] if runs and runs[-1][2] in recent else none), max(runs, default=none)


def top_languages():
    sizes, colors, cursor = {}, {}, None
    while True:
        repos = gql(REPOS_Q, l=LOGIN, c=cursor)["repositories"]
        for repo in repos["nodes"]:
            for e in repo["languages"]["edges"]:
                name = e["node"]["name"]
                sizes[name] = sizes.get(name, 0) + e["size"]
                colors[name] = e["node"]["color"] or "#858585"
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]
    return share_of(sorted(sizes.items(), key=lambda kv: -kv[1]), colors)


def share_of(ranked, colors):
    """Top languages plus an "Other" slice, as (name, color, percent of all code)."""
    total = sum(size for _, size in ranked) or 1
    langs = [(name, colors[name], 100 * size / total) for name, size in ranked[:TOP_LANGS]]
    rest = sum(size for _, size in ranked[TOP_LANGS:])
    return langs + [("Other", "#8b949e", 100 * rest / total)] if rest else langs


def fmt(iso):
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def card(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'{STYLE}<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="4.5" '
            f'style="fill:var(--bg);stroke:var(--border)"/>{body}</svg>\n')


def streak_svg(days):
    current, longest = streaks(days)
    first = next((d for d, c in days if c), None)
    span = lambda s: "" if not s[1] else fmt(s[1]) if s[1] == s[2] else f"{fmt(s[1])} - {fmt(s[2])}"
    cols = [
        (sum(c for _, c in days), "Total Contributions", f"{fmt(first)} - Present" if first else ""),
        (current[0], "Current Streak", span(current)),
        (longest[0], "Longest Streak", span(longest)),
    ]
    body = '<path d="M165 30v135M330 30v135" style="stroke:var(--border)"/>'
    for i, (n, label, sub) in enumerate(cols):
        x = 82.5 + 165 * i
        body += (f'<text x="{x}" y="85" text-anchor="middle" class="big{" accent" if i == 1 else ""}">{n:,}</text>'
                 f'<text x="{x}" y="118" text-anchor="middle" class="label">{label}</text>'
                 f'<text x="{x}" y="142" text-anchor="middle">{sub}</text>')
    return card(495, 195, body)


def langs_svg(langs):
    """Donut chart with a legend; the top language's share sits in the hole."""
    cx, cy, r = 110, 112, 52
    circ = 2 * math.pi * r
    body = (f'<text x="25" y="35" class="label accent">Most Used Languages</text>'
            f'<g transform="rotate(-90 {cx} {cy})" fill="none" stroke-width="18">')
    start = 0
    for _, color, pct in langs:
        length = circ * pct / 100
        # 2px gap between slices; tiny slices keep at least 1px
        body += (f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{color}" stroke-dashoffset="{-start:.2f}" '
                 f'stroke-dasharray="{max(length - 2, 1):.2f} {circ:.2f}"/>')
        start += length
    body += "</g>"
    if langs:
        name, _, pct = langs[0]
        body += (f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" class="big">{pct:.0f}%</text>'
                 f'<text x="{cx}" y="{cy + 22}" text-anchor="middle">{escape(name)}</text>')
    top = cy - 11 * (len(langs) - 1)  # legend is centered on the donut
    for i, (name, color, pct) in enumerate(langs):
        y = top + 22 * i
        body += (f'<circle cx="235" cy="{y - 4}" r="5" fill="{color}"/>'
                 f'<text x="250" y="{y}" class="label">{escape(name)}</text>'
                 f'<text x="470" y="{y}" text-anchor="end">{pct:.1f}%</text>')
    return card(495, 195, body)


def self_check():
    d = lambda counts: [(f"2026-01-{i + 1:02}", c) for i, c in enumerate(counts)]
    assert streaks(d([1, 1, 0, 1, 1, 1])) == ([3, "2026-01-04", "2026-01-06"], [3, "2026-01-04", "2026-01-06"])
    assert streaks(d([1, 1, 1, 0, 1, 0])) == ([1, "2026-01-05", "2026-01-05"], [3, "2026-01-01", "2026-01-03"])
    assert streaks(d([1, 1, 0, 0])) == ([0, None, None], [2, "2026-01-01", "2026-01-02"])
    assert streaks(d([0, 0])) == ([0, None, None], [0, None, None])
    ranked = [(f"L{i}", 10) for i in range(7)] + [("L7", 30)]
    langs = share_of(sorted(ranked, key=lambda kv: -kv[1]), {n: "#000" for n, _ in ranked})
    assert [n for n, _, _ in langs] == ["L7", "L0", "L1", "L2", "L3", "Other"] and abs(sum(p for *_, p in langs) - 100) < 1e-9


if __name__ == "__main__":
    self_check()
    with open(os.path.join(OUT, "streak.svg"), "w") as f:
        f.write(streak_svg(contribution_days()))
    with open(os.path.join(OUT, "langs.svg"), "w") as f:
        f.write(langs_svg(top_languages()))
