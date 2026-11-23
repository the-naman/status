# status

A small, public status page for my websites: **https://the-naman.github.io/status/**

It answers one question for anyone: *is the site up right now, and has it been up lately?*
It runs entirely on GitHub (Actions + Pages). No server, no secrets.

## How it works

```
every 15 min  ──►  GitHub Actions (check.yml)  ──►  check.py  ──►  data/*.json  ──►  index.html (GitHub Pages)
                         commits data/ only when something changed
```

| Part | What it does |
|---|---|
| `sites.json` | The public, login-free sites that are checked (HTTPS addresses only) |
| `check.py` | Fetches each site; a site counts as **down only after two failed checks 20 seconds apart**, so one network blip is not an outage |
| `data/state.json` | Current state of every site |
| `data/incidents.json` | Every outage with start and end time |
| `data/daily.json` | Uptime per day |
| `index.html` | The page: banner (all up / something down), one card per site, daily uptime bars. Light and dark theme, strict Content-Security-Policy, no images or trackers |
| `test_check.py` | Unit tests for `check.py` |

`data/` is committed only when something changes (and once a day for the daily uptime),
so **the git history of `data/` is the incident log**.

## Workflows

| Workflow | When | What |
|---|---|---|
| `Status check` (`check.yml`) | 07, 22, 37 and 52 minutes past every hour | Runs `check.py`, commits `data/` if it changed |
| `CI` (`ci.yml`) | Every push (except `data/`) | Runs the tests and checks that `sites.json` is valid and HTTPS-only |

Both run on `ubuntu-24.04` with the least permissions they need; actions are pinned by commit hash.

> GitHub runs scheduled workflows on a best-effort basis, so on free accounts a check can arrive late.
> Faster checks run elsewhere (an external uptime monitor every 5 minutes).

## Add or remove a site

1. Edit `sites.json` (public HTTPS address only, nothing behind a login).
2. Commit to `main`. CI checks the file; the next status check picks it up.

## Run the checks locally

```bash
python3 -I check.py                       # one check round, writes data/
python3 -E -s -m unittest -v test_check   # tests
```

## Privacy and security

- Public repo: only public site addresses; no secrets, tokens, server names or IP addresses.
- The page loads nothing from third parties and sends no referrer.
- Deeper private checks and alerts live in a separate private repository.
