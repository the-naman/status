"""Tests for check.py with a local fake web server. No network."""
import datetime as dt
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import check

T0 = dt.datetime(2026, 11, 9, 6, 0, tzinfo=dt.timezone.utc)          # 11:30 IST


class Fake:
    def __init__(self):
        self.code, self.health = 200, {"ok": True}
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/api/health":
                    body = me.health if isinstance(me.health, bytes) else json.dumps(me.health).encode()
                    code = 200
                else:
                    body, code = b"<html>ok</html>", me.code
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.f = Fake()
        self.d = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.d, "data"))
        with open(os.path.join(self.d, "sites.json"), "w") as fh:
            json.dump({"sites": [{"id": "a", "name": "A", "url": self.f.url + "/", "health": self.f.url + "/api/health"},
                                 {"id": "b", "name": "B", "url": self.f.url + "/"}]}, fh)
        self.p = [mock.patch.object(check, "HERE", self.d), mock.patch.object(check, "DATA", os.path.join(self.d, "data"))]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.f.close()
        shutil.rmtree(self.d)

    def run_at(self, t):
        with mock.patch("builtins.print"):
            return check.run(now=t, sleep=lambda s: None)

    def data(self, name):
        with open(os.path.join(self.d, "data", name)) as fh:
            return json.load(fh)

    def test_removed_site_closes_its_outage(self):
        self.f.code = 500
        self.run_at(T0)
        self.assertIsNone(self.data("incidents.json")[0]["end"])
        with open(os.path.join(self.d, "sites.json"), "w") as fh:
            json.dump({"sites": []}, fh)
        self.run_at(T0 + dt.timedelta(minutes=15))
        self.assertEqual(self.data("state.json"), {})
        self.assertTrue(all(i["end"] for i in self.data("incidents.json")))

    def test_missing_data_folder_is_created(self):
        shutil.rmtree(os.path.join(self.d, "data"))
        changed, _ = self.run_at(T0)
        self.assertIn("state.json", changed)

    def test_all_up_then_nothing_changes(self):
        changed, _ = self.run_at(T0)
        self.assertIn("state.json", changed)
        self.assertEqual(self.data("state.json")["a"]["status"], "up")
        changed, _ = self.run_at(T0 + dt.timedelta(minutes=15))
        self.assertEqual(changed, [])                                   # no commit when nothing changed

    def test_outage_opens_and_closes_one_incident(self):
        self.run_at(T0)
        self.f.health = {"ok": False}
        changed, lines = self.run_at(T0 + dt.timedelta(minutes=15))
        self.assertIn("incidents.json", changed)
        inc = self.data("incidents.json")
        self.assertEqual(len(inc), 1)
        self.assertEqual((inc[0]["site"], inc[0]["reason"], inc[0]["end"]), ("a", "health not ok", None))
        self.assertEqual(self.data("state.json")["b"]["status"], "up")     # B has no health URL, still up
        self.run_at(T0 + dt.timedelta(minutes=30))                          # still down: no second incident
        self.assertEqual(len(self.data("incidents.json")), 1)
        self.f.health = {"ok": True}
        self.run_at(T0 + dt.timedelta(minutes=45))
        inc = self.data("incidents.json")
        self.assertEqual(inc[0]["end"], "2026-11-09T06:45:00Z")
        self.assertEqual(self.data("state.json")["a"]["status"], "up")

    def test_http_error_and_non_json_health(self):
        self.f.code = 502
        self.assertEqual(check.check({"url": self.f.url + "/"}, sleep=lambda s: None), (False, "HTTP 502"))
        self.f.code, self.f.health = 200, b"<html>"
        self.assertEqual(check.check({"url": self.f.url + "/", "health": self.f.url + "/api/health"}, sleep=lambda s: None),
                         (False, "health not ok"))
        self.assertEqual(check.check({"url": "http://127.0.0.1:1/"}, sleep=lambda s: None)[0], False)

    def test_one_blip_is_not_an_outage(self):
        calls = []

        def flaky(site):
            calls.append(1)
            return (True, "") if len(calls) > 1 else (False, "timeout")
        with mock.patch.object(check, "probe", flaky):
            self.assertEqual(check.check({}, sleep=lambda s: None), (True, ""))

    def test_daily_uptime_from_incidents(self):
        day = dt.date(2026, 11, 8)
        start = dt.datetime(2026, 11, 8, 0, 0, tzinfo=check.IST)
        inc = [{"site": "a", "start": check.iso(start + dt.timedelta(hours=1)), "end": check.iso(start + dt.timedelta(hours=1, minutes=36))}]
        self.assertEqual(check.daily_uptime(inc, "a", day, T0), 97.5)            # 36 of 1440 minutes down
        self.assertEqual(check.daily_uptime(inc, "b", day, T0), 100.0)

    def test_reasons_never_hold_addresses(self):
        self.f.code = 503
        self.run_at(T0)
        text = json.dumps(self.data("incidents.json"))
        self.assertNotIn("127.0.0.1", text)

    def test_page_has_no_external_resources(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(check.__file__)), "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link", html)
        self.assertNotIn("innerHTML", html)                                    # text only, no HTML injection
        self.assertIn("Content-Security-Policy", html)


if __name__ == "__main__":
    unittest.main()
