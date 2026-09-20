# ruff: noqa: E501  (HTML, CSS and JS templates are long by nature)
"""The worker page at /desk/: static files, no build step, no inline scripts (the vhost's CSP
allows scripts only from its own origin as files). The page reads bundle.json next to it and
talks to /api/ (`boss desk` serves both; a reverse proxy strips the prefix when self-hosted)."""

from __future__ import annotations

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Desk</title>
<link rel="stylesheet" href="/desk/desk.css">
</head>
<body>
<header>
  <div class="brand"><a href="/desk/"><b id="brand">Desk</b> <span>desk</span></a></div>
  <div id="who" class="who"></div>
</header>
<nav id="tabs" class="tabs">
  <button data-tab="today">Today</button>
  <button data-tab="ticket">Ticket</button>
  <button data-tab="boss" id="tab-boss">Boss</button>
  <button data-tab="tutor" id="tab-tutor">Tutor</button>
  <button data-tab="standup">Standup</button>
  <button data-tab="inbox">Inbox</button>
  <button data-tab="ladder">Ladder</button>
</nav>
<main id="view"><p class="dim">Loading the desk...</p></main>
<footer id="foot">Private worker area of a fictional company. Training environment.</footer>
<script src="/desk/app.js"></script>
</body>
</html>
"""

CSS = """
:root{color-scheme:dark;--bg:#0e1013;--panel:#14171b;--line:#22262c;--fg:#d8dbe0;--dim:#7d868f;--red:#c9412f;--ok:#5fb36a;--bad:#e06c5a;--link:#9fc0e6;--you:#1c2430;--boss:#2a1c1c;--tutor:#1b2a22}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
a{color:var(--link)}
header{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;border-bottom:1px solid var(--line)}
.brand a{color:var(--fg);text-decoration:none;font-size:20px;letter-spacing:.08em;font-weight:600}
.brand span{color:var(--red)}
.who{color:var(--dim);font-size:13px;text-align:right}
.tabs{display:flex;gap:4px;padding:10px 16px;border-bottom:1px solid var(--line);overflow-x:auto}
.tabs button{background:none;border:1px solid transparent;color:var(--dim);padding:6px 12px;border-radius:6px;font:inherit;cursor:pointer;white-space:nowrap}
.tabs button.on{color:var(--fg);border-color:var(--line);background:var(--panel)}
.tabs button .n{display:inline-block;min-width:18px;padding:0 5px;margin-left:6px;border-radius:9px;background:var(--red);color:#fff;font-size:11px;text-align:center}
main{max-width:980px;margin:0 auto;padding:22px 16px 60px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:14px;margin:26px 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.12em}
h3{font-size:15px;margin:18px 0 6px}
.dim{color:var(--dim)}.ok{color:var(--ok)}.bad{color:var(--bad)}
pre,.msg{white-space:pre-wrap;word-wrap:break-word;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px;font:13px/1.45 ui-monospace,monospace;margin:0 0 10px}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;background:#1c2026;color:#c9ced4;font-size:12px;margin-left:6px}
.tag.bad{background:#3a1d18;color:#f0a090}
table{width:100%;border-collapse:collapse}
td,th{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:14px}
th{color:var(--dim);font-weight:600}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:720px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.check{list-style:none;padding:0;margin:0}
.check li{display:flex;gap:10px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--line)}
.check input{margin-top:5px}
.check li.done label{color:var(--dim);text-decoration:line-through}
.thread{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}
.bubble{padding:10px 14px;border-radius:10px;max-width:92%;white-space:pre-wrap;word-wrap:break-word}
.bubble.you{align-self:flex-end;background:var(--you)}
.bubble.boss{align-self:flex-start;background:var(--boss);border-left:3px solid var(--red)}
.bubble.tutor{align-self:flex-start;background:var(--tutor);border-left:3px solid var(--ok)}
.bubble .meta{display:block;color:var(--dim);font-size:11px;margin-bottom:3px}
.bubble.waiting{opacity:.6;border-left-style:dashed}
.compose{display:flex;flex-direction:column;gap:8px}
textarea,input[type=text]{width:100%;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:10px;font:inherit}
textarea{min-height:84px;resize:vertical}
button.go{align-self:flex-end;background:var(--red);color:#fff;border:0;border-radius:6px;padding:9px 16px;font:inherit;cursor:pointer}
button.go:disabled{opacity:.5;cursor:wait}
button.link{background:none;border:0;color:var(--link);cursor:pointer;font:inherit;padding:0}
.note{font-size:13px;color:var(--dim);margin:0 0 10px}
.status{font-size:13px;margin:8px 0;color:var(--dim)}
.status.bad{color:var(--bad)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:14px}
.kv dt{color:var(--dim)}.kv dd{margin:0}
select{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px;font:inherit}
details summary{cursor:pointer;color:var(--link)}
footer{max-width:980px;margin:0 auto;padding:12px 16px 24px;color:#5d656e;font-size:13px}
.brief{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--red);border-radius:8px;padding:16px 18px;margin-bottom:16px}
.brief p{margin:0 0 8px}
.needs{list-style:none;padding:0;margin:0}
.needs li{display:flex;gap:10px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line)}
.needs .k{min-width:72px;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--red)}
.needs code,.bar{font:12px/1.4 ui-monospace,monospace}
.bar{display:flex;align-items:center;gap:10px;margin:4px 0}
.bar .track{flex:1;height:8px;background:#1c2026;border-radius:4px;overflow:hidden}
.bar .fill{height:100%;background:var(--ok)}
.feed{list-style:none;padding:0;margin:0}
.feed li{display:grid;grid-template-columns:120px 1fr;gap:12px;padding:6px 0;border-bottom:1px solid var(--line);font-size:14px}
.feed .t{color:var(--dim);font-size:12px;padding-top:2px}
.stat{display:inline-block;margin:0 18px 6px 0}.stat b{font-size:20px;display:block}
.pill{display:inline-block;border:1px solid var(--line);border-radius:12px;padding:1px 9px;font-size:12px;color:var(--dim);margin:2px 4px 2px 0}
"""

JS = r"""
(function () {
  'use strict';
  function TZname() { return (S.bundle && S.bundle.timezone) || 'UTC'; }
  function bossN() { return (S.bundle && S.bundle.boss_first) || 'Boss'; }
  function tutorN() { return (S.bundle && S.bundle.tutor_name) || 'Tutor'; }
  var S = { bundle: null, act: null, tab: 'ticket', ticket: null, apiOk: true, apiErr: '' };
  var view = document.getElementById('view');
  var tabs = document.getElementById('tabs');

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function when(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString('en-GB', { timeZone: TZname(), weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); }
    catch (e) { return iso; }
  }
  function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || 'null'); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; } }
  function api(path, body) {
    var opts = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' };
    return fetch('/api' + path, opts).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; });
    });
  }
  function ticket() {
    var b = S.bundle; if (!b || !b.tickets.length) return null;
    var byId = {}; b.tickets.forEach(function (t) { byId[t.id] = t; });
    if (S.ticket && byId[S.ticket]) return byId[S.ticket];
    if (b.open.length && byId[b.open[0]]) return byId[b.open[0]];
    return b.tickets[b.tickets.length - 1];
  }
  function answerFor(id) { return (S.bundle && S.bundle.answers && id && S.bundle.answers[id]) || null; }
  function thread(tid, channel) {
    var th = (S.act && S.act.threads && S.act.threads[tid]) || [];
    var out = [];
    th.forEach(function (m) {
      if (m.channel !== channel) return;
      out.push(m);
      if (m.pending) {
        var a = answerFor(m.id);
        if (a) out.push({ who: channel, channel: channel, text: a.reply, at: a.at });
        else out.push({ who: channel, channel: channel, text: (S.bundle && S.bundle.eta) || 'Answer on its way.', at: m.at, waiting: true });
      }
    });
    return out;
  }
  function countdown(iso) {
    var ms = new Date(iso) - new Date(); var h = Math.round(Math.abs(ms) / 36e5);
    var d = Math.floor(h / 24); h = h % 24;
    var s = (d ? d + ' d ' : '') + h + ' h';
    return ms < 0 ? '<span class="bad">overdue by ' + s + '</span>' : 'in ' + s;
  }

  // ---- views --------------------------------------------------------------
  function greeting() {
    var h = parseInt(new Date().toLocaleString('en-GB', { timeZone: TZname(), hour: '2-digit', hour12: false }), 10);
    return h < 5 ? 'Still up' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  }
  function feed() {
    var b = S.bundle, items = [];
    (b.messages || []).forEach(function (m) { items.push({ at: m.created_at, who: b.boss_first, text: m.subject, kind: m.kind }); });
    (b.reviews || []).forEach(function (r) { items.push({ at: r.created_at, who: b.boss_first, text: 'Reviewed ' + r.ticket_id + ': ' + r.verdict + ' ' + r.score + '/5', kind: 'review' }); });
    (b.meetings || []).forEach(function (m) { if (m.status === 'held') items.push({ at: m.when_at, who: 'both', text: m.label + ' held (' + m.id + ')', kind: 'meeting' }); });
    if (S.act) {
      Object.keys(S.act.threads || {}).forEach(function (tid) {
        S.act.threads[tid].forEach(function (m) { if (m.who === 'you') items.push({ at: m.at, who: 'you', text: 'Asked ' + (m.channel === 'boss' ? b.boss_first : tutorN()) + ' about ' + tid + ': ' + m.text.slice(0, 80), kind: 'desk' }); });
      });
      (S.act.standups || []).forEach(function (s) { items.push({ at: s.at, who: 'you', text: 'Posted standup from the desk', kind: 'standup' }); });
      (S.act.notes || []).forEach(function (n) { items.push({ at: n.at, who: 'you', text: 'Note: ' + n.text.slice(0, 80), kind: 'note' }); });
    }
    items.sort(function (a, c) { return a.at < c.at ? 1 : -1; });
    return items.slice(0, 20);
  }
  function vToday() {
    var b = S.bundle, t = ticket(), p = b.progress || {}, need = b.needs_you || [];
    var lvl = (b.ladder || []).filter(function (l) { return l.current; })[0];
    var pct = lvl && lvl.required ? Math.min(100, Math.round(100 * lvl.accepted / lvl.required)) : 0;
    var openLine = t && (t.status === 'open' || t.status === 'changes_requested')
      ? 'Open: <b>' + esc(t.id) + '</b> ' + esc(t.title) + ' for ' + esc(t.client) + ', due ' + esc(t.due_local) + ' (' + countdown(t.due_at) + ').'
      : 'No open ticket. The next tick assigns one.';
    var needHtml = need.length ? '<ul class="needs">' + need.map(function (n) {
      return '<li><span class="k">' + esc(n.kind) + '</span><span>' + esc(n.text) + ' <button class="link" data-go="' + esc(n.tab) + '">open</button>' + (n.cmd ? '<br><code>' + esc(n.cmd) + '</code>' : '') + '</span></li>';
    }).join('') + '</ul>' : '<p class="dim">Nothing waits on you right now.</p>';
    var fd = feed();
    var feedHtml = fd.length ? '<ul class="feed">' + fd.map(function (i) { return '<li><span class="t">' + esc(when(i.at)) + '</span><span><span class="dim">' + esc(i.who) + '</span> ' + esc(i.text) + '</span></li>'; }).join('') + '</ul>' : '<p class="dim">Quiet.</p>';
    return '<div class="brief"><h1>' + greeting() + ', ' + esc(b.engineer_name) + '.</h1>' +
      '<p>' + openLine + '</p>' +
      '<p>Level L' + b.level + ' ' + esc(b.level_name) + ': ' + (lvl ? lvl.accepted + ' of ' + lvl.required + ' tickets accepted' : '') + '. Day ' + (p.days_in || 0) + ' at ' + esc(b.company) + '. Standup streak ' + (p.standup_streak || 0) + (p.standups_missed ? ', ' + p.standups_missed + ' missed' : '') + '.</p>' +
      '<p class="dim">' + esc(b.boss_first) + ' writes the tickets and the reviews; ' + esc(tutorN()) + ' explains. Neither writes your code.</p></div>' +
      '<h2>Needs you</h2>' + needHtml +
      '<h2>Progress</h2><div class="card">' +
      '<div class="stat"><b>' + (p.tickets_done || 0) + '</b>tickets done</div><div class="stat"><b>' + (p.approved || 0) + '/' + (p.reviews || 0) + '</b>reviews approved</div><div class="stat"><b>' + (p.standups_held || 0) + '</b>standups held</div>' +
      '<div class="bar"><span>L' + b.level + '</span><div class="track"><div class="fill" style="width:' + pct + '%"></div></div><span>' + pct + '%</span></div>' +
      '<p class="note">This level trains: ' + esc((b.competencies || []).join('; ')) + '</p></div>' +
      '<h2>Activity</h2>' + feedHtml;
  }

  function vTicket() {
    var b = S.bundle, t = ticket();
    if (!t) return '<h1>No ticket yet</h1><p class="dim">The next tick assigns one. Read the handbook on the Ladder tab meanwhile.</p>';
    var picker = '';
    if (b.tickets.length > 1) {
      picker = '<p><select id="pick">' + b.tickets.slice().reverse().map(function (x) { return '<option value="' + esc(x.id) + '"' + (x.id === t.id ? ' selected' : '') + '>' + esc(x.id + ' ' + x.title + ' [' + x.status + ']') + '</option>'; }).join('') + '</select></p>';
    }
    var ticks = store('desk_ticks_' + t.id) || {};
    var crit = t.acceptance.map(function (a, i) {
      var on = !!ticks[i];
      return '<li class="' + (on ? 'done' : '') + '"><input type="checkbox" data-i="' + i + '"' + (on ? ' checked' : '') + ' id="c' + i + '"><label for="c' + i + '">' + esc(a) + '</label></li>';
    }).join('');
    var openState = t.status === 'open' || t.status === 'changes_requested';
    var cmds = 'cd ' + t.sandbox + '\nuv sync\n' + t.run_command + '\nuv run ruff check .\nboss submit ' + t.id + ' -m "what you did and what you are unsure about"';
    var reviews = (b.reviews || []).filter(function (r) { return r.ticket_id === t.id; });
    return picker +
      '<h1>' + esc(t.id) + ': ' + esc(t.title) + '<span class="tag' + (t.overdue ? ' bad' : '') + '">' + esc(t.status) + '</span></h1>' +
      '<p class="dim">Client ' + esc(t.client) + '. Level L' + t.level + '. Due ' + esc(t.due_local) + (openState ? ', ' + countdown(t.due_at) : '') + '.</p>' +
      '<div class="grid">' +
      '<div class="card"><h3>Acceptance criteria <span class="dim">(your own ticks, this browser only)</span></h3><ul class="check" id="crit">' + crit + '</ul></div>' +
      '<div class="card"><h3>In the sandbox</h3><pre>' + esc(cmds) + '</pre>' +
      '<dl class="kv"><dt>Tests</dt><dd>' + (t.test_names.length ? t.test_names.map(function (n) { return '<span class="pill">' + esc(n) + '</span>'; }).join('') : '<span class="dim">none found</span>') + '</dd>' +
      '<dt>Your files</dt><dd>' + (t.src_files.length ? t.src_files.map(function (n) { return '<span class="pill">' + esc(n) + '</span>'; }).join('') : '<span class="dim">none</span>') + '</dd></dl>' +
      '<p class="note">Stuck on a concept: the ' + esc(tutorN()) + ' tab. Unclear what the ticket wants: the ' + esc(bossN()) + ' tab. Neither writes your code.</p></div>' +
      '</div>' +
      '<h2>The ticket</h2><pre>' + esc(t.ticket_md || t.brief) + '</pre>' +
      (reviews.length ? '<h2>Reviews of this ticket</h2>' + reviews.map(function (r) { return '<h3><span class="' + (r.verdict === 'APPROVED' ? 'ok' : 'bad') + '">' + esc(r.verdict) + '</span> ' + r.score + '/5 <span class="dim">' + esc(when(r.created_at)) + '</span></h3><pre>' + esc(r.feedback_md || r.summary) + '</pre>'; }).join('') : '');
  }

  function vChat(channel) {
    var t = ticket(), tid = t ? t.id : 'general';
    var isBoss = channel === 'boss';
    var head = isBoss
      ? '<h1>' + esc(S.bundle.boss_name) + ' <span class="dim">' + esc(S.bundle.boss_title) + '</span></h1><p class="note">Questions about the ticket, between meetings: what it asks, what gets checked at review, the next step. Never your code. Answers arrive on this page in the same voice as the reviews and 1:1s; the page refreshes by itself.</p>'
      : '<h1>' + esc(tutorN()) + ' <span class="dim">study mode</span></h1><p class="note">Explains with a picture, quizzes you, sets a one-to-three-line experiment. Refuses to write code; that is the rule of this place. In the terminal: <code>boss help "question"</code>.</p>';
    var msgs = thread(tid, channel);
    var body = msgs.length ? msgs.map(function (m) {
      var who = m.who === 'you' ? 'you' : (isBoss ? bossN() : tutorN());
      return '<div class="bubble ' + esc(m.who) + (m.waiting ? ' waiting' : '') + '"><span class="meta">' + esc(who) + ' · ' + esc(when(m.at)) + (m.waiting ? ' · waiting' : '') + '</span>' + esc(m.text) + '</div>';
    }).join('') : '<p class="dim">Nothing yet on ' + esc(tid) + '.</p>';
    var hint = isBoss ? 'e.g. Is criterion 3 about the file or about git?' : 'e.g. What does a pytest AssertionError actually compare?';
    var deepBox = '';
    return head +
      '<p class="dim">Thread for ' + esc(tid) + (t ? ': ' + esc(t.title) : '') + '</p>' +
      '<div class="thread" id="thread">' + body + '</div>' +
      '<div class="compose">' + deepBox + '<textarea id="q" placeholder="' + esc(hint) + '"></textarea>' +
      '<div class="status" id="st">' + (S.apiOk ? '' : '<span class="bad">Desk service unreachable: ' + esc(S.apiErr) + '</span>') + '</div>' +
      '<button class="go" id="send" data-channel="' + channel + '">' + ('Ask ' + esc(isBoss ? bossN() : tutorN())) + '</button></div>';
  }

  function vStandup() {
    var b = S.bundle;
    var posted = (S.act && S.act.standups) || [];
    var held = (b.meetings || []).filter(function (m) { return m.type === 'standup' && m.status === 'held'; });
    var next = (b.meetings || []).filter(function (m) { return m.type === 'standup' && (m.status === 'scheduled' || m.status === 'notified') && new Date(m.when_at) > new Date(); })[0];
    var hist = posted.slice().reverse().map(function (s) {
      var a = s.reply ? { reply: s.reply } : answerFor(s.id);
      var bubble = a ? '<div class="bubble boss"><span class="meta">' + esc(bossN()) + '</span>' + esc(a.reply) + '</div>' : '<div class="bubble boss waiting"><span class="meta">' + esc(bossN()) + ' · waiting</span>' + esc((S.bundle && S.bundle.eta) || '') + '</div>';
      return '<h3>' + esc(when(s.at)) + ' <span class="dim">from the desk</span></h3><pre>Yesterday: ' + esc(s.answers.yesterday || '(blank)') + '\nToday: ' + esc(s.answers.today || '(blank)') + '\nBlockers: ' + esc(s.answers.blockers || '(none)') + '</pre>' + bubble;
    }).join('');
    var termHist = held.slice().reverse().slice(0, 5).map(function (m) { return '<h3>' + esc(m.when_local) + ' <span class="dim">' + esc(m.id) + '</span></h3><div class="bubble boss"><span class="meta">' + esc(bossN()) + '</span>' + esc(m.minutes || '(no reply recorded)') + '</div>'; }).join('');
    return '<h1>Standup</h1><p class="note">Async: three lines, facts, any time on a standup day. ' + (next ? 'Next: ' + esc(next.when_local) + ' (' + esc(next.id) + ').' : '') + ' Posting here counts the same as <code>boss standup</code>.</p>' +
      '<div class="compose"><input type="text" id="y" placeholder="Yesterday"><input type="text" id="t" placeholder="Today"><input type="text" id="bl" placeholder="Blockers (or: none)">' +
      '<div class="status" id="st"></div><button class="go" id="post">Post standup</button></div>' +
      (hist ? '<h2>Posted from the desk</h2>' + hist : '') +
      (termHist ? '<h2>Held in the terminal</h2>' + termHist : '');
  }

  function vInbox() {
    var b = S.bundle;
    var notes = (S.act && S.act.notes) || [];
    var msgs = (b.messages || []).map(function (m) {
      return '<h3>' + esc(m.subject) + ' <span class="tag">' + esc(m.kind) + '</span> <span class="dim">' + esc(when(m.created_at)) + '</span></h3><pre>' + esc(m.body) + '</pre>';
    }).join('') || '<p class="dim">Inbox empty.</p>';
    var noteHist = notes.slice().reverse().map(function (n) {
      var a = n.reply ? { reply: n.reply } : answerFor(n.id);
      var bubble = a ? '<div class="bubble boss"><span class="meta">' + esc(bossN()) + '</span>' + esc(a.reply) + '</div>' : '<div class="bubble boss waiting"><span class="meta">' + esc(bossN()) + ' · waiting</span>' + esc((S.bundle && S.bundle.eta) || '') + '</div>';
      return '<div class="bubble you"><span class="meta">you · ' + esc(when(n.at)) + '</span>' + esc(n.text) + '</div>' + bubble;
    }).join('');
    var meet = (b.meetings || []).filter(function (m) { return m.status === 'scheduled' || m.status === 'notified'; }).map(function (m) { return '<tr><td>' + esc(m.id) + '</td><td>' + esc(m.label) + (m.client ? ': ' + esc(m.client) : '') + '</td><td>' + esc(m.when_local) + '</td></tr>'; }).join('');
    return '<h1>Inbox</h1>' +
      '<div class="card"><h3>Message ' + esc(bossN()) + '</h3><p class="note">Outside meetings: an extension, a scope question, something you need decided. The answer lands here and in the decision log.</p>' +
      '<div class="compose"><textarea id="note" placeholder="e.g. I need until Thursday on this ticket; the setup step took my whole evening."></textarea><div class="status" id="st"></div><button class="go" id="sendnote">Send</button></div>' +
      '<div class="thread" id="notes">' + noteHist + '</div></div>' +
      (meet ? '<h2>Coming up</h2><table><tr><th>Id</th><th>What</th><th>When</th></tr>' + meet + '</table>' : '') +
      '<h2>From ' + esc(bossN()) + '</h2>' + msgs;
  }

  function vLadder() {
    var b = S.bundle;
    var rows = b.ladder.map(function (l) { return '<tr><td>' + (l.current ? '&#9654;' : '') + '</td><td>L' + l.number + '</td><td>' + esc(l.name) + '</td><td class="dim">' + esc(l.phase) + '</td><td>' + l.accepted + '/' + l.required + '</td></tr>'; }).join('');
    var comp = (b.competencies || []).map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('');
    return '<h1>Ladder</h1><p class="dim">You are at L' + b.level + ' ' + esc(b.level_name) + '. Today: ' + b.llm_today.quality_calls + ' quality calls, $' + b.llm_today.spend_usd.toFixed(2) + '.</p>' +
      '<table><tr><th></th><th>Level</th><th>Name</th><th>Maps to</th><th>Accepted</th></tr>' + rows + '</table>' +
      '<h2>This level trains</h2><ul>' + comp + '</ul>' +
      '<h2>Handbook</h2><details><summary>Read it once</summary><pre>' + esc(b.handbook || '(no handbook yet)') + '</pre></details>' +
      '<h2>Help beside the desk</h2><ul><li>Terminal: <code>boss help "question"</code> asks ' + esc(tutorN()) + ' with the ticket attached; <code>boss ask "question"</code> asks ' + esc(bossN()) + '.</li></ul>';
  }

  // ---- render + events ---------------------------------------------------
  function render() {
    if (!S.bundle) return;
    var b = S.bundle, t = ticket();
    document.getElementById('brand').textContent = b.company;
    document.title = b.company + ' desk';
    document.getElementById('tab-boss').textContent = bossN();
    document.getElementById('tab-tutor').textContent = tutorN();
    document.getElementById('who').innerHTML = esc(b.engineer_name) + ' reports to ' + esc(b.boss_name) + '<br>L' + b.level + ' ' + esc(b.level_name) + ' · rendered ' + esc(when(b.rendered));
    Array.prototype.forEach.call(tabs.querySelectorAll('button'), function (btn) {
      btn.classList.toggle('on', btn.dataset.tab === S.tab);
      var n = '';
      if (btn.dataset.tab === 'ticket' && t && t.overdue) n = '!';
      btn.innerHTML = esc(btn.textContent.replace(/[!\d]+$/, '').trim()) + (n ? '<span class="n">' + n + '</span>' : '');
    });
    var v = { today: vToday, ticket: vTicket, boss: function () { return vChat('boss'); }, tutor: function () { return vChat('tutor'); }, standup: vStandup, inbox: vInbox, ladder: vLadder }[S.tab] || vToday;
    view.innerHTML = v();
    var th = document.getElementById('thread'); if (th) th.scrollTop = th.scrollHeight;
    store('desk_tab', S.tab);
  }

  function busy(id, on) { var el = document.getElementById(id); if (el) el.disabled = !!on; }
  function status(msg, bad) { var el = document.getElementById('st'); if (el) { el.textContent = msg || ''; el.classList.toggle('bad', !!bad); } }

  tabs.addEventListener('click', function (e) {
    var btn = e.target.closest('button'); if (!btn) return;
    S.tab = btn.dataset.tab; render();
  });

  view.addEventListener('change', function (e) {
    if (e.target.id === 'pick') { S.ticket = e.target.value; store('desk_ticket', S.ticket); render(); return; }
    if (e.target.matches('#crit input')) {
      var t = ticket(); if (!t) return;
      var ticks = store('desk_ticks_' + t.id) || {};
      ticks[e.target.dataset.i] = e.target.checked; store('desk_ticks_' + t.id, ticks);
      e.target.closest('li').classList.toggle('done', e.target.checked);
    }
  });

  view.addEventListener('click', function (e) {
    var btn = e.target.closest('button'); if (!btn) return;
    var t = ticket(), tid = t ? t.id : 'general';
    if (btn.dataset.go) { S.tab = btn.dataset.go; render(); return; }
    if (btn.id === 'send') {
      var q = document.getElementById('q').value.trim(); if (!q) return;
      var channel = btn.dataset.channel, path = channel === 'boss' ? '/ask-boss' : '/ask-tutor';
      busy('send', true); status('Sending...');
      api(path, { ticket: tid, question: q }).then(function (r) {
        S.act = S.act || { threads: {}, standups: [], notes: [] };
        var th = S.act.threads[tid] = S.act.threads[tid] || [];
        if (r.queued) {
          th.push({ id: r.id, who: 'you', channel: channel, text: q, at: r.at, pending: true });
        } else {
          th.push({ who: 'you', channel: channel, text: q, at: r.at });
          th.push({ who: channel, channel: channel, text: r.reply, at: r.at });
        }
        render();
      }).catch(function (err) { busy('send', false); status('Failed: ' + err.message, true); });
    } else if (btn.id === 'post') {
      var a = { yesterday: document.getElementById('y').value.trim(), today: document.getElementById('t').value.trim(), blockers: document.getElementById('bl').value.trim() };
      if (!a.yesterday && !a.today && !a.blockers) { status('Three empty lines is not a standup.', true); return; }
      busy('post', true); status('Posting...');
      api('/standup', a).then(function (r) {
        S.act = S.act || { threads: {}, standups: [], notes: [] };
        S.act.standups.push({ id: r.id, at: r.at, answers: a, reply: r.reply || null }); render();
      }).catch(function (err) { busy('post', false); status('Failed: ' + err.message, true); });
    } else if (btn.id === 'sendnote') {
      var n = document.getElementById('note').value.trim(); if (!n) return;
      busy('sendnote', true); status('Sending...');
      api('/note', { text: n }).then(function (r) {
        S.act = S.act || { threads: {}, standups: [], notes: [] };
        S.act.notes.push({ id: r.id, at: r.at, text: n, reply: r.reply || null }); render();
      }).catch(function (err) { busy('sendnote', false); status('Failed: ' + err.message, true); });
    }
  });

  view.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      var b = document.getElementById('send') || document.getElementById('post') || document.getElementById('sendnote');
      if (b) b.click();
    }
  });

  // ---- refresh: her answers arrive through the bundle, so poll it -----------
  var lastSig = '';
  function refresh() {
    Promise.all([
      fetch('/desk/bundle.json', { cache: 'no-store' }).then(function (r) { return r.json(); }),
      api('/activity').catch(function () { return S.act; })
    ]).then(function (pair) {
      var b0 = pair[0]; var sig = JSON.stringify([Object.keys(b0.answers || {}).length, (b0.pending || []).length, (b0.tickets || []).map(function (t) { return t.id + t.status; }), (b0.messages || []).length, (b0.reviews || []).length, b0.level, JSON.stringify(pair[1] || {}).length]);
      if (sig === lastSig) return;
      lastSig = sig; S.bundle = pair[0]; if (pair[1]) S.act = pair[1]; render();
    }).catch(function () {});
  }
  setInterval(refresh, 10000);

  // ---- boot ---------------------------------------------------------------
  S.tab = store('desk_tab') || 'today';
  S.ticket = store('desk_ticket');
  fetch('/desk/bundle.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (b) {
    S.bundle = b; render();
    return api('/activity').then(function (a) { S.act = a; S.apiOk = true; render(); })
      .catch(function (err) { S.apiOk = false; S.apiErr = err.message; render(); });
  }).catch(function (err) {
    view.innerHTML = '<h1>Desk unavailable</h1><p class="bad">Could not load bundle.json: ' + esc(err.message) + '. Run <code>boss desk</code> in a terminal.</p>';
  });
})();
"""
