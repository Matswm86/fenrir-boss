# ruff: noqa: E501  (HTML and CSS templates are long by nature)
"""Render the site to static HTML; with `[web] enabled`, rsync it to your own server.

Two pages. `/` is a public landing page for the fictional company: no names, no paths.
`/board/` is the working board (tickets, meetings, reviews, inbox); on a server it must sit
behind your reverse proxy's login (docs/SELF-HOSTING.md). Home-directory paths are folded to `~` before anything leaves
this machine.
"""

from __future__ import annotations

import html
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from boss import desk, desk_page, ladder, meetings
from boss.config import Config
from boss.state import State, parse_iso

CSS = """
:root{color-scheme:dark}body{margin:0;background:#0e1013;color:#d8dbe0;font:15px/1.5 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:32px 20px}h1{font-size:28px;letter-spacing:.08em;margin:0 0 4px}
h1 span{color:#c9412f}h2{font-size:17px;margin:32px 0 10px;color:#9aa3ad;text-transform:uppercase;letter-spacing:.12em}
table{width:100%;border-collapse:collapse}td,th{padding:8px 10px;border-bottom:1px solid #22262c;text-align:left;vertical-align:top}
th{color:#9aa3ad;font-weight:600}.ok{color:#5fb36a}.bad{color:#e06c5a}.dim{color:#7d868f}
pre{white-space:pre-wrap;background:#14171b;border:1px solid #22262c;border-radius:6px;padding:12px;font:13px/1.45 ui-monospace,monospace}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;background:#1c2026;color:#c9ced4;font-size:12px}
footer{margin-top:48px;color:#5d656e;font-size:13px}a{color:#9fc0e6}
"""


def _fold(text: str) -> str:
    return desk.fold_home(text)


def _esc(text: object) -> str:
    return html.escape(_fold(str(text)))


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        f"<title>{_esc(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>"
    )


def render_landing(cfg: Config) -> str:
    company = cfg.section("company")
    name = company["name"]
    body = (
        f"<h1>{_esc(name)}</h1>"
        f"<p class=dim>{_esc(company.get('city', ''))}</p>"
        '<p>The desk is at <a href="/desk/">/desk/</a>.</p>'
        f"<footer>{_esc(name)} is a fictional workplace used as a training environment. It "
        "has no clients, no employees and no products, and it is not affiliated with any real "
        "organisation of the same or a similar name.</footer>"
    )
    return _page(name, body)


