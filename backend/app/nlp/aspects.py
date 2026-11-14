"""Rule-based aspect (feature) detection.

How it works:
1. Choose the feature list that fits what was reviewed: physical products or
   mobile apps (choose_vocabulary). App reviews therefore never show "Battery"
   or "Camera", and phone reviews never show "Login".
2. Split each review into clauses (preprocess.split_clauses), so
   "great battery, but the camera is poor" becomes two clauses.
3. A clause that contains one of a feature's words is a mention of that
   feature. The clause itself is the feature's context: the pipeline scores
   that clause on its own, never the whole review, so each feature gets the
   sentiment of the words around it.

This is a transparent keyword method, not a learned model. It misses features
described without these words and can be confused by sarcasm.
"""
import re

from .preprocess import split_clauses

PRODUCT_ASPECTS = {
    "Battery": ["battery", "charge", "charging", "charger", "drains", "backup", "standby"],
    "Camera": ["camera", "photo", "photos", "selfie", "selfies", "portrait", "night mode", "lens",
               "video stabilisation"],
    "Display": ["display", "screen", "amoled", "brightness", "120hz", "dead pixels", "touch screen"],
    "Performance": ["performance", "lag", "lags", "lagging", "smooth", "gaming", "games", "heats", "overheating",
                    "warm", "slows", "hangs", "software"],
    "Build quality": ["build", "built", "premium", "design", "weight", "heavy", "back panel", "matte back"],
    "Price": ["price", "value for money", "worth", "overpriced", "affordable", "budget", "rupee"],
    "Delivery": ["delivery", "delivered", "shipping", "received it"],
    "Packaging": ["packaging", "packed", "box"],
    "Customer service": ["customer service", "customer support", "customer care", "service centre",
                         "replacement", "return process"],
}

APP_ASPECTS = {
    "Login & account": ["login", "log in", "logged in", "logging in", "log out", "logged out", "logs me out",
                        "sign in", "signed in", "sign up", "signup", "otp", "password", "account", "verification",
                        "authentication", "2fa"],
    "Crashes & stability": ["crash", "crashes", "crashing", "crashed", "freeze", "freezes", "freezing", "frozen",
                            "hangs", "hanging", "bug", "bugs", "buggy", "glitch", "glitches", "glitchy",
                            "not working", "stopped working", "doesn't work", "does not work", "force close",
                            "stuck"],
    "Speed & performance": ["slow", "slower", "fast", "faster", "speed", "lag", "lags", "laggy", "lagging",
                            "loading", "load time", "takes forever", "performance", "responsive", "smooth",
                            "battery drain", "drains battery"],
    "Updates": ["update", "updates", "updated", "new version", "latest version", "upgrade"],
    "Ads": ["ad", "ads", "advert", "adverts", "advertisement", "advertisements", "popup", "popups", "pop-up",
            "pop-ups", "commercials"],
    "Design & ease of use": ["ui", "interface", "design", "layout", "user friendly", "user-friendly", "easy to use",
                             "navigation", "dark mode", "font", "menu", "intuitive", "confusing", "cluttered"],
    "Notifications": ["notification", "notifications", "alert", "alerts", "reminder", "reminders"],
    "Payments & pricing": ["payment", "payments", "pay", "paid", "upi", "subscription", "premium", "charged",
                           "charges", "price", "prices", "pricing", "expensive", "cheap", "money", "wallet",
                           "cashback", "transaction"],
    "Customer support": ["customer support", "customer service", "customer care", "support team", "support",
                         "helpline", "help center", "help centre", "chat support", "complaint", "complaints",
                         "agent", "executive"],
    "Privacy & security": ["privacy", "private", "security", "secure", "data", "permission", "permissions",
                           "hacked", "scam", "fraud", "spam", "tracking", "ban", "banned"],
}

# Extra app features for some App Store categories, where they are central to the service.
APP_CATEGORY_EXTRAS = {
    "food & drink": {
        "Orders & delivery": ["delivery", "delivered", "delivery partner", "delivery boy", "order", "orders",
                              "late", "on time", "cold food", "missing item", "wrong order"],
        "Refunds": ["refund", "refunds", "refunded", "money back"],
    },
    "shopping": {
        "Orders & delivery": ["delivery", "delivered", "order", "orders", "shipping", "late", "on time",
                              "wrong item", "damaged"],
        "Refunds & returns": ["refund", "refunds", "refunded", "return", "returns", "replacement", "money back"],
    },
    "travel": {
        "Bookings": ["booking", "bookings", "booked", "ticket", "tickets", "cancellation", "cancelled"],
        "Refunds": ["refund", "refunds", "refunded", "money back"],
    },
}

DOMAINS = ("product", "app")

# An aspect needs at least this many mentions before we call it a strength/weakness.
MIN_MENTIONS_FOR_VERDICT = 3
# Share of positive (or negative) mentions needed to call it clearly positive (or negative).
CLEAR_MAJORITY = 0.65


def choose_vocabulary(domain: str = "product", category: str | None = None) -> dict[str, list[str]]:
    """The feature list for this kind of product. Unknown domains use the physical-product list."""
    if domain != "app":
        return PRODUCT_ASPECTS
    return APP_ASPECTS | APP_CATEGORY_EXTRAS.get((category or "").strip().lower(), {})


_pattern_cache: dict[int, dict[str, re.Pattern]] = {}


def _patterns(vocabulary: dict[str, list[str]]) -> dict[str, re.Pattern]:
    key = id(vocabulary)
    if key not in _pattern_cache:
        _pattern_cache[key] = {
            aspect: re.compile(r"(?<![\w-])(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
                               + r")(?![\w-])", re.IGNORECASE)
            for aspect, terms in vocabulary.items()
        }
    return _pattern_cache[key]


def find_mentions(text: str, vocabulary: dict[str, list[str]]) -> list[dict]:
    """One {"aspect", "snippet"} per feature mentioned (its first mention); scoring happens in the pipeline."""
    found: dict[str, dict] = {}
    patterns = _patterns(vocabulary)
    for clause in split_clauses(text):
        for aspect, pattern in patterns.items():
            if aspect not in found and pattern.search(clause):
                found[aspect] = {"aspect": aspect, "snippet": clause}
    return list(found.values())


def verdict(positive: int, negative: int, neutral: int) -> str:
    """Summarise one aspect's mentions as positive / negative / mixed."""
    total = positive + negative + neutral
    if total < MIN_MENTIONS_FOR_VERDICT:
        return "insufficient"
    if positive / total >= CLEAR_MAJORITY:
        return "positive"
    if negative / total >= CLEAR_MAJORITY:
        return "negative"
    return "mixed"
