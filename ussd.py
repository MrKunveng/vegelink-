"""USSD menu engine — Africa's Talking compatible, bilingual (English / Twi).

The gateway POSTs sessionId, phoneNumber and `text` (the full sequence of
user inputs joined by '*'). We reply with a string beginning with:
  CON  -> show menu, keep session open
  END  -> show final message, close session

The FIRST input chooses a language (1=English, 2=Twi); every later step is
shown in that language. Being stateless-on-text means this same handler works
against the real Africa's Talking gateway and our on-screen emulator.
"""
import time
import db

CROP_MENU = db.CROPS  # shared veg + fruit list (kept in sync with db.py)
LOC_MENU = ["Akumadan", "Tuobodom", "Nkenkaasu", "Offinso", "Techiman"]

# Minimal i18n: instructional strings in English and Twi (Akan). Proper nouns
# (crop names, towns) stay as-is. Twi is provided to lower the literacy/language
# barrier for smallholder farmers — a key accessibility goal of the challenge.
STR = {
    "en": {
        "welcome": "VegeLink — Akwaaba, {name}!",
        "m1": "List produce for sale", "m2": "My active listings",
        "m3": "Today's market prices", "m4": "Request transport",
        "m5": "Register / my profile", "m6": "Buyers near me",
        "pick_crop": "Select crop:", "enter_qty": "{crop}: enter quantity (crates):",
        "enter_price": "Enter price per crate (GHS):", "pick_loc": "Select pickup location:",
        "confirm": "Confirm listing:\n{qty} crates of {crop}\n@ GHS {price}/crate\nPickup: {loc}\n1. Confirm  2. Cancel",
        "bad_crop": "Invalid crop selection. Please dial again.",
        "bad_num": "Invalid quantity or price. Please dial again.",
        "cancelled": "Listing cancelled.",
        "done": "Done! {qty} crates of {crop} listed @ GHS{price}.\nYou'll get an SMS when a buyer orders.",
        "no_listings": "You have no active listings.",
        "your_listings": "Your active listings:",
        "no_price": "No price data yet.", "today_prices": "Today's avg prices:",
        "no_transport": "No transport available right now.", "nearby_transport": "Nearby transport:",
        "transport_sent": "We'll text you a match.",
        "reg_first": "Register first (option 5) so we know your location.",
        "no_buyers": "No buyers found yet.", "buyers_near": "Buyers nearest {loc}:",
        "profile": "Profile:", "reg_loc": "Register — select your location:",
        "registered": "Registered! Location: {loc}. Use option 1 to list produce.",
        "invalid": "Invalid selection. Please dial again.",
        "list_first": "No listings yet. Use option 1 to list produce.",
        "live": "VegeLink: Your {qty} crates of {crop} @ GHS{price} are LIVE. We'll text you when a buyer orders.",
        "transport_req": "VegeLink: Transport request received. A provider will call you.",
    },
    "tw": {
        "welcome": "VegeLink — Akwaaba, {name}!",
        "m1": "Tɔn wo nnɔbae", "m2": "Me nnɔbae a ɛwɔ hɔ",
        "m3": "Ɛnnɛ gua so botaeɛ", "m4": "Hwehwɛ kar a ɛbɛsoa",
        "m5": "Kyerɛw wo din / me ho nsɛm", "m6": "Adetɔfoɔ a wɔbɛn me",
        "pick_crop": "Paw nnɔbae:", "enter_qty": "{crop}: kyerɛw dodoɔ (nkɛntɛn):",
        "enter_price": "Kyerɛw boɔ (GHS) wɔ kɛntɛn biara so:", "pick_loc": "Paw faako a wɔbɛfa:",
        "confirm": "Si so dua:\nNkɛntɛn {qty} {crop}\n@ GHS {price}/kɛntɛn\nFaako: {loc}\n1. Si so dua  2. Gyae",
        "bad_crop": "Nnɔbae a wopaaeɛ no nyɛ. Frɛ bio.",
        "bad_num": "Dodoɔ anaa boɔ no nyɛ. Frɛ bio.",
        "cancelled": "Wɔagyae.",
        "done": "Ɛwie! Nkɛntɛn {qty} {crop} @ GHS{price} aba dwa so.\nYɛbɛto wo nkra sɛ obi tɔ.",
        "no_listings": "Wonni nnɔbae biara wɔ hɔ.",
        "your_listings": "Wo nnɔbae a ɛwɔ hɔ:",
        "no_price": "Botaeɛ nni hɔ.", "today_prices": "Ɛnnɛ botaeɛ:",
        "no_transport": "Kar biara nni hɔ seesei.", "nearby_transport": "Kar a ɛbɛn:",
        "transport_sent": "Yɛbɛto wo nkra.",
        "reg_first": "Di kan kyerɛw wo din (5) na yɛahunu faako a wowɔ.",
        "no_buyers": "Adetɔfoɔ biara nni hɔ.", "buyers_near": "Adetɔfoɔ a wɔbɛn {loc}:",
        "profile": "Wo ho nsɛm:", "reg_loc": "Kyerɛw din — paw faako a wowɔ:",
        "registered": "Wɔakyerɛw wo din! Faako: {loc}. Fa 1 tɔn nnɔbae.",
        "invalid": "Nea wopaaeɛ no nyɛ. Frɛ bio.",
        "list_first": "Wonni nnɔbae. Fa 1 tɔn nnɔbae.",
        "live": "VegeLink: Wo nkɛntɛn {qty} {crop} @ GHS{price} aba dwa so. Yɛbɛto wo nkra sɛ obi tɔ.",
        "transport_req": "VegeLink: Yɛagye wo kar abisadeɛ. Ɔdwumayɛni bɛfrɛ wo.",
    },
}