def render_board(cfg: Config, state: State) -> str:
    now = datetime.now(UTC)
    tz = cfg.tz
    level = state.level
    lvl = ladder.get_level(level)
    rows = []
    for t in state.tickets():
        due = parse_iso(t["due_at"])
        cls = "bad" if (t["status"] in {"open", "changes_requested"} and now > due) else ""
        rows.append(
            f"<tr><td>{_esc(t['id'])}</td><td>{_esc(t['title'])}</td><td>{_esc(t['client'])}</td>"
            f"<td><span class=tag>{_esc(t['status'])}</span></td>"
            f'<td class="{cls}">{due.astimezone(tz):%a %d %b %H:%M}</td></tr>'
        )
    tickets_html = (
        "<table><tr><th>Id</th><th>Title</th><th>Client</th><th>Status</th><th>Due</th></tr>"
        + "".join(reversed(rows))
        + "</table>"
        if rows
        else "<p class=dim>No tickets yet.</p>"
    )
    mrows = []
    for m in state.meetings():
        when = parse_iso(m["when_at"])
        if when < now and m["status"] in {"held", "missed"} and (now - when).days > 7:
            continue
        mrows.append(
            f"<tr><td>{_esc(m['id'])}</td><td>{_esc(meetings.LABEL.get(m['type'], m['type']))}</td>"
            f"<td>{when.astimezone(tz):%a %d %b %H:%M}</td><td><span class=tag>{_esc(m['status'])}</span></td>"
            f"<td>{_esc(m['client'] or '')}</td></tr>"
        )
    meetings_html = (
        "<table><tr><th>Id</th><th>Type</th><th>When</th><th>Status</th><th>Client</th></tr>"
        + "".join(mrows)
        + "</table>"
        if mrows
        else "<p class=dim>Nothing scheduled.</p>"
    )
    rrows = []
    for r in state.recent_reviews(8):
        cls = "ok" if r["verdict"] == "APPROVED" else "bad"
        rrows.append(
            f'<tr><td>{_esc(r["ticket_id"])}</td><td class="{cls}">{_esc(r["verdict"])}</td>'
            f"<td>{r['score']}/5</td><td>{_esc(r['summary'] or '')}</td></tr>"
        )
    reviews_html = (
        "<table><tr><th>Ticket</th><th>Verdict</th><th>Score</th><th>Summary</th></tr>"
        + "".join(rrows)
        + "</table>"
        if rrows
        else "<p class=dim>No reviews yet.</p>"
    )
    inbox_html = (
        "".join(
            f"<h3>{_esc(m['subject'])} <span class=dim>{parse_iso(m['created_at']).astimezone(tz):%a %d %b %H:%M}</span></h3>"
            f"<pre>{_esc(m['body'])}</pre>"
            for m in state.messages(10)
        )
        or "<p class=dim>Inbox empty.</p>"
    )
    ladder_html = "".join(
        f"<tr><td>{'&#9654;' if lv.number == level else ''}</td><td>L{lv.number}</td><td>{_esc(lv.name)}</td>"
        f"<td>{state.accepted_count(lv.number)}/{lv.required_accepted}</td></tr>"
        for lv in ladder.LEVELS
    )
    body = (
        f"<h1>{_esc(cfg.company)} <span>board</span></h1>"
        '<p><a href="/desk/">Open the desk</a>: ticket, threads, standup, inbox.</p>'
        f"<p class=dim>Level L{level} {_esc(lvl.name)}. {_esc(cfg.boss_name)}, {_esc(cfg.section('boss').get('title', ''))}. "
        f"Rendered {now.astimezone(tz):%a %d %b %Y %H:%M}.</p>"
        f"<h2>Tickets</h2>{tickets_html}"
        f"<h2>Meetings</h2>{meetings_html}"
        f"<h2>Reviews</h2>{reviews_html}"
        f"<h2>Ladder</h2><table>{ladder_html}</table>"
        f"<h2>Inbox</h2>{inbox_html}"
        "<footer>Private engineering board of a fictional company. Training environment.</footer>"
    )
    return _page(f"{cfg.company} board", body)


def write_site(cfg: Config, state: State) -> Path:
    site = cfg.root / "site"
    (site / "board").mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(render_landing(cfg), encoding="utf-8")
    (site / "board" / "index.html").write_text(render_board(cfg, state), encoding="utf-8")
    (site / "desk").mkdir(parents=True, exist_ok=True)
    (site / "desk" / "index.html").write_text(desk_page.HTML, encoding="utf-8")
    (site / "desk" / "desk.css").write_text(desk_page.CSS, encoding="utf-8")
    (site / "desk" / "app.js").write_text(desk_page.JS, encoding="utf-8")
    (site / "desk" / "bundle.json").write_text(
        json.dumps(desk.bundle(cfg, state), ensure_ascii=False), encoding="utf-8"
    )
    (site / "board" / "state.json").write_text(
        json.dumps(
            {
                "level": state.level,
                "open": [dict(t)["id"] for t in state.open_tickets()],
                "rendered": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )
    return site


def publish(cfg: Config, state: State, timeout: int = 60) -> str:
    web = cfg.section("web")
    site = write_site(cfg, state)
    if not web.get("enabled"):
        return f"rendered {site} (web.enabled is false, not uploaded)"
    host, webroot = web.get("host"), web.get("webroot")
    if not host or not webroot:
        return f"rendered {site} (web.host/webroot missing, not uploaded)"
    cmd = [
        "rsync",
        "-az",
        "--chmod=D755,F644",
        "-e",
        "ssh -o BatchMode=yes -o ConnectTimeout=10",
        f"{site}/",
        f"{host}:{webroot}/",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"rendered {site}; upload failed: {type(exc).__name__}"
    if proc.returncode != 0:
        return f"rendered {site}; upload failed: {(proc.stderr or '').strip()[:200]}"
    return f"published to {web.get('url', host)}"
