---
name: driver-base-server
description: Use when the user asks to spin up, start, serve, or preview the driver-base local web UI, or needs a browser-reachable URL to verify changes to files in web/.
---

# driver-base local server

## Overview

The driver-base web UI is a static site in `web/` (HTML + JS + `drivers.json`). No build step. Serve the directory and open it in a browser.

## How to run

Serve `web/` on port 8000 as a background task:

```bash
cd /Users/jonathancohen/src/driver-base/web && python3 -m http.server 8000
```

Use the Bash tool with `run_in_background: true` so the task keeps serving while you work. Then tell the user the URL.

Verify it responds before reporting success:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/
```

Expect `200`.

## Port already in use

Check first; if 8000 is taken, try 8001, 8002, etc.:

```bash
lsof -iTCP:8000 -sTCP:LISTEN
```

If a previous session's `python3 -m http.server` is already listening on 8000, reuse it — don't start a duplicate.

## Reporting back

Tell the user the URL (e.g. `http://localhost:8000/`) and that it's running in the background. Mention how to stop it (kill the background task) only if asked.

## Don't

- Don't `cd` out of the repo to serve.
- Don't serve the repo root — `drivers.json` lives inside `web/` and the app fetches it relative to `index.html`.
- Don't use a framework/dev-server; the site is plain static files.
