"""VegeLink server — stdlib HTTP server (no external deps).

  python3 server.py            # serves http://localhost:8000
Routes:
  /                      -> SPA (static/index.html)
  /api/*                 -> JSON REST API
  /api/ussd              -> Africa's Talking compatible USSD endpoint (text/plain)
"""
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import ussd
import seed

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
PORT = int(os.environ.get("PORT", "8000"))


# ----------------------------- serializers -----------------------------

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
        "total": r["total"], "payment_status": r["payment_status"], "status": r["status"],
        "payment_method": r["payment_method"],
        "payment_label": db.PAYMENT_LABELS.get(r["payment_method"], "Mobile Money"),
        "buyer": {"id": buyer["id"], "name": buyer["name"], "location": buyer["location"]} if buyer else None,
        "farmer": {"id": farmer["id"], "name": farmer["name"], "location": farmer["location"]} if farmer else None,
        "transport": transport,
        "buyer_rated": bool(r["buyer_rated"]), "farmer_rated": bool(r["farmer_rated"]),
        "created_at": r["created_at"],
    }


# ----------------------------- request handler -----------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet console
        pass

    # --- helpers ---
    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, code=200):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
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
        if not fp.startswith(STATIC_DIR) or not os.path.isfile(fp):
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
                rows = conn.execute("SELECT * FROM farmers ORDER BY id").fetchall()
                return self._send_json([dict(r) for r in rows])

            if path == "/api/buyers":
                rows = conn.execute("SELECT * FROM buyers ORDER BY id").fetchall()
                return self._send_json([dict(r) for r in rows])

            if path == "/api/transport":
                rows = conn.execute("SELECT * FROM transport ORDER BY rating DESC").fetchall()
                return self._send_json([dict(r) for r in rows])

            if path == "/api/listings":
                crop = qs.get("crop", [None])[0]
                maxprice = qs.get("maxprice", [None])[0]
                loc = qs.get("location", [None])[0]
                sort = qs.get("sort", ["smart"])[0]
                buyer_loc = qs.get("buyer_location", ["Accra"])[0]
                sql = "SELECT * FROM listings WHERE status='active'"
                args = []
                if crop:
                    sql += " AND crop=?"; args.append(crop)
                if loc:
                    sql += " AND location=?"; args.append(loc)
                if maxprice:
                    sql += " AND price<=?"; args.append(float(maxprice))
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
                sql = "SELECT * FROM orders WHERE 1=1"; args = []
                if qs.get("buyer_id"):
                    sql += " AND buyer_id=?"; args.append(int(qs["buyer_id"][0]))
                if qs.get("farmer_id"):
                    sql += " AND farmer_id=?"; args.append(int(qs["farmer_id"][0]))
                if qs.get("transport_id"):
                    sql += " AND transport_id=?"; args.append(int(qs["transport_id"][0]))
                sql += " ORDER BY id DESC"
                rows = conn.execute(sql, args).fetchall()
                return self._send_json([order_dict(conn, r) for r in rows])

            if path == "/api/notifications":
                rows = conn.execute(
                    "SELECT * FROM notifications ORDER BY id DESC LIMIT 40").fetchall()
                return self._send_json([dict(r) for r in rows])

            if path == "/api/dashboard":
                return self._send_json(self._dashboard(conn))

            if path == "/api/meta":
                return self._send_json({
                    "crops": db.CROPS,
                    "locations": list(db.LOCATIONS.keys()),
                    "shelf_life": db.SHELF_LIFE_HOURS,
                    "payment_methods": db.PAYMENT_LABELS,
                })

            if path == "/api/nearby":
                find = qs.get("find", ["buyers"])[0]
                origin = qs.get("origin", ["Akumadan"])[0]
                radius = qs.get("radius", [None])[0]
                radius = float(radius) if radius else None
                return self._send_json(self._nearby(conn, find, origin, radius))

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

            if path == "/api/farmers":
                cur = conn.execute(
                    "INSERT INTO farmers (name,phone,location,verified,created_at) VALUES (?,?,?,?,?)",
                    (data["name"], data["phone"], data["location"], int(data.get("verified", 0)), now))
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path == "/api/buyers":
                role = data.get("role", "buyer")  # buyer | retailer
                cur = conn.execute(
                    "INSERT INTO buyers (name,phone,type,role,location,created_at) VALUES (?,?,?,?,?,?)",
                    (data["name"], data["phone"],
                     data.get("type", "retailer" if role == "retailer" else "household"),
                     role, data["location"], now))
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path == "/api/transport":
                cur = conn.execute(
                    "INSERT INTO transport (name,phone,vehicle,capacity_crates,location,"
                    "rate_per_km,available,created_at) VALUES (?,?,?,?,?,?,1,?)",
                    (data["name"], data["phone"], data.get("vehicle", "Pickup truck"),
                     int(data.get("capacity_crates", 80)), data["location"],
                     float(data.get("rate_per_km", 2.5)), now))
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path == "/api/listings":
                cur = conn.execute(
                    "INSERT INTO listings (farmer_id,crop,quantity,unit,price,location,"
                    "harvested_at,image,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'active', ?)",
                    (int(data["farmer_id"]), data["crop"], int(data["quantity"]), "crate",
                     float(data["price"]), data["location"],
                     now - int(data.get("harvested_hours_ago", 6)) * 3600,
                     data.get("image") or db.CROP_EMOJI.get(data["crop"], "🧺"), now))
                farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (data["farmer_id"],)).fetchone()
                db.log_notification(conn, "SMS", farmer["phone"],
                    f"VegeLink: Your {data['quantity']} crates of {data['crop']} are LIVE.")
                conn.commit()
                return self._send_json({"id": cur.lastrowid}, 201)

            if path == "/api/orders":
                return self._create_order(conn, data, now)

            if path.startswith("/api/orders/") and path.endswith("/status"):
                oid = int(path.split("/")[3])
                return self._update_status(conn, oid, data.get("status"), now)

            if path.startswith("/api/orders/") and path.endswith("/confirm-delivery"):
                oid = int(path.split("/")[3])
                return self._confirm_delivery(conn, oid, now)

            if path.startswith("/api/orders/") and path.endswith("/rate"):
                oid = int(path.split("/")[3])
                return self._rate(conn, oid, data)

            if path == "/api/seed/reset":
                conn.close()
                seed.reset()
                return self._send_json({"ok": True})

            return self._send_json({"error": "unknown route"}, 404)
        except Exception as e:  # surface errors as JSON for easy debugging
            return self._send_json({"error": str(e)}, 400)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ----------------------- business logic -----------------------

    def _create_order(self, conn, data, now):
        listing = conn.execute("SELECT * FROM listings WHERE id=?",
                                (int(data["listing_id"]),)).fetchone()
        if not listing:
            return self._send_json({"error": "listing not found"}, 404)
        buyer = conn.execute("SELECT * FROM buyers WHERE id=?", (int(data["buyer_id"]),)).fetchone()
        if not buyer:
            return self._send_json({"error": "buyer not found"}, 404)
        qty = int(data["quantity"])
        if qty <= 0 or qty > listing["quantity"]:
            return self._send_json({"error": "invalid quantity"}, 400)

        produce_total = round(qty * listing["price"], 2)

        # --- Auto-match transport: available, enough capacity, best (cheap+rated) ---
        transport_id = data.get("transport_id")
        t_cost = t_dist = 0.0
        eta = 0
        chosen = None
        candidates = conn.execute(
            "SELECT * FROM transport WHERE available=1 AND capacity_crates>=? ", (qty,)).fetchall()
        leg_km = db.haversine_km(db.LOCATIONS.get(listing["location"]),
                                 db.LOCATIONS.get(buyer["location"]))
        if transport_id:
            chosen = conn.execute("SELECT * FROM transport WHERE id=?", (int(transport_id),)).fetchone()
        elif candidates:
            # Cargo tricycles (aboboyaa) only suit local hauls (<=50km).
            suitable = [t for t in candidates
                        if not ("tricycle" in t["vehicle"].lower() and leg_km > 50)] or candidates

            def cand_cost(t):
                d, c, e = db.estimate_transport(listing["location"], buyer["location"], t["rate_per_km"])
                return c - t["rating"] * 5  # prefer cheaper + higher rated
            chosen = min(suitable, key=cand_cost)
        if chosen:
            t_dist, t_cost, eta = db.estimate_transport(
                listing["location"], buyer["location"], chosen["rate_per_km"])
            transport_id = chosen["id"]
        else:
            transport_id = None

        total = round(produce_total + t_cost, 2)

        # --- Payment method: COD is collected on delivery (no escrow);
        #     momo / bank / card are held in escrow until delivery confirmed. ---
        method = data.get("payment_method", "momo")
        if method not in db.PAYMENT_LABELS:
            method = "momo"
        method_label = db.PAYMENT_LABELS[method]
        pay_status = "cod_pending" if method == "cod" else "held"

        cur = conn.execute(
            "INSERT INTO orders (listing_id,buyer_id,farmer_id,quantity,unit_price,produce_total,"
            "transport_id,transport_cost,distance_km,eta_minutes,total,payment_method,"
            "payment_status,status,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (listing["id"], buyer["id"], listing["farmer_id"], qty, listing["price"], produce_total,
             transport_id, t_cost, t_dist, eta, total, method, pay_status,
             "matched" if transport_id else "placed", now))
        order_id = cur.lastrowid

        # decrement inventory
        remaining = listing["quantity"] - qty
        conn.execute("UPDATE listings SET quantity=?, status=? WHERE id=?",
                     (remaining, "sold_out" if remaining <= 0 else "active", listing["id"]))

        # notifications: payment + farmer + transport
        farmer = conn.execute("SELECT * FROM farmers WHERE id=?", (listing["farmer_id"],)).fetchone()
        if method == "cod":
            db.log_notification(conn, "app", buyer["name"],
                f"Cash on Delivery selected — pay GHS{total:.2f} to the driver on arrival.")
            secured = f"Buyer will pay GHS{total:.0f} CASH on delivery."
        else:
            db.log_notification(conn, "app", buyer["name"],
                f"{method_label} payment GHS{total:.2f} HELD in escrow — releases on delivery confirmation.")
            secured = f"Payment ({method_label}) secured in escrow."
        db.log_notification(conn, "SMS", farmer["phone"],
            f"VegeLink: NEW ORDER! {qty} crates {listing['crop']} from {buyer['name']}. "
            f"{secured} Prepare for pickup.")
        if chosen:
            db.log_notification(conn, "SMS", chosen["phone"],
                f"VegeLink: Pickup job — {qty} crates from {listing['location']} to "
                f"{buyer['location']} (~{t_dist:.0f}km, GHS{t_cost:.0f}). ETA {eta}min.")
        conn.commit()
        return self._send_json(order_dict(conn, conn.execute(
            "SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()), 201)

    def _update_status(self, conn, oid, status, now):
        valid = ["placed", "matched", "picked_up", "delivered"]
        if status not in valid:
            return self._send_json({"error": "invalid status"}, 400)
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return self._send_json({"error": "not found"}, 404)
        delivered_at = now if status == "delivered" else order["delivered_at"]
        conn.execute("UPDATE orders SET status=?, delivered_at=? WHERE id=?",
                     (status, delivered_at, oid))
        buyer = conn.execute("SELECT * FROM buyers WHERE id=?", (order["buyer_id"],)).fetchone()
        msg = {"picked_up": "Produce picked up — on the way.",
               "delivered": "Delivered! Please confirm to release payment.",
               "matched": "Transport matched and scheduled."}.get(status)
        if msg:
            db.log_notification(conn, "app", buyer["name"], f"Order #{oid}: {msg}")
        conn.commit()
        return self._send_json(order_dict(conn, conn.execute(
            "SELECT * FROM orders WHERE id=?", (oid,)).fetchone()))

    def _confirm_delivery(self, conn, oid, now):
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return self._send_json({"error": "not found"}, 404)
        method = order["payment_method"]
        label = db.PAYMENT_LABELS.get(method, "Mobile Money")
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
        db.log_notification(conn, "SMS", farmer["phone"], sms)
        conn.commit()
        return self._send_json(order_dict(conn, conn.execute(
            "SELECT * FROM orders WHERE id=?", (oid,)).fetchone()))

    def _rate(self, conn, oid, data):
        order = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return self._send_json({"error": "not found"}, 404)
        target = data.get("target")  # 'farmer' or 'buyer' or 'transport'
        stars = float(data.get("stars", 5))
        table = {"farmer": ("farmers", order["farmer_id"]),
                 "buyer": ("buyers", order["buyer_id"]),
                 "transport": ("transport", order["transport_id"])}.get(target)
        if not table or not table[1]:
            return self._send_json({"error": "invalid rate target"}, 400)
        tbl, tid = table
        row = conn.execute(f"SELECT rating, rating_count FROM {tbl} WHERE id=?", (tid,)).fetchone()
        new_count = row["rating_count"] + 1
        new_rating = round((row["rating"] * row["rating_count"] + stars) / new_count, 2)
        conn.execute(f"UPDATE {tbl} SET rating=?, rating_count=? WHERE id=?",
                     (new_rating, new_count, tid))
        if target == "farmer":
            conn.execute("UPDATE orders SET farmer_rated=1 WHERE id=?", (oid,))
        elif target == "buyer":
            conn.execute("UPDATE orders SET buyer_rated=1 WHERE id=?", (oid,))
        conn.commit()
        return self._send_json({"ok": True, "rating": new_rating})

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
            item = {"id": r["id"], "name": r["name"], "location": r["location"],
                    "distance_km": dist, "rating": r["rating"], "rating_count": r["rating_count"],
                    "phone": r["phone"]}
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
        return {"origin": origin, "find": find, "radius": radius, "results": out}

    def _dashboard(self, conn):
        orders = conn.execute("SELECT * FROM orders").fetchall()
        gmv = round(sum(o["total"] for o in orders), 2)
        produce_value = round(sum(o["produce_total"] for o in orders), 2)
        # Loss avoided: produce that reached a buyer fast instead of spoiling.
        # Ghana loses 20-50% of perishables; we use the 35% midpoint as the
        # share of each sold lot that would typically have been lost.
        loss_avoided = round(produce_value * 0.35, 2)
        completed = [o for o in orders if o["status"] == "completed"]
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