def _t(lang, key, **kw):
    s = STR.get(lang, STR["en"]).get(key, STR["en"][key])
    return s.format(**kw) if kw else s


def _farmer_by_phone(conn, phone):
    return conn.execute("SELECT * FROM farmers WHERE phone=?", (phone,)).fetchone()


def _pick(menu, idx):
    try:
        return menu[int(idx) - 1]
    except (ValueError, IndexError):
        return None


def handle(conn, phone, text):
    parts = text.split("*") if text else []

    # ---------- Step 0: language selection ----------
    if not parts or parts == [""]:
        return ("CON Welcome to VegeLink / Akwaaba\n"
                "Choose language / Paw kasa:\n"
                "1. English\n2. Twi")

    lang = "tw" if parts[0] == "2" else "en"
    rest = parts[1:]  # everything after the language choice

    def T(key, **kw):
        return _t(lang, key, **kw)

    # ---------- Main menu ----------
    if not rest:
        farmer = _farmer_by_phone(conn, phone)
        who = farmer["name"].split()[0] if farmer else ("kuayɛni" if lang == "tw" else "farmer")
        return ("CON " + T("welcome", name=who) + "\n"
                "1. " + T("m1") + "\n2. " + T("m2") + "\n3. " + T("m3") + "\n"
                "4. " + T("m4") + "\n5. " + T("m5") + "\n6. " + T("m6"))

    choice = rest[0]

    # ---------- 1. List produce ----------
    if choice == "1":
        if len(rest) == 1:
            menu = "\n".join(f"{i+1}. {c}" for i, c in enumerate(CROP_MENU))
            return "CON " + T("pick_crop") + "\n" + menu
        if len(rest) == 2:
            crop = _pick(CROP_MENU, rest[1])
            if not crop:
                return "END " + T("bad_crop")
            return "CON " + T("enter_qty", crop=crop)
        if len(rest) == 3:
            return "CON " + T("enter_price")
        if len(rest) == 4:
            menu = "\n".join(f"{i+1}. {l}" for i, l in enumerate(LOC_MENU))
            return "CON " + T("pick_loc") + "\n" + menu
        if len(rest) == 5:
            crop = _pick(CROP_MENU, rest[1])
            loc = _pick(LOC_MENU, rest[4])
            return "CON " + T("confirm", qty=rest[2], crop=crop, price=rest[3], loc=loc)
        if len(rest) == 6:
            if rest[5] != "1":
                return "END " + T("cancelled")
            crop = _pick(CROP_MENU, rest[1])
            loc = _pick(LOC_MENU, rest[4])
            try:
                qty = int(rest[2]); price = float(rest[3])
            except ValueError:
                return "END " + T("bad_num")

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
            db.log_notification(conn, "SMS", phone,
                                T("live", qty=qty, crop=crop, price=f"{price:.0f}"),
                                "farmer", farmer_id)
            conn.commit()
            return "END " + T("done", qty=qty, crop=crop, price=f"{price:.0f}")

    # ---------- 2. My listings ----------
    if choice == "2":
        farmer = _farmer_by_phone(conn, phone)
        if not farmer:
            return "END " + T("list_first")
        rows = conn.execute(
            "SELECT * FROM listings WHERE farmer_id=? AND status='active' ORDER BY id DESC LIMIT 5",
            (farmer["id"],)).fetchall()
        if not rows:
            return "END " + T("no_listings")
        lines = [f"- {r['quantity']}x {r['crop']} @GHS{r['price']:.0f}" for r in rows]
        return "END " + T("your_listings") + "\n" + "\n".join(lines)

    # ---------- 3. Market prices ----------
    if choice == "3":
        rows = conn.execute(
            "SELECT crop, ROUND(AVG(price)) avg FROM listings WHERE status='active' GROUP BY crop"
        ).fetchall()
        if not rows:
            return "END " + T("no_price")
        lines = [f"- {r['crop']}: ~GHS{int(r['avg'])}/crate" for r in rows]
        return "END " + T("today_prices") + "\n" + "\n".join(lines)

    # ---------- 4. Request transport ----------
    if choice == "4":
        rows = conn.execute(
            "SELECT * FROM transport WHERE available=1 ORDER BY rating DESC LIMIT 3").fetchall()
        if not rows:
            return "END " + T("no_transport")
        lines = [f"- {r['name']} ({r['vehicle']}), GHS{r['rate_per_km']:.1f}/km" for r in rows]
        farmer = _farmer_by_phone(conn, phone)
        db.log_notification(conn, "SMS", phone, T("transport_req"),
                            "farmer", farmer["id"] if farmer else None)
        conn.commit()
        return "END " + T("nearby_transport") + "\n" + "\n".join(lines) + "\n" + T("transport_sent")

    # ---------- 6. Buyers near me ----------
    if choice == "6":
        farmer = _farmer_by_phone(conn, phone)
        if not farmer:
            return "END " + T("reg_first")
        buyers = conn.execute("SELECT * FROM buyers").fetchall()
        origin = db.LOCATIONS.get(farmer["location"])
        ranked = sorted(
            ({"b": b, "d": db.haversine_km(origin, db.LOCATIONS.get(b["location"]))}
             for b in buyers), key=lambda x: x["d"])[:4]
        if not ranked:
            return "END " + T("no_buyers")
        lines = [f"- {x['b']['name']} ({x['b']['location']}, {x['d']:.0f}km) {x['b']['rating']:.1f}*"
                 for x in ranked]
        return "END " + T("buyers_near", loc=farmer["location"]) + "\n" + "\n".join(lines)

    # ---------- 5. Register / profile ----------
    if choice == "5":
        farmer = _farmer_by_phone(conn, phone)
        if farmer:
            v = "Verified" if farmer["verified"] else "Unverified"
            return ("END " + T("profile") + f"\n{farmer['name']}\n{farmer['location']}\n"
                    f"{v} · {farmer['rating']:.1f}★ ({farmer['rating_count']})")
        if len(rest) == 1:
            menu = "\n".join(f"{i+1}. {l}" for i, l in enumerate(LOC_MENU))
            return "CON " + T("reg_loc") + "\n" + menu
        if len(rest) == 2:
            loc = _pick(LOC_MENU, rest[1])
            now = int(time.time())
            conn.execute(
                "INSERT INTO farmers (name,phone,location,verified,created_at) VALUES (?,?,?,0,?)",
                (f"Farmer {phone[-4:]}", phone, loc, now))
            conn.commit()
            return "END " + T("registered", loc=loc)

    return "END " + T("invalid")
