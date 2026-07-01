"""VegeLink server — stdlib HTTP server (no external deps).

  python3 server.py            # serves http://localhost:8000
Routes:
  /                      -> SPA (static/index.html)
  /api/*                 -> JSON REST API
  /api/ussd              -> Africa's Talking compatible USSD endpoint (text/plain)
"""
import json
import os
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import ussd
import seed

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
PORT = int(os.environ.get("PORT", "8000"))

# --- in-memory login throttle (per phone): N failures within WINDOW -> lockout ---
_LOGIN_FAILS = {}
_LOGIN_MAX = 5
_LOGIN_WINDOW = 60  # seconds


def _login_blocked(phone):
    rec = _LOGIN_FAILS.get(phone)
    if not rec:
        return False
    count, first = rec
    if time.time() - first > _LOGIN_WINDOW:
        _LOGIN_FAILS.pop(phone, None)
        return False
    return count >= _LOGIN_MAX


def _login_fail(phone):
    count, first = _LOGIN_FAILS.get(phone, (0, time.time()))
    if time.time() - first > _LOGIN_WINDOW:
        count, first = 0, time.time()
    _LOGIN_FAILS[phone] = (count + 1, first)


def _login_reset(phone):
    _LOGIN_FAILS.pop(phone, None)


# ----------------------------- serializers -----------------------------

_SECRET_COLS = ("pin_hash", "pin_salt")


def _safe(row, public=False):
    """Row -> dict with credential columns stripped (never sent to clients).
    With public=True, also drop phone (PII) for unauthenticated directories."""
    drop = _SECRET_COLS + (("phone",) if public else ())
    return {k: row[k] for k in row.keys() if k not in drop}


def listing_dict(conn, r, buyer_location="Accra"):
    farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (r["farmer_id"],)).fetchone()
    score, urg, dist = db.smart_score(r, buyer_location)
    label, level = db.freshness_label(r["crop"], r["harvested_at"])
    return {
        "id": r["id"], "crop": r["crop"], "image": r["image"],
        "quantity": r["quantity"], "unit": r["unit"], "price": r["price"],
        "location": r["location"], "status": r["status"],
        "farmer": {"id": farmer["id"], "name": farmer["name"],
                    "verified": bool(farmer["verified"]),
                    "rating": farmer["rating"], "rating_count": farmer["rating_count"]},
        "lat": r["location"] and (farmer["lat"] if farmer["lat"] is not None
                                  else (db.LOCATIONS.get(r["location"]) or (None, None))[0]),
        "lng": (farmer["lng"] if farmer["lng"] is not None
                else (db.LOCATIONS.get(r["location"]) or (None, None))[1]),
        "hours_remaining": db.hours_remaining(r["crop"], r["harvested_at"]),
        "freshness": label, "freshness_level": level,
        "urgency": urg, "distance_km": dist, "smart_score": score,
    }


def order_dict(conn, r):
    listing = conn.execute("SELECT * FROM listings WHERE id=?", (r["listing_id"],)).fetchone()
    buyer = conn.execute("SELECT * FROM buyers WHERE id=?", (r["buyer_id"],)).fetchone()
    farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (r["farmer_id"],)).fetchone()
    transport = None
    if r["transport_id"]:
        t = conn.execute("SELECT * FROM transport WHERE id=?", (r["transport_id"],)).fetchone()
        if t:
            transport = {"id": t["id"], "name": t["name"], "vehicle": t["vehicle"]}
    return {
        "id": r["id"], "crop": listing["crop"] if listing else "?",
        "image": listing["image"] if listing else "",
        "quantity": r["quantity"], "unit_price": r["unit_price"],
        "produce_total": r["produce_total"], "transport_cost": r["transport_cost"],
        "distance_km": r["distance_km"], "eta_minutes": r["eta_minutes"],
        "transport_status": r["transport_status"], "pickup_at": r["pickup_at"],
        "payment_ref": r["payment_ref"],
        "total": r["total"], "payment_status": r["payment_status"], "status": r["status"],
        "payment_method": r["payment_method"],
        "payment_label": db.PAYMENT_LABELS.get(r["payment_method"], "Mobile Money"),
        "buyer": {"id": buyer["id"], "name": buyer["name"], "location": buyer["location"]} if buyer else None,
        "farmer": {"id": farmer["id"], "name": farmer["name"], "location": farmer["location"]} if farmer else None,
        "transport": transport,
        "buyer_rated": bool(r["buyer_rated"]), "farmer_rated": bool(r["farmer_rated"]),
        "transport_rated": bool(r["transport_rated"]),
        "created_at": r["created_at"],
    }


