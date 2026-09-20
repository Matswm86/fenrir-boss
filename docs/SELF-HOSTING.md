# Self-hosting the desk (advanced, optional)

`boss desk` on your own machine is all most people need. This page is for reaching the desk
from a phone or another computer through a server you control.

**Warning: the desk has no login of its own.** `boss desk-serve` is an API that accepts posts
from anyone who can reach it. On a server it must bind to localhost (the default) and sit
behind a reverse proxy that enforces authentication (basic auth at minimum) over TLS. Never
expose its port directly. The rendered site contains your ticket briefs, reviews and inbox,
so the `/board/`, `/desk/` and `/api/` paths all belong behind that login. Only `/` is a
public landing page, and it carries no names.

How the pieces fit:

1. `boss publish` renders `<root>/site` and, with `[web] enabled = true`, rsyncs it over SSH
   to `[web] host` : `[web] webroot`. Your web server serves that folder.
2. On the server, `boss desk-serve` runs the API (port `[desk] port`). Your proxy forwards
   `/api/*` to it with the `/api` prefix stripped. Environment: `BOSS_TOML`, `DESK_DATA`
   (where the outbox is written), `DESK_BUNDLE` (the published `desk/bundle.json`).
   `boss desk-deploy` copies the package and your `boss.toml` to `[desk] remote_app` and
   restarts a user unit named `fenrir-boss-desk.service`, which you create.
3. The server never calls a model and never answers. Your own machine's `boss tick` pulls the
   outbox over rsync, answers with the same model and memory as reviews, and publishes the
   answers back. One voice, and no API keys on the server.

```toml
[web]
enabled = true
host = "user@your-server"
webroot = "/var/www/your-site"
url = "https://desk.example.org"

[desk]
enabled = true
port = 8110
remote_app = "services/fenrir-boss/app"
remote_data = "services/fenrir-boss/data"
```

Home-directory paths are folded to `~` before anything is rendered. Check the published
`bundle.json` yourself before you rely on that.
