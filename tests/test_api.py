"""VegeLink test suite — stdlib unittest, no external deps.

Spins up the real ThreadingHTTPServer against a throwaway SQLite DB and drives
it over HTTP, plus pure-unit checks of the domain math. Run:

    python3 -m unittest discover -s tests      (or ./run.sh test)
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

# Point the app at a temp DB BEFORE importing db (DB_PATH is read at import).
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name
os.environ["VEGELINK_ALLOW_RESET"] = "0"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db        # noqa: E402
import seed      # noqa: E402
import server    # noqa: E402
import ussd      # noqa: E402


def _req(method, path, body=None, token=None):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw and resp.headers.get("Content-Type", "").startswith("application/json") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def setUpModule():
    global HTTPD, PORT
    seed.reset()
    HTTPD = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    PORT = HTTPD.server_address[1]
    threading.Thread(target=HTTPD.serve_forever, daemon=True).start()


def tearDownModule():
    HTTPD.shutdown()
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass


def login(phone, pin="1234"):
    code, body = _req("POST", "/api/login", {"phone": phone, "pin": pin})
    return body["accounts"][0]["token"] if code == 200 else None


class DomainMath(unittest.TestCase):
    def test_haversine_guard_and_symmetry(self):
        self.assertEqual(db.haversine_km(None, (1, 1)), 9999.0)
        a, b = db.LOCATIONS["Akumadan"], db.LOCATIONS["Accra"]
        self.assertAlmostEqual(db.haversine_km(a, b), db.haversine_km(b, a))
        self.assertGreater(db.haversine_km(a, b), 100)

    def test_urgency_boundaries(self):
        import time as _t
        now = int(_t.time())
        fresh = db.urgency_score("Tomatoes", now)            # just harvested
        spoiled = db.urgency_score("Tomatoes", now - 200 * 3600)  # past 96h life
        self.assertLess(fresh, 0.2)
        self.assertEqual(spoiled, 1.0)

    def test_pin_roundtrip(self):
        h, s = db.make_pin("4821")
        self.assertTrue(db.verify_pin("4821", h, s))
        self.assertFalse(db.verify_pin("0000", h, s))


class AuthAndListings(unittest.TestCase):
    def test_register_login_and_listing_flow(self):
        code, _ = _req("POST", "/api/farmers",
                       {"name": "Test Farmer", "phone": "0245550001", "pin": "9999",
                        "location": "Akumadan"})
        self.assertEqual(code, 201)
        tok = login("0245550001", "9999")
        self.assertIsNotNone(tok)
        code, body = _req("POST", "/api/listings",
                          {"crop": "Tomatoes", "quantity": 10, "price": 50,
                           "location": "Akumadan"}, token=tok)
        self.assertEqual(code, 201)
        # appears in the public marketplace
        code, items = _req("GET", "/api/listings?location=Akumadan")
        self.assertTrue(any(i["crop"] == "Tomatoes" for i in items))

    def test_listing_requires_auth(self):
        code, _ = _req("POST", "/api/listings",
                       {"crop": "Okra", "quantity": 5, "price": 20, "location": "Offinso"})
        self.assertEqual(code, 401)

    def test_listing_rejects_unknown_crop(self):
        tok = login("0241000001")  # seeded farmer
        code, body = _req("POST", "/api/listings",
                          {"crop": "<img src=x onerror=alert(1)>", "quantity": 5,
                           "price": 20, "location": "Akumadan"}, token=tok)
        self.assertEqual(code, 400)


class OrdersAndEscrow(unittest.TestCase):
    def test_oversell_guard(self):
        farmer = login("0241000001")
        _, lst = _req("POST", "/api/listings",
                      {"crop": "Pepper" if False else "Peppers", "quantity": 8,
                       "price": 100, "location": "Akumadan"}, token=farmer)
        lid = lst["id"]
        buyer = login("0551000001")
        c1, o1 = _req("POST", "/api/orders",
                      {"listing_id": lid, "quantity": 8, "payment_method": "momo"}, token=buyer)
        self.assertEqual(c1, 201)
        c2, o2 = _req("POST", "/api/orders",
                      {"listing_id": lid, "quantity": 1, "payment_method": "momo"}, token=buyer)
        self.assertEqual(c2, 409)  # stock already claimed; no overselling

    def test_escrow_release_and_ownership(self):
        farmer = login("0241000001")
        _, lst = _req("POST", "/api/listings",
                      {"crop": "Mango", "quantity": 5, "price": 60, "location": "Akumadan"},
                      token=farmer)
        buyer = login("0551000001")
        _, order = _req("POST", "/api/orders",
                        {"listing_id": lst["id"], "quantity": 2, "payment_method": "momo"},
                        token=buyer)
        oid = order["id"]
        # a different buyer cannot confirm this order
        other = login("0551000003")
        code, _ = _req("POST", f"/api/orders/{oid}/confirm-delivery", {}, token=other)
        self.assertEqual(code, 403)
        # rightful buyer drives it to completion -> escrow released
        _req("POST", f"/api/orders/{oid}/status", {"status": "picked_up"}, token=buyer)
        _req("POST", f"/api/orders/{oid}/status", {"status": "delivered"}, token=buyer)
        code, done = _req("POST", f"/api/orders/{oid}/confirm-delivery", {}, token=buyer)
        self.assertEqual(code, 200)
        self.assertEqual(done["payment_status"], "released")
        # rating is idempotent: second rating of same target is rejected
        c1, _ = _req("POST", f"/api/orders/{oid}/rate",
                     {"target": "farmer", "stars": 5}, token=buyer)
        self.assertEqual(c1, 200)
        c2, _ = _req("POST", f"/api/orders/{oid}/rate",
                     {"target": "farmer", "stars": 1}, token=buyer)
        self.assertEqual(c2, 409)


class UssdEngine(unittest.TestCase):
    def test_language_menu_then_listing(self):
        conn = db.connect()
        try:
            first = ussd.handle(conn, "0249999999", "")
            self.assertTrue(first.startswith("CON"))
            self.assertIn("English", first)
            # English (1) -> list (1) -> crop 1 -> qty 50 -> price 5 -> loc 1 -> confirm 1
            end = ussd.handle(conn, "0249999999", "1*1*1*50*5*1*1")
            self.assertTrue(end.startswith("END"))
            self.assertIn("Done", end)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
