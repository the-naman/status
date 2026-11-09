# Status

Public status page for my sites: **https://the-naman.github.io/status/**

- Checked every 15 minutes by GitHub Actions (`.github/workflows/check.yml` → `check.py`).
- A site is down only after two failed checks 20 seconds apart.
- `data/` is written by the check and committed only when something changes, so the git history is the incident log.
- No secrets live here, and nothing private: only public site addresses.

Deeper private checks (every 6 hours) and alerts run in a separate private repo.
