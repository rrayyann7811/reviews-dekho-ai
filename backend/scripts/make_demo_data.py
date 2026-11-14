"""Writes the synthetic demo review files in backend/data/demo/ (deterministic: same seed, same files).

Run from backend/:  .venv/bin/python scripts/make_demo_data.py

Every review, product and reviewer name is invented for demonstration and testing. Nothing is copied from a real
website or a real customer. The files are committed, so the demo never needs this script; it exists so they can be
re-created and checked (`git diff` after running it should be empty).
"""
import csv
import datetime as dt
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "demo"

# (feature phrase, sentiment) building blocks. Positive / negative / neutral wording per feature.
PHONE = {
    "battery": (["The battery easily lasts a full day", "Battery life is excellent, two days with light use",
                 "Charging is quick and the battery is reliable"],
                ["The battery drains far too fast", "Battery backup is poor after a few weeks",
                 "The phone needs charging twice a day, battery is weak"],
                ["The battery lasts about a day", "Battery is average"]),
    "display": (["The display is bright and sharp", "Lovely screen, colours look great",
                 "The display is easy to read outdoors"],
                ["The screen has a yellow tint", "The display is dim in sunlight", "Screen scratches far too easily"],
                ["The display is fine", "Screen size is normal"]),
    "camera": (["The camera takes excellent photos", "Great camera, portraits look natural",
                "Night photos from the camera are impressive"],
               ["The camera is blurry in low light", "Photos look washed out, camera is disappointing",
                "The camera app is slow and photos are noisy"],
               ["The camera is okay for daylight photos", "Camera does the job"]),
    "performance": (["Performance is fast and smooth", "No lag at all, performance is great for gaming"],
                    ["The phone lags and heats up while gaming", "Performance is slow when switching apps"],
                    ["Performance is as expected for the price"]),
    "price": (["Great value for the price", "Worth every rupee"],
              ["Overpriced for what you get", "Too expensive compared to similar phones"],
              ["The price is reasonable"]),
    "delivery": (["Fast delivery and well packed"], ["Delivery was late by a week"], ["Delivery took four days"]),
}
APP = {
    "speed": (["The app is fast and smooth", "Pages load quickly"], ["The app is very slow to load"],
              ["Speed is okay"]),
    "orders": (["Orders arrive on time", "Delivery of my orders is always quick"],
               ["My order arrived late again", "Wrong items in my order twice"], ["Orders usually take a day"]),
    "payments": (["Payments are quick and easy", "UPI payment works every time"],
                 ["Payment failed but money was deducted", "Payments keep failing at checkout"],
                 ["Payment options are standard"]),
    "design": (["The design is clean and easy to use", "Very simple to use, nice design"],
               ["The new design is confusing", "Too many menus, hard to use"], ["The layout is fine"]),
    "support": (["Customer support solved my issue quickly"], ["Customer support never responds"],
                ["Support replied after a day"]),
    "crashes": (["No crashes so far, very stable"], ["The app keeps crashing after the update",
                                                     "It crashes every time I open the cart"], []),
    "login": (["Login with OTP is quick"], ["I can't log in, the OTP never arrives", "Login keeps failing"], []),
    "ads": ([], ["Too many ads and pop-ups", "Ads everywhere, very annoying"], []),
}
EARPHONES = {
    "sound": (["The sound is clear with deep bass", "Great sound quality for calls and music"],
              ["Sound is tinny and the bass is weak", "The sound crackles at high volume"], ["Sound is decent"]),
    "battery": (["Battery lasts the whole day", "The case charges quickly and the battery is good"],
                ["Battery drains in two hours", "The battery of the left bud dies early"], ["Battery is average"]),
    "build": (["Build quality feels premium", "Solid build, fits comfortably"],
              ["Build quality is cheap and flimsy", "The case broke within a month"], ["Build is okay"]),
    "price": (["Good value for the price"], ["Overpriced for the sound"], ["Price is fair"]),
}
HINGLISH = ["bahut accha product hai yaar, sound ekdum mast", "bakwas earphones hai, paisa barbaad ho gaya",
            "sound quality theek thaak hai, battery jaldi khatam ho jati hai", "ekdum paisa vasool, bass bahut badhiya",
            "bilkul bekar hai, ek mahine mein kharab ho gaya", "accha hai lekin case thoda kamzor hai"]