# ----------------------------- request handler -----------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet console
        pass

    # --- helpers ---
    def _security_headers(self):
        # CSP with script-src 'self' (no unsafe-inline) blocks injected inline
        # scripts AND on*-attribute handlers — defense-in-depth against XSS.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, code=200):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            return json.loads(raw or b"{}")
        # form-urlencoded (Africa's Talking)
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}

    def _serve_static(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        fp = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        # trailing-separator guard so a sibling dir prefixing STATIC_DIR can't pass
        if not (fp == STATIC_DIR or fp.startswith(STATIC_DIR + os.sep)) or not os.path.isfile(fp):
            self._send_text("Not found", 404)
            return
        ctype = ("text/html" if fp.endswith(".html") else
                 "application/javascript" if fp.endswith(".js") else
                 "text/css" if fp.endswith(".css") else "text/plain")
        with open(fp, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    # --- GET ---
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            return self._serve_static(path)
        qs = urllib.parse.parse_qs(parsed.query)
        conn = db.connect()
        try:
            if path == "/api/health":
                return self._send_json({"ok": True, "time": int(time.time())})

            if path == "/api/farmers":
                if not self._require(conn):
                    return
                rows = conn.execute("SELECT * FROM farmers ORDER BY id").fetchall()
                return self._send_json([_safe(r) for r in rows])

            if path == "/api/buyers":
                if not self._require(conn):
                    return
                rows = conn.execute("SELECT * FROM buyers ORDER BY id").fetchall()
                return self._send_json([_safe(r) for r in rows])

            if path == "/api/transport":
                # Public provider directory — name/vehicle/rating only, no phone.
                rows = conn.execute("SELECT * FROM transport ORDER BY rating DESC").fetchall()
                return self._send_json([_safe(r, public=True) for r in rows])

            if path == "/api/listings":
                crop = qs.get("crop", [None])[0]
                maxprice = qs.get("maxprice", [None])[0]
                minqty = qs.get("minqty", [None])[0]
                loc = qs.get("location", [None])[0]
                farmer_id = qs.get("farmer_id", [None])[0]
                sort = qs.get("sort", ["smart"])[0]
                buyer_loc = qs.get("buyer_location", ["Accra"])[0]
                # farmers managing their own stock want every status; buyers only active.
                # Anything beyond active listings requires the owning farmer to be logged in.
                statuses = qs.get("status", ["active"])[0]
                if statuses != "active":
                    sess = self._require(conn, ["farmer"])
                    if not sess:
                        return
                    if not farmer_id or int(farmer_id) != sess["account_id"]:
                        return self._send_json({"error": "can only view your own listings"}, 403)
                sql = "SELECT * FROM listings WHERE 1=1"
                args = []
                if statuses != "all":
                    sql += " AND status=?"; args.append(statuses)
                if crop:
                    sql += " AND crop=?"; args.append(crop)
                if loc:
                    sql += " AND location=?"; args.append(loc)
                if farmer_id:
                    sql += " AND farmer_id=?"; args.append(int(farmer_id))
                if maxprice:
                    sql += " AND price<=?"; args.append(float(maxprice))
                if minqty:
                    sql += " AND quantity>=?"; args.append(int(minqty))
                rows = conn.execute(sql, args).fetchall()
                items = [listing_dict(conn, r, buyer_loc) for r in rows]
                if sort == "smart":
                    items.sort(key=lambda x: x["smart_score"], reverse=True)
                elif sort == "price":
                    items.sort(key=lambda x: x["price"])
                elif sort == "urgency":
                    items.sort(key=lambda x: x["urgency"], reverse=True)
                return self._send_json(items)

            if path.startswith("/api/listings/"):
                lid = int(path.rsplit("/", 1)[1])
                r = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
                if not r:
                    return self._send_json({"error": "not found"}, 404)
                return self._send_json(listing_dict(conn, r, qs.get("buyer_location", ["Accra"])[0]))

            if path == "/api/orders":
                # Callers only ever see orders they are a party to (derived from session).
                sess = self._require(conn)
                if not sess:
                    return
                col = {"farmer": "farmer_id", "transport": "transport_id"}.get(
                    sess["kind"], "buyer_id")
                rows = conn.execute(
                    f"SELECT * FROM orders WHERE {col}=? ORDER BY id DESC",
                    (sess["account_id"],)).fetchall()
                return self._send_json([order_dict(conn, r) for r in rows])

            if path == "/api/notifications":
                # Personal inbox: the caller's own notifications only.
                sess = self._require(conn)
                if not sess:
                    return
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE owner_kind=? AND owner_id=? "
                    "ORDER BY id DESC LIMIT 40", (sess["kind"], sess["account_id"])).fetchall()
                return self._send_json([dict(r) for r in rows])

            if path == "/api/dashboard":
                return self._send_json(self._dashboard(conn))

            if path == "/api/export.csv":
                # CSV of the caller's own orders (analytics/record-keeping).
                sess = self._require(conn)
                if not sess:
                    return
                col = {"farmer": "farmer_id", "transport": "transport_id"}.get(
                    sess["kind"], "buyer_id")
                rows = conn.execute(
                    f"SELECT * FROM orders WHERE {col}=? ORDER BY id", (sess["account_id"],)).fetchall()
                cols = ["id", "created_at", "crop_quantity", "produce_total", "transport_cost",
                        "total", "payment_method", "payment_status", "status"]
                out = [",".join(cols)]
                for o in rows:
                    od = order_dict(conn, o)
                    out.append(",".join(str(x) for x in [
                        od["id"], od["created_at"], f"{od['quantity']} {od['crop']}",
                        od["produce_total"], od["transport_cost"], od["total"],
                        od["payment_method"], od["payment_status"], od["status"]]))
                body = ("\n".join(out)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition", "attachment; filename=vegelink-orders.csv")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/api/meta":
                return self._send_json({
                    "crops": db.CROPS,
                    "locations": list(db.LOCATIONS.keys()),
                    "location_coords": {k: {"lat": v[0], "lng": v[1]} for k, v in db.LOCATIONS.items()},
                    "shelf_life": db.SHELF_LIFE_HOURS,
                    "payment_methods": db.PAYMENT_LABELS,
                })

            if path == "/api/nearby":
                if not self._require(conn):  # exposes contact phones — login required
                    return
                find = qs.get("find", ["buyers"])[0]
                origin = qs.get("origin", ["Akumadan"])[0]
                radius = qs.get("radius", [None])[0]
                radius = float(radius) if radius else None
                return self._send_json(self._nearby(conn, find, origin, radius))

            if path == "/api/reviews":
                tk = qs.get("target_kind", [None])[0]
                tid = qs.get("target_id", [None])[0]
                sql = "SELECT * FROM reviews WHERE 1=1"; args = []
                if tk:
                    sql += " AND target_kind=?"; args.append(tk)
                if tid:
                    sql += " AND target_id=?"; args.append(int(tid))
                sql += " ORDER BY id DESC LIMIT 50"
                rows = conn.execute(sql, args).fetchall()
                return self._send_json([dict(r) for r in rows])

            if path == "/api/messages":
                # The caller (from session) sees only their own threads/messages.
                sess = self._require(conn)
                if not sess:
                    return
                kind, uid = sess["kind"], sess["account_id"]
                thread = qs.get("thread", [None])[0]
                if thread:
                    rows = conn.execute(
                        "SELECT * FROM messages WHERE thread=? ORDER BY id", (thread,)).fetchall()
                    # only a participant may read the thread
                    if rows and not any(
                            (m["from_kind"] == kind and m["from_id"] == uid) or
                            (m["to_kind"] == kind and m["to_id"] == uid) for m in rows):
                        return self._send_json({"error": "not your thread"}, 403)
                    conn.execute(
                        "UPDATE messages SET read=1 WHERE thread=? AND to_kind=? AND to_id=?",
                        (thread, kind, uid))
                    conn.commit()
                    return self._send_json([dict(r) for r in rows])
                rows = conn.execute(
                    "SELECT * FROM messages WHERE (from_kind=? AND from_id=?) "
                    "OR (to_kind=? AND to_id=?) ORDER BY id",
                    (kind, uid, kind, uid)).fetchall()
                return self._send_json(self._thread_summaries(rows, kind, uid))
                return self._send_json([])

            return self._send_json({"error": "unknown route"}, 404)
        finally:
            conn.close()

    # --- POST ---
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        conn = db.connect()
        try:
            # USSD endpoint (text/plain CON/END)
            if path == "/api/ussd":
                data = self._read_body()
                phone = data.get("phoneNumber") or data.get("phone") or "0240000000"
                text = data.get("text", "")
                resp = ussd.handle(conn, phone, text)
                return self._send_text(resp)

            data = self._read_body()
            now = int(time.time())

            if path == "/api/login":
                return self._login(conn, data)

            if path == "/api/logout":
                db.delete_session(conn, self._token()); conn.commit()
                return self._send_json({"ok": True})

            if path == "/api/farmers":
                err = self._valid_reg(data)
                if err:
                    return self._send_json({"error": err}, 400)
                ph, ps = self._pin_cols(data)
                lat, lng = self._gps(data, data["location"])
                # NB: verification is granted by admins, never self-asserted at signup.
                cur = conn.execute(
                    "INSERT INTO farmers (name,phone,location,lat,lng,pin_hash,pin_salt,"
                    "verified,created_at) VALUES (?,?,?,?,?,?,?,0,?)",
                    (data["name"].strip(), data["phone"].strip(), data["location"], lat, lng, ph, ps, now))
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path == "/api/buyers":
                err = self._valid_reg(data)
                if err:
                    return self._send_json({"error": err}, 400)
                role = data.get("role", "buyer")  # buyer | retailer
                ph, ps = self._pin_cols(data)
                lat, lng = self._gps(data, data["location"])
                cur = conn.execute(
                    "INSERT INTO buyers (name,phone,type,role,location,lat,lng,pin_hash,"
                    "pin_salt,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (data["name"].strip(), data["phone"].strip(),
                     data.get("type", "retailer" if role == "retailer" else "household"),
                     role, data["location"], lat, lng, ph, ps, now))
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path == "/api/transport":
                err = self._valid_reg(data)
                if err:
                    return self._send_json({"error": err}, 400)
                ph, ps = self._pin_cols(data)
                lat, lng = self._gps(data, data["location"])
                cur = conn.execute(
                    "INSERT INTO transport (name,phone,vehicle,capacity_crates,location,lat,lng,"
                    "pin_hash,pin_salt,rate_per_km,available,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                    (data["name"].strip(), data["phone"].strip(), data.get("vehicle", "Pickup truck"),
                     int(data.get("capacity_crates", 80)), data["location"], lat, lng, ph, ps,
                     float(data.get("rate_per_km", 2.5)), now))
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path == "/api/listings":
                sess = self._require(conn, ["farmer"])
                if not sess:
                    return
                # Allow-list crop & location (no free text reaches storage/render),
                # and sanity-check the economics.
                if data.get("crop") not in db.CROPS:
                    return self._send_json({"error": "unknown crop"}, 400)
                if data.get("location") not in db.LOCATIONS:
                    return self._send_json({"error": "unknown location"}, 400)
                qty = int(data["quantity"]); price = float(data["price"])
                if qty <= 0 or price <= 0:
                    return self._send_json({"error": "quantity and price must be positive"}, 400)
                fid = sess["account_id"]  # listing always belongs to the caller
                img = self._clean_image(data.get("image")) or db.CROP_EMOJI.get(data.get("crop"), "🧺")
                cur = conn.execute(
                    "INSERT INTO listings (farmer_id,crop,quantity,unit,price,location,"
                    "harvested_at,image,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'active', ?)",
                    (fid, data["crop"], qty, "crate", price, data["location"],
                     now - int(data.get("harvested_hours_ago", 6)) * 3600, img, now))
                farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (fid,)).fetchone()
                db.log_notification(conn, "SMS", farmer["phone"],
                    f"VegeLink: Your {data['quantity']} crates of {data['crop']} are LIVE.",
                    "farmer", fid)
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path.startswith("/api/listings/") and path.endswith("/update"):
                sess = self._require(conn, ["farmer"])
                if not sess:
                    return
                lid = int(path.split("/")[3])
                return self._update_listing(conn, sess, lid, data, now)

            if path == "/api/orders":
                sess = self._require(conn, ["buyer", "retailer"])
                if not sess:
                    return
                return self._create_order(conn, sess, data, now)

            if path.startswith("/api/orders/") and path.endswith("/status"):
                sess = self._require(conn)
                if not sess:
                    return
                oid = int(path.split("/")[3])
                return self._update_status(conn, sess, oid, data.get("status"), now)

            if path.startswith("/api/orders/") and path.endswith("/transport-response"):
                sess = self._require(conn, ["transport"])
                if not sess:
                    return
                oid = int(path.split("/")[3])
                return self._transport_response(conn, sess, oid, data, now)

            if path.startswith("/api/orders/") and path.endswith("/confirm-delivery"):
                sess = self._require(conn, ["buyer", "retailer"])
                if not sess:
                    return
                oid = int(path.split("/")[3])
                return self._confirm_delivery(conn, sess, oid, now)

            if path.startswith("/api/orders/") and path.endswith("/rate"):
                sess = self._require(conn)
                if not sess:
                    return
                oid = int(path.split("/")[3])
                return self._rate(conn, sess, oid, data)

            if path == "/api/messages":
                sess = self._require(conn)
                if not sess:
                    return
                return self._send_message(conn, sess, data, now)

            if path == "/api/seed/reset":
                # Destructive: disabled unless explicitly allowed via env.
                if os.environ.get("VEGELINK_ALLOW_RESET") != "1":
                    return self._send_json({"error": "reset disabled"}, 403)
                conn.close()
                seed.reset()
                return self._send_json({"ok": True})

            return self._send_json({"error": "unknown route"}, 404)
        except KeyError as e:  # missing required field
            return self._send_json({"error": f"missing field: {e}"}, 400)
        except (ValueError, TypeError):
            return self._send_json({"error": "invalid input"}, 400)
        except Exception:  # don't leak internals to the client
            import traceback; traceback.print_exc()
            return self._send_json({"error": "server error"}, 500)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ----------------------- business logic -----------------------

    def _create_order(self, conn, sess, data, now):
        listing = conn.execute("SELECT * FROM listings WHERE id=?",
                                (int(data["listing_id"]),)).fetchone()
        if not listing:
            return self._send_json({"error": "listing not found"}, 404)
        # Buyer is the authenticated caller — never trust a body-supplied id.
        buyer = conn.execute("SELECT * FROM buyers WHERE id=?", (sess["account_id"],)).fetchone()
        if not buyer:
            return self._send_json({"error": "buyer not found"}, 404)
        qty = int(data["quantity"])
        if qty <= 0:
            return self._send_json({"error": "invalid quantity"}, 400)

        produce_total = round(qty * listing["price"], 2)

        # --- Auto-match transport: available, enough capacity, nearest+cheap+rated ---
        chosen = self._match_transport(conn, listing, buyer, qty)
        t_cost = t_dist = 0.0
        eta = 0
        transport_id = None
        if chosen:
            t_dist, t_cost, eta = db.estimate_transport(
                listing["location"], buyer["location"], chosen["rate_per_km"])
            transport_id = chosen["id"]

        total = round(produce_total + t_cost, 2)

        # --- Payment method: COD is collected on delivery (no escrow);
        #     momo / bank / card are held in escrow until delivery confirmed.
        #     Routed through the pluggable gateway seam (db.initiate_payment). ---
        method = data.get("payment_method", "momo")
        if method not in db.PAYMENT_LABELS:
            method = "momo"
        method_label = db.PAYMENT_LABELS[method]

        # --- Atomically claim stock: only succeeds if enough is still available.
        #     Guards against two concurrent orders overselling the same listing. ---
        conn.execute("BEGIN IMMEDIATE")
        claimed = conn.execute(
            "UPDATE listings SET quantity = quantity - ?, "
            "status = CASE WHEN quantity - ? <= 0 THEN 'sold_out' ELSE status END "
            "WHERE id=? AND status='active' AND quantity >= ?",
            (qty, qty, listing["id"], qty))
        if claimed.rowcount != 1:
            conn.rollback()
            return self._send_json({"error": "not enough stock available"}, 409)

        pay_ref, pay_status = db.initiate_payment(method, total, buyer["phone"])
        t_status = "proposed" if transport_id else "none"
        cur = conn.execute(
            "INSERT INTO orders (listing_id,buyer_id,farmer_id,quantity,unit_price,produce_total,"
            "transport_id,transport_cost,distance_km,eta_minutes,transport_status,total,payment_method,"
            "payment_status,payment_ref,status,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (listing["id"], buyer["id"], listing["farmer_id"], qty, listing["price"], produce_total,
             transport_id, t_cost, t_dist, eta, t_status, total, method, pay_status, pay_ref,
             "matched" if transport_id else "placed", now))
        order_id = cur.lastrowid

        # notifications: payment (buyer) + farmer + transport
        farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (listing["farmer_id"],)).fetchone()
        if method == "cod":
            db.log_notification(conn, "app", buyer["name"],
                f"Cash on Delivery selected — pay GHS{total:.2f} to the driver on arrival.",
                buyer["role"] or "buyer", buyer["id"])
            secured = f"Buyer will pay GHS{total:.0f} CASH on delivery."
        else:
            db.log_notification(conn, "app", buyer["name"],
                f"{method_label} payment GHS{total:.2f} HELD safely — released to the farmer only when you confirm delivery.",
                buyer["role"] or "buyer", buyer["id"])
            secured = f"Payment ({method_label}) secured in escrow."
        db.log_notification(conn, "SMS", farmer["phone"],
            f"VegeLink: NEW ORDER! {qty} crates {listing['crop']} from {buyer['name']}. "
            f"{secured} Prepare for pickup.", "farmer", farmer["id"])
        if chosen:
            db.log_notification(conn, "SMS", chosen["phone"],
                f"VegeLink: NEW pickup job — {qty} crates from {listing['location']} to "
                f"{buyer['location']} (~{t_dist:.0f}km, GHS{t_cost:.0f}). ETA {eta}min. "
                f"Open VegeLink to ACCEPT or DECLINE.", "transport", chosen["id"])
        conn.commit()
        return self._send_json(order_dict(conn, conn.execute(
            "SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()), 201)

    def _match_transport(self, conn, listing, buyer, qty, exclude_id=None):
        """Pick the best available vehicle for a pickup→drop leg: enough capacity,
        vehicle suitable for the distance, ranked by (delivery cost + how far the
        vehicle must travel to reach the pickup) minus a rating bonus — so a
        nearer, cheaper, better-rated provider wins."""
        cands = conn.execute(
            "SELECT * FROM transport WHERE available=1 AND capacity_crates>=?"
            + (" AND id<>?" if exclude_id else ""),
            ((qty, exclude_id) if exclude_id else (qty,))).fetchall()
        if not cands:
            return None
        leg_km = db.haversine_km(db.LOCATIONS.get(listing["location"]),
                                 db.LOCATIONS.get(buyer["location"]))
        suitable = [t for t in cands
                    if not ("tricycle" in (t["vehicle"] or "").lower() and leg_km > 50)] or cands

        def rank(t):
            _, cost, _ = db.estimate_transport(listing["location"], buyer["location"], t["rate_per_km"])
            # distance the vehicle must travel from its base to the pickup point
            approach = db.haversine_km(db.LOCATIONS.get(t["location"]),
                                       db.LOCATIONS.get(listing["location"]))
            return cost + approach * 0.5 - (t["rating"] or 0) * 5
        return min(suitable, key=rank)

    def _update_status(self, conn, sess, oid, status, now):
        valid = ["placed", "matched", "picked_up", "delivered"]
        if status not in valid:
            return self._send_json({"error": "invalid status"}, 400)
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return self._send_json({"error": "not found"}, 404)
        # Only the order's buyer or its assigned transport provider may advance it.
        if not ((sess["kind"] in ("buyer", "retailer") and sess["account_id"] == order["buyer_id"])
                or (sess["kind"] == "transport" and sess["account_id"] == order["transport_id"])):
            return self._send_json({"error": "not your order"}, 403)
        if order["status"] == status:  # idempotent
            return self._send_json(order_dict(conn, order))
        delivered_at = now if status == "delivered" else order["delivered_at"]
        conn.execute("UPDATE orders SET status=?, delivered_at=? WHERE id=?",
                     (status, delivered_at, oid))
        buyer = conn.execute("SELECT * FROM buyers WHERE id=?", (order["buyer_id"],)).fetchone()
        msg = {"picked_up": "Produce picked up — on the way.",
               "delivered": "Delivered! Please confirm to release payment.",
               "matched": "Transport matched and scheduled."}.get(status)
        if msg:
            db.log_notification(conn, "app", buyer["name"], f"Order #{oid}: {msg}",
                                buyer["role"] or "buyer", buyer["id"])
        conn.commit()
        return self._send_json(order_dict(conn, conn.execute(
            "SELECT * FROM orders WHERE id=?", (oid,)).fetchone()))

    def _confirm_delivery(self, conn, sess, oid, now):
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return self._send_json({"error": "not found"}, 404)
        if sess["account_id"] != order["buyer_id"]:
            return self._send_json({"error": "not your order"}, 403)
        if order["status"] == "completed":  # idempotent — don't re-release/re-notify
            return self._send_json(order_dict(conn, order))
        method = order["payment_method"]
        label = db.PAYMENT_LABELS.get(method, "Mobile Money")
        # Confirm the escrowed funds actually cleared before releasing (gateway seam).
        if method != "cod" and order["payment_ref"] and not db.verify_payment(order["payment_ref"]):
            return self._send_json({"error": "payment not cleared"}, 402)
        # COD: cash collected on arrival; others: escrow releases to farmer.
        new_pay = "paid" if method == "cod" else "released"
        conn.execute(
            "UPDATE orders SET status='completed', payment_status=?, delivered_at=? WHERE id=?",
            (new_pay, now, oid))
        farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (order["farmer_id"],)).fetchone()
        if method == "cod":
            sms = (f"VegeLink: Delivery confirmed! GHS{order['produce_total']:.2f} collected "
                   f"in CASH on delivery.")
        else:
            sms = (f"VegeLink: Delivery confirmed! GHS{order['produce_total']:.2f} released to "
                   f"your account via {label}.")
        db.log_notification(conn, "SMS", farmer["phone"], sms, "farmer", farmer["id"])
        conn.commit()
        return self._send_json(order_dict(conn, conn.execute(
            "SELECT * FROM orders WHERE id=?", (oid,)).fetchone()))

    def _rate(self, conn, sess, oid, data):
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return self._send_json({"error": "not found"}, 404)
        # Only a participant in this order may rate, and only a completed one.
        is_party = ((sess["kind"] in ("buyer", "retailer") and sess["account_id"] == order["buyer_id"])
                    or (sess["kind"] == "farmer" and sess["account_id"] == order["farmer_id"])
                    or (sess["kind"] == "transport" and sess["account_id"] == order["transport_id"]))
        if not is_party:
            return self._send_json({"error": "not your order"}, 403)
        if order["status"] != "completed":
            return self._send_json({"error": "can only rate completed orders"}, 400)
        target = data.get("target")  # 'farmer' or 'buyer' or 'transport'
        # You cannot rate your own side of the deal.
        own = {"farmer": sess["kind"] == "farmer",
               "buyer": sess["kind"] in ("buyer", "retailer"),
               "transport": sess["kind"] == "transport"}.get(target)
        if own:
            return self._send_json({"error": "you cannot rate yourself"}, 400)
        try:
            stars = max(1.0, min(5.0, float(data.get("stars", 5))))
        except (TypeError, ValueError):
            return self._send_json({"error": "invalid stars"}, 400)
        flag = {"farmer": "farmer_rated", "buyer": "buyer_rated", "transport": "transport_rated"}.get(target)
        table = {"farmer": ("farmers", order["farmer_id"]),
                 "buyer": ("buyers", order["buyer_id"]),
                 "transport": ("transport", order["transport_id"])}.get(target)
        if not flag or not table or not table[1]:
            return self._send_json({"error": "invalid rate target"}, 400)
        tbl, tid = table
        # Atomic: one rating per target per order; recompute average under a lock.
        conn.execute("BEGIN IMMEDIATE")
        fresh = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if fresh[flag]:
            conn.rollback()
            return self._send_json({"error": "already rated"}, 409)
        row = conn.execute(f"SELECT rating, rating_count FROM {tbl} WHERE id=?", (tid,)).fetchone()
        new_count = row["rating_count"] + 1
        new_rating = round((row["rating"] * row["rating_count"] + stars) / new_count, 2)
        conn.execute(f"UPDATE {tbl} SET rating=?, rating_count=? WHERE id=?",
                     (new_rating, new_count, tid))
        author = conn.execute(f"SELECT name FROM {self.TABLE_FOR[sess['kind']]} WHERE id=?",
                              (sess["account_id"],)).fetchone()
        conn.execute(
            "INSERT INTO reviews (target_kind,target_id,author_kind,author_id,author_name,"
            "order_id,stars,body,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (target, tid, sess["kind"], sess["account_id"],
             author["name"] if author else None, oid, stars,
             (data.get("body") or "").strip()[:600], int(time.time())))
        conn.execute(f"UPDATE orders SET {flag}=1 WHERE id=?", (oid,))
        conn.commit()
        return self._send_json({"ok": True, "rating": new_rating})

    # ----------------------- auth / helpers -----------------------

    TABLE_FOR = {"farmer": "farmers", "buyer": "buyers", "retailer": "buyers", "transport": "transport"}

    def _token(self):
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h[:7].lower() == "bearer " else None

    def _session(self, conn):
        """The session row for the bearer token, or None."""
        return db.get_session(conn, self._token())

    def _actor(self, conn):
        """(session, account_row) for the caller, or (None, None)."""
        sess = self._session(conn)
        if not sess:
            return (None, None)
        tbl = self.TABLE_FOR.get(sess["kind"])
        acct = conn.execute(f"SELECT * FROM {tbl} WHERE id=?", (sess["account_id"],)).fetchone()
        return (sess, acct)

    def _require(self, conn, kinds=None):
        """Return the session if authenticated (and of an allowed kind), else
        send a 401/403 and return None. `kinds` is an optional allow-list."""
        sess = self._session(conn)
        if not sess:
            self._send_json({"error": "login required"}, 401)
            return None
        if kinds and sess["kind"] not in kinds:
            self._send_json({"error": "not allowed for this role"}, 403)
            return None
        return sess

    def _valid_reg(self, data):
        """Validate a registration payload server-side. Returns an error string
        or None if OK. (The client validates too, but never trust the client.)"""
        name = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        pin = str(data.get("pin", "")).strip()
        loc = data.get("location")
        if len(name) < 2:
            return "name is required"
        if not re.fullmatch(r"0\d{9}", phone):
            return "phone must be 10 digits, e.g. 0241234567"
        if not re.fullmatch(r"\d{4,8}", pin):
            return "PIN must be 4–8 digits"
        if loc not in db.LOCATIONS:
            return "unknown location"
        return None

    # Strict base64 image data URL: blocks attribute-breakout payloads that a
    # bare startswith("data:image/") check would let through.
    _IMG_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,[A-Za-z0-9+/]+={0,2}$")

    def _clean_image(self, image):
        """Accept only a bounded, well-formed image data URL; else None."""
        if not image or not isinstance(image, str):
            return None
        if len(image) > 350_000:  # ~250KB binary; client already downscales
            raise ValueError("image too large")
        return image if self._IMG_RE.match(image) else None

    def _pin_cols(self, data):
        """(pin_hash, pin_salt) from a registration payload, or (None, None)."""
        pin = str(data.get("pin", "")).strip()
        if not pin:
            return (None, None)
        return db.make_pin(pin)

    def _gps(self, data, location):
        """Captured GPS if present, else the town centroid as a fallback fix."""
        lat, lng = data.get("lat"), data.get("lng")
        if lat is not None and lng is not None and lat != "" and lng != "":
            try:
                return float(lat), float(lng)
            except (TypeError, ValueError):
                pass
        c = db.LOCATIONS.get(location) or (None, None)
        return c[0], c[1]

    def _public_account(self, row, kind):
        d = {k: row[k] for k in row.keys() if k not in ("pin_hash", "pin_salt")}
        d["kind"] = kind
        return d

    def _login(self, conn, data):
        phone = str(data.get("phone", "")).strip()
        pin = str(data.get("pin", "")).strip()
        if not phone or not pin:
            return self._send_json({"error": "phone and PIN required"}, 400)
        # Rate-limit by phone to stop PIN brute-force (4–8 digit space).
        if _login_blocked(phone):
            return self._send_json({"error": "too many attempts — try again in a minute"}, 429)
        # A phone may exist in several roles (e.g. the demo Lukman accounts);
        # return every matching account whose PIN verifies, tagged by kind.
        matches = []
        for kind, tbl in (("farmer", "farmers"), ("buyer", "buyers"), ("transport", "transport")):
            for row in conn.execute(f"SELECT * FROM {tbl} WHERE phone=?", (phone,)).fetchall():
                if db.verify_pin(pin, row["pin_hash"], row["pin_salt"]):
                    acct = self._public_account(row, "buyer" if tbl == "buyers" else kind)
                    if tbl == "buyers":
                        acct["kind"] = row["role"] or "buyer"
                    matches.append(acct)
        if not matches:
            _login_fail(phone)
            return self._send_json({"error": "invalid phone or PIN"}, 401)
        _login_reset(phone)
        # issue a bearer token per matched account (a phone may hold several roles)
        for acct in matches:
            acct["token"] = db.create_session(conn, acct["kind"], acct["id"])
        conn.commit()
        return self._send_json({"accounts": matches})

    def _update_listing(self, conn, sess, lid, data, now):
        listing = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
        if not listing:
            return self._send_json({"error": "not found"}, 404)
        if listing["farmer_id"] != sess["account_id"]:
            return self._send_json({"error": "not your listing"}, 403)
        fields, args = [], []
        if "quantity" in data:
            q = max(0, int(data["quantity"]))
            fields.append("quantity=?"); args.append(q)
            # keep status coherent with stock unless an explicit status is sent
            if "status" not in data:
                fields.append("status=?"); args.append("sold_out" if q <= 0 else "active")
        if "price" in data:
            price = float(data["price"])
            if price <= 0:
                return self._send_json({"error": "price must be positive"}, 400)
            fields.append("price=?"); args.append(price)
        if "status" in data and data["status"] in ("active", "sold_out", "unavailable"):
            fields.append("status=?"); args.append(data["status"])
        img = self._clean_image(data.get("image"))
        if img:
            fields.append("image=?"); args.append(img)
        if not fields:
            return self._send_json({"error": "nothing to update"}, 400)
        args.append(lid)
        conn.execute(f"UPDATE listings SET {', '.join(fields)} WHERE id=?", args)
        conn.commit()
        r = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
        return self._send_json(listing_dict(conn, r))

    def _transport_response(self, conn, sess, oid, data, now):
        """Transport provider accepts / declines an auto-matched job and can set
        a pickup time. Declining re-matches the next best available vehicle."""
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return self._send_json({"error": "not found"}, 404)
        if order["transport_id"] != sess["account_id"]:
            return self._send_json({"error": "not your job"}, 403)
        action = data.get("action")
        if action == "accept":
            pickup_at = data.get("pickup_at")
            pickup_at = int(pickup_at) if pickup_at else (now + 2 * 3600)
            conn.execute(
                "UPDATE orders SET transport_status='accepted', pickup_at=?, status='matched' WHERE id=?",
                (pickup_at, oid))
            t = conn.execute("SELECT * FROM transport WHERE id=?", (order["transport_id"],)).fetchone()
            buyer = conn.execute("SELECT * FROM buyers WHERE id=?", (order["buyer_id"],)).fetchone()
            farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (order["farmer_id"],)).fetchone()
            when = time.strftime("%a %d %b, %H:%M", time.localtime(pickup_at))
            db.log_notification(conn, "app", buyer["name"],
                f"Order #{oid}: {t['name']} accepted the job. Pickup scheduled {when}.",
                buyer["role"] or "buyer", buyer["id"])
            db.log_notification(conn, "SMS", farmer["phone"],
                f"VegeLink: {t['name']} will pick up your produce on {when}. Please have it ready.",
                "farmer", farmer["id"])
            conn.commit()
            return self._send_json(order_dict(conn, conn.execute(
                "SELECT * FROM orders WHERE id=?", (oid,)).fetchone()))
        if action == "reject":
            # re-match the next best available vehicle, excluding the one that declined
            listing = conn.execute("SELECT * FROM listings WHERE id=?", (order["listing_id"],)).fetchone()
            buyer = conn.execute("SELECT * FROM buyers WHERE id=?", (order["buyer_id"],)).fetchone()
            nxt = self._match_transport(conn, listing, buyer, order["quantity"],
                                        exclude_id=order["transport_id"])
            if nxt:
                d, c, e = db.estimate_transport(listing["location"], buyer["location"], nxt["rate_per_km"])
                conn.execute(
                    "UPDATE orders SET transport_id=?, transport_cost=?, distance_km=?, eta_minutes=?,"
                    " transport_status='proposed', total=?, status='matched' WHERE id=?",
                    (nxt["id"], c, d, e, round(order["produce_total"] + c, 2), oid))
                db.log_notification(conn, "SMS", nxt["phone"],
                    f"VegeLink: NEW pickup job — {order['quantity']} crates from {listing['location']} "
                    f"to {buyer['location']} (~{d:.0f}km, GHS{c:.0f}). Open VegeLink to ACCEPT or DECLINE.",
                    "transport", nxt["id"])
            else:
                conn.execute(
                    "UPDATE orders SET transport_id=NULL, transport_cost=0, transport_status='none',"
                    " total=?, status='placed' WHERE id=?", (order["produce_total"], oid))
                db.log_notification(conn, "app", buyer["name"],
                    f"Order #{oid}: no transport available right now — we'll keep searching.",
                    buyer["role"] or "buyer", buyer["id"])
            conn.commit()
            return self._send_json(order_dict(conn, conn.execute(
                "SELECT * FROM orders WHERE id=?", (oid,)).fetchone()))
        return self._send_json({"error": "action must be accept or reject"}, 400)

    def _send_message(self, conn, sess, data, now):
        # Sender identity comes from the session, never the request body.
        from_kind, from_id = sess["kind"], sess["account_id"]
        if data.get("to_kind") in (None, "") or data.get("to_id") in (None, "") or not str(data.get("body", "")).strip():
            return self._send_json({"error": "to and body required"}, 400)
        to_kind, to_id = data["to_kind"], int(data["to_id"])
        sender = conn.execute(f"SELECT name FROM {self.TABLE_FOR[from_kind]} WHERE id=?", (from_id,)).fetchone()
        to_tbl = self.TABLE_FOR.get(to_kind)
        recipient = conn.execute(f"SELECT name, phone FROM {to_tbl} WHERE id=?", (to_id,)).fetchone() if to_tbl else None
        if not recipient:
            return self._send_json({"error": "recipient not found"}, 404)
        body = str(data["body"]).strip()[:1000]
        order_id = int(data["order_id"]) if data.get("order_id") else None
        thread = db.thread_key(from_kind, from_id, to_kind, to_id, order_id)
        conn.execute(
            "INSERT INTO messages (thread,order_id,listing_id,from_kind,from_id,from_name,"
            "to_kind,to_id,to_name,body,read,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
            (thread, order_id, int(data["listing_id"]) if data.get("listing_id") else None,
             from_kind, from_id, sender["name"] if sender else from_kind,
             to_kind, to_id, recipient["name"], body, now))
        db.log_notification(conn, "app", recipient["name"],
            f"New message from {sender['name'] if sender else from_kind}: {body[:60]}",
            to_kind, to_id)
        conn.commit()
        return self._send_json({"ok": True, "thread": thread}, 201)

    def _thread_summaries(self, rows, kind, uid):
        """Collapse a user's messages into one entry per conversation thread."""
        threads = {}
        for r in rows:
            t = threads.setdefault(r["thread"], {"thread": r["thread"], "messages": 0,
                                                 "unread": 0, "last": None})
            t["messages"] += 1
            # the other party, from this user's perspective
            if r["from_kind"] == kind and r["from_id"] == uid:
                t["other_kind"], t["other_id"], t["other_name"] = r["to_kind"], r["to_id"], r["to_name"]
            else:
                t["other_kind"], t["other_id"], t["other_name"] = r["from_kind"], r["from_id"], r["from_name"]
                if not r["read"]:
                    t["unread"] += 1
            t["order_id"] = r["order_id"]
            t["last"] = {"body": r["body"], "created_at": r["created_at"],
                         "mine": r["from_kind"] == kind and r["from_id"] == uid}
        return sorted(threads.values(),
                      key=lambda x: x["last"]["created_at"] if x["last"] else 0, reverse=True)

    def _nearby(self, conn, find, origin, radius):
        """Proximity discovery: from `origin` location, find nearby actors of a
        given role (buyers / farmers / transport), sorted nearest-first.
        Used by any actor to discover who's around them."""
        opin = db.LOCATIONS.get(origin)
        # buyers + retailers both live in the `buyers` table, split by role
        table = {"buyers": "buyers", "retailers": "buyers",
                 "farmers": "farmers", "transport": "transport"}.get(find)
        if not table:
            return {"error": "find must be buyers, retailers, farmers or transport"}
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        out = []
        for r in rows:
            if table == "buyers":
                want_role = "retailer" if find == "retailers" else "buyer"
                if (r["role"] or "buyer") != want_role:
                    continue
            dist = db.haversine_km(opin, db.LOCATIONS.get(r["location"]))
            if radius is not None and dist > radius:
                continue
            tloc = db.LOCATIONS.get(r["location"]) or (None, None)
            item = {"id": r["id"], "name": r["name"], "location": r["location"],
                    "distance_km": dist, "rating": r["rating"], "rating_count": r["rating_count"],
                    "phone": r["phone"],
                    "lat": r["lat"] if r["lat"] is not None else tloc[0],
                    "lng": r["lng"] if r["lng"] is not None else tloc[1]}
            if table == "buyers":
                item["type"] = r["type"]
                item["role"] = r["role"] or "buyer"
            elif table == "farmers":
                item["verified"] = bool(r["verified"])
                item["active_listings"] = conn.execute(
                    "SELECT COUNT(*) c FROM listings WHERE farmer_id=? AND status='active'",
                    (r["id"],)).fetchone()["c"]
            elif table == "transport":
                item["vehicle"] = r["vehicle"]
                item["capacity_crates"] = r["capacity_crates"]
                item["rate_per_km"] = r["rate_per_km"]
                item["available"] = bool(r["available"])
            out.append(item)
        out.sort(key=lambda x: x["distance_km"])
        ocoord = opin or (None, None)
        return {"origin": origin, "origin_lat": ocoord[0], "origin_lng": ocoord[1],
                "find": find, "radius": radius, "results": out}

    def _dashboard(self, conn):
        orders = conn.execute("SELECT * FROM orders").fetchall()
        gmv = round(sum(o["total"] for o in orders), 2)
        produce_value = round(sum(o["produce_total"] for o in orders), 2)
        completed = [o for o in orders if o["status"] == "completed"]

        # --- Per-transaction loss-avoided model (not a flat % of GMV) ---
        # For each sold lot we estimate the spoilage probability it FACED at the
        # moment of sale from its crop shelf-life and how little life remained
        # (db.urgency_score: 0 = just harvested, 1 = at/over its shelf life), then
        # scale by Ghana's 20–50% perishable-loss band (midpoint 0.35). A lot sold
        # while still fresh is credited little; a near-spoiling lot rescued in time
        # is credited a lot. We only count lots that were actually delivered.
        loss_avoided = 0.0
        urgent_rescued = 0
        for o in completed:
            lst = conn.execute("SELECT crop, harvested_at FROM listings WHERE id=?",
                               (o["listing_id"],)).fetchone()
            if not lst:
                continue
            urg = db.urgency_score(lst["crop"], lst["harvested_at"])  # 0..1 at sale time
            loss_avoided += o["produce_total"] * 0.35 * urg
            if urg >= 0.5:
                urgent_rescued += 1
        loss_avoided = round(loss_avoided, 2)

        # avg hours from listing creation -> order (time-to-sale)
        times = []
        for o in orders:
            lst = conn.execute("SELECT created_at FROM listings WHERE id=?", (o["listing_id"],)).fetchone()
            if lst:
                times.append(max(0, (o["created_at"] - lst["created_at"]) / 3600.0))
        avg_tts = round(sum(times) / len(times), 1) if times else 0
        return {
            "orders": len(orders), "completed": len(completed),
            "gmv": gmv, "produce_value": produce_value, "loss_avoided": loss_avoided,
            "urgent_rescued": urgent_rescued,
            "avg_time_to_sale_hours": avg_tts,
            "farmers": conn.execute("SELECT COUNT(*) c FROM farmers").fetchone()["c"],
            "buyers": conn.execute(
                "SELECT COUNT(*) c FROM buyers WHERE COALESCE(role,'buyer')='buyer'").fetchone()["c"],
            "retailers": conn.execute(
                "SELECT COUNT(*) c FROM buyers WHERE role='retailer'").fetchone()["c"],
            "transport": conn.execute("SELECT COUNT(*) c FROM transport").fetchone()["c"],
            "active_listings": conn.execute(
                "SELECT COUNT(*) c FROM listings WHERE status='active'").fetchone()["c"],
            "escrow_held": round(sum(
                o["total"] for o in orders if o["payment_status"] == "held"), 2),
        }


def main():
    if not os.path.exists(db.DB_PATH):
        seed.reset()
    else:
        db.init_db()
    print(f"\n  🍅 VegeLink running at  http://localhost:{PORT}")
    print(f"     USSD endpoint:          http://localhost:{PORT}/api/ussd")
    print("     Press Ctrl+C to stop.\n")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
