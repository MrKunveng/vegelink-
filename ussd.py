"""USSD menu engine — Africa's Talking compatible.

The gateway POSTs sessionId, phoneNumber and `text` (the full sequence of
user inputs joined by '*'). We reply with a string beginning with:
  CON  -> show menu, keep session open
  END  -> show final message, close session

Being stateless-on-text means this same handler works against the real
Africa's Talking gateway and against our on-screen feature-phone emulator.
"""
import time
import db

CROP_MENU = db.CROPS  # shared veg + fruit list (kept in sync with db.py)
LOC_MENU = ["Akumadan", "Tuobodom", "Nkenkaasu", "Offinso", "Techiman"]


def _farmer_by_phone(conn, phone):
    return conn.execute("SELECT * FROM farmers WHERE phone=?", (phone,)).fetchone()


def _pick(menu, idx):
    try:
        return menu[int(idx) - 1]
    except (ValueError, IndexError):
        return None


def handle(conn, phone, text):
    parts = text.split("*") if text else []

    # ---------- Main menu ----------
    if not parts or parts == [""]:
        farmer = _farmer_by_phone(conn, phone)
        who = farmer["name"].split()[0] if farmer else "farmer"
        return ("CON VegeLink — Akwaaba, {}!\n"
                "1. List produce for sale\n"
                "2. My active listings\n"
                "3. Today's market prices\n"
                "4. Request transport\n"
                "5. Register / my profile\n"
                "6. Buyers near me").format(who)

    choice = parts[0]

    # ---------- 1. List produce ----------
    if choice == "1":
        if len(parts) == 1:
            menu = "\n".join(f"{i+1}. {c}" for i, c in enumerate(CROP_MENU))
            return "CON Select crop:\n" + menu
        if len(parts) == 2:
            crop = _pick(CROP_MENU, parts[1])
            if not crop:
                return "END Invalid crop selection."
            return f"CON {crop}: enter quantity (crates):"
        if len(parts) == 3:
            return "CON Enter price per crate (GHS):"
        if len(parts) == 4:
            menu = "\n".join(f"{i+1}. {l}" for i, l in enumerate(LOC_MENU))
            return "CON Select pickup location:\n" + menu
        if len(parts) == 5:
            crop = _pick(CROP_MENU, parts[1])
            loc = _pick(LOC_MENU, parts[4])
            return (f"CON Confirm listing:\n{parts[2]} crates of {crop}\n"
                    f"@ GHS {parts[3]}/crate\nPickup: {loc}\n1. Confirm  2. Cancel")
        if len(parts) == 6:
            if parts[5] != "1":
                return "END Listing cancelled."
            crop = _pick(CROP_MENU, parts[1])
            loc = _pick(LOC_MENU, parts[4])
            try:
                qty = int(parts[2]); price = float(parts[3])
            except ValueError:
                return "END Invalid quantity or price."

            farmer = _farmer_by_phone(conn, phone)
            now = int(time.time())
            if not farmer:
                cur = conn.execute(
                    "INSERT INTO farmers (name,phone,location,verified,created_at)"
                    " VALUES (?,?,?,0,?)",
                    (f"Farmer {phone[-4:]}", phone, loc, now))
                farmer_id = cur.lastrowid
            else:
                farmer_id = farmer["id"]

            conn.execute(
                "INSERT INTO listings (farmer_id,crop,quantity,unit,price,location,"
                "harvested_at,image,status,created_at) VALUES (?,?,?,?,?,?,?,?, 'active', ?)",
                (farmer_id, crop, qty, "crate", price, loc, now,
                 db.CROP_EMOJI.get(crop, "🧺"), now))
            db.log_notification(
                conn, "SMS", phone,
                f"VegeLink: Your {qty} crates of {crop} @ GHS{price:.0f} are LIVE. "
                f"We'll text you when a buyer orders.")
            conn.commit()
            return (f"END Done! {qty} crates of {crop} listed @ GHS{price:.0f}.\n"
                    f"You'll get an SMS when a buyer orders.")

    # ---------- 2. My listings ----------
    if choice == "2":
        farmer = _farmer_by_phone(conn, phone)
        if not farmer:
            return "END No listings yet. Use option 1 to list produce."
        rows = conn.execute(
            "SELECT * FROM listings WHERE farmer_id=? AND status='active' ORDER BY id DESC LIMIT 5",
            (farmer["id"],)).fetchall()
        if not rows:
            return "END You have no active listings."
        lines = [f"- {r['quantity']}x {r['crop']} @GHS{r['price']:.0f}" for r in rows]
        return "END Your active listings:\n" + "\n".join(lines)

    # ---------- 3. Market prices ----------
    if choice == "3":
        rows = conn.execute(
            "SELECT crop, ROUND(AVG(price)) avg FROM listings WHERE status='active' GROUP BY crop"
        ).fetchall()
        if not rows:
            return "END No price data yet."
        lines = [f"- {r['crop']}: ~GHS{int(r['avg'])}/crate" for r in rows]
        return "END Today's avg prices:\n" + "\n".join(lines)

    # ---------- 4. Request transport ----------
    if choice == "4":
        rows = conn.execute(
            "SELECT * FROM transport WHERE available=1 ORDER BY rating DESC LIMIT 3").fetchall()
        if not rows:
            return "END No transport available right now."
        lines = [f"- {r['name']} ({r['vehicle']}), GHS{r['rate_per_km']:.1f}/km" for r in rows]
        db.log_notification(conn, "SMS", phone,
                            "VegeLink: Transport request received. A provider will call you.")
        conn.commit()
        return "END Nearby transport:\n" + "\n".join(lines) + "\nWe'll text you a match."

    # ---------- 6. Buyers near me ----------
    if choice == "6":
        farmer = _farmer_by_phone(conn, phone)
        if not farmer:
            return "END Register first (option 5) so we know your location."
        buyers = conn.execute("SELECT * FROM buyers").fetchall()
        origin = db.LOCATIONS.get(farmer["location"])
        ranked = sorted(
            ({"b": b, "d": db.haversine_km(origin, db.LOCATIONS.get(b["location"]))}
             for b in buyers), key=lambda x: x["d"])[:4]
        if not ranked:
            return "END No buyers found yet."
        lines = [f"- {x['b']['name']} ({x['b']['location']}, {x['d']:.0f}km) {x['b']['rating']:.1f}*"
                 for x in ranked]
        return f"END Buyers nearest {farmer['location']}:\n" + "\n".join(lines)

    # ---------- 5. Register / profile ----------
    if choice == "5":
        farmer = _farmer_by_phone(conn, phone)
        if farmer:
            v = "Verified" if farmer["verified"] else "Unverified"
            return (f"END Profile:\n{farmer['name']}\n{farmer['location']}\n"
                    f"{v} · {farmer['rating']:.1f}★ ({farmer['rating_count']})")
        if len(parts) == 1:
            menu = "\n".join(f"{i+1}. {l}" for i, l in enumerate(LOC_MENU))
            return "CON Register — select your location:\n" + menu
        if len(parts) == 2:
            loc = _pick(LOC_MENU, parts[1])
            now = int(time.time())
            conn.execute(
                "INSERT INTO farmers (name,phone,location,verified,created_at) VALUES (?,?,?,0,?)",
                (f"Farmer {phone[-4:]}", phone, loc, now))
            conn.commit()
            return f"END Registered! Location: {loc}. Use option 1 to list produce."

    return "END Invalid selection. Please dial again."