def review(rng: random.Random, vocab: dict, weights: dict) -> tuple[str, int]:
    """1-2 feature phrases with a sentiment drawn from per-feature weights (positive, negative, neutral)."""
    features = rng.sample(list(vocab), k=rng.choice([1, 1, 2]))
    parts, score = [], 0
    for feature in features:
        pos, neg, neu = vocab[feature]
        options = [(pos, 1), (neg, -1), (neu, 0)]
        weights_here = weights.get(feature, (1, 1, 1))
        choices = [(o, s) for (o, s), w in zip(options, weights_here) if o]
        pool, s = rng.choices(choices, weights=[w for (o, _), w in zip(options, weights_here) if o])[0]
        parts.append(rng.choice(pool))
        score += s
    stars = {2: 5, 1: rng.choice([4, 5]), 0: 3, -1: rng.choice([1, 2]), -2: 1}[max(-2, min(2, score))]
    return ". ".join(parts) + ".", stars


def write(name: str, rows: list[dict]):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["review_id", "reviewer_name", "rating", "review_date", "review_text"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{name}: {len(rows)} reviews")


def make(prefix: str, rng: random.Random, n: int, vocab: dict, weights: dict, start: dt.date, days: int,
         first_id: int = 1) -> list[dict]:
    rows = []
    for i in range(n):
        text, stars = review(rng, vocab, weights)
        rows.append({"review_id": f"{prefix}-{first_id + i:04d}", "reviewer_name": f"Demo user {first_id + i:03d}",
                     "rating": stars, "review_date": (start + dt.timedelta(days=rng.randrange(days))).isoformat(),
                     "review_text": text})
    return rows


def main():
    rng = random.Random(20261114)
    # A second phone to compare with the bundled Kestrel sample: strong display and camera, weaker battery.
    write("aurora_x5_phone.csv", make("AX5", rng, 150, PHONE, {
        "battery": (2, 3, 1), "display": (5, 1, 1), "camera": (4, 1, 1), "performance": (3, 1, 1),
        "price": (2, 2, 1), "delivery": (3, 1, 1)}, dt.date(2026, 8, 1), 90))
    # An app, before and after a (fictional) update: the update brings crashes and login problems.
    write("quickcart_app_october.csv", make("QC", rng, 120, APP, {
        "speed": (4, 1, 1), "orders": (4, 2, 1), "payments": (3, 2, 1), "design": (4, 1, 1), "support": (2, 2, 1),
        "crashes": (3, 1, 0), "login": (3, 1, 0), "ads": (0, 1, 0)}, dt.date(2026, 10, 1), 31))
    # After the update most new reviews are about crashes, login and speed (the second run re-analyses all 210).
    after_update = {k: APP[k] for k in ("crashes", "login", "speed", "payments")}
    write("quickcart_app_november_update.csv", make("QC", rng, 90, after_update, {
        "crashes": (1, 8, 0), "login": (1, 5, 0), "speed": (1, 4, 1), "payments": (2, 3, 1)},
        dt.date(2026, 11, 1), 13, first_id=121))
    # Earphones with some Hinglish reviews, which the app marks "not analysed".
    rows = make("SB", rng, 60, EARPHONES, {"sound": (4, 2, 1), "battery": (2, 2, 1), "build": (3, 2, 1),
                                           "price": (3, 1, 1)}, dt.date(2026, 9, 1), 60)
    for i in range(12):
        text = HINGLISH[i % len(HINGLISH)]
        stars = 1 if any(w in text for w in ("bakwas", "bekar")) else rng.choice([3, 4, 5])
        rows.append({"review_id": f"SB-{61 + i:04d}", "reviewer_name": f"Demo user {61 + i:03d}", "rating": stars,
                     "review_date": (dt.date(2026, 9, 1) + dt.timedelta(days=rng.randrange(60))).isoformat(),
                     "review_text": text})
    write("saffron_buds_earphones_mixed_language.csv", rows)


if __name__ == "__main__":
    main()
