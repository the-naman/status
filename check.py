"""Public status checks (Automation M4, layer 2). Runs every 15 minutes in this PUBLIC repo; no secrets anywhere.

    python3 -I check.py            check every site in sites.json, update data/*.json only when something changed

A site is DOWN only after two failed tries 20 s apart (one network blip is not an outage).
  data/state.json      current state per site (up/down, since when)
  data/incidents.json  every outage: start, end (null while ongoing), short reason. Last 200 kept.
  data/daily.json      uptime % per site per day (IST), worked out from the incidents. Last 90 days kept.
Reasons are short and safe ("HTTP 502", "timeout", "health not ok") - never addresses or response bodies.
"""
import datetime as dt
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UA = "status-check (github.com/the-naman/status)"
RETRY_WAIT = 20
KEEP_DAYS, KEEP_INCIDENTS = 90, 200


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(200_000)


def probe(site):
    """(ok, reason). Never raises."""
    try:
        st, _ = fetch(site["url"])
        if st != 200:
            return False, f"HTTP {st}"
        if site.get("health"):
            st, body = fetch(site["health"])
            try:
                ok = json.loads(body).get("ok") is True
            except (ValueError, AttributeError):
                ok = False
            if not ok:
                return False, "health not ok"
        return True, ""
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (socket.timeout, TimeoutError):
        return False, "timeout"
    except ssl.SSLError:
        return False, "TLS error"
    except urllib.error.URLError as e:
        return False, "timeout" if isinstance(e.reason, (socket.timeout, TimeoutError)) else "no connection"
    except Exception as e:                       # noqa: BLE001
        return False, type(e).__name__


def check(site, sleep=time.sleep):
    ok, why = probe(site)
    if ok:
        return True, ""
    sleep(RETRY_WAIT)
    return probe(site)


def load(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)              # a fresh clone may not have data/ yet
    path = os.path.join(DATA, name)
    text = json.dumps(obj, indent=1, sort_keys=True) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def daily_uptime(incidents, site_id, day, now):
    """Uptime % of one IST day, from the incidents (an open incident counts until now)."""
    start = dt.datetime.combine(day, dt.time(0), IST)
    end = min(start + dt.timedelta(days=1), now)
    if end <= start:
        return None
    down = 0.0
    for inc in incidents:
        if inc["site"] != site_id:
            continue
        a = max(parse(inc["start"]), start)
        b = min(parse(inc["end"]) if inc.get("end") else now, end)
        if b > a:
            down += (b - a).total_seconds()
    return round(100 * (1 - down / (end - start).total_seconds()), 2)


def run(now=None, sleep=time.sleep):
    now = now or dt.datetime.now(dt.timezone.utc)
    with open(os.path.join(HERE, "sites.json"), encoding="utf-8") as f:
        sites = json.load(f)["sites"]
    state, incidents, daily = load("state.json", {}), load("incidents.json", []), load("daily.json", {})
    lines = []
    for s in sites:
        ok, why = check(s, sleep)
        cur = state.get(s["id"], {})
        was_up = cur.get("status", "up") == "up"
        if ok and not was_up:
            for inc in incidents:
                if inc["site"] == s["id"] and not inc.get("end"):
                    inc["end"] = iso(now)
            state[s["id"]] = {"name": s["name"], "status": "up", "since": iso(now)}
            lines.append(f"{s['name']}: back up")
        elif not ok and was_up:
            incidents.append({"site": s["id"], "name": s["name"], "start": iso(now), "end": None, "reason": why})
            state[s["id"]] = {"name": s["name"], "status": "down", "since": iso(now), "reason": why}
            lines.append(f"{s['name']}: DOWN ({why})")
        else:
            if s["id"] not in state:
                state[s["id"]] = {"name": s["name"], "status": "up" if ok else "down", "since": iso(now)}
            state[s["id"]]["name"] = s["name"]
            lines.append(f"{s['name']}: {'up' if ok else 'still down (' + why + ')'}")
    for gone in set(state) - {s["id"] for s in sites}:
        del state[gone]
    incidents = incidents[-KEEP_INCIDENTS:]
    today = now.astimezone(IST).date()
    for back in (1, 0):                          # yesterday (final) and today (so far)
        day = today - dt.timedelta(days=back)
        daily[day.isoformat()] = {s["id"]: daily_uptime(incidents, s["id"], day, now) for s in sites}
    for d in sorted(daily)[:-KEEP_DAYS]:
        del daily[d]
    changed = [n for n, o in (("state.json", state), ("incidents.json", incidents)) if save(n, o)]
    # daily.json changes every run (today's %), so save it only with a state change or once a day (new day key)
    old_daily = load("daily.json", {})
    if changed or today.isoformat() not in old_daily or old_daily.get((today - dt.timedelta(days=1)).isoformat()) != daily[(today - dt.timedelta(days=1)).isoformat()]:
        if save("daily.json", daily):
            changed.append("daily.json")
    for l in lines:
        print(l)
    print("changed: " + (", ".join(changed) or "nothing"))
    return changed, lines


if __name__ == "__main__":
    run()
    sys.exit(0)
