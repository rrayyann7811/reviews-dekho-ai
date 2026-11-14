"""Is a review written in English, which both sentiment engines are built for?

Neither engine understands Hindi, Hinglish (Hindi written in Latin letters) or
other languages. VADER, for example, scores "bakwas app hai" (= "useless app")
as neutral simply because it knows none of the words. Instead of silently
calling such reviews neutral, they are marked "language not supported" and
left out of the sentiment numbers. Their star ratings still count.

The check is a transparent heuristic, not a trained language identifier:
1. Mostly non-Latin letters (Devanagari, Tamil, Arabic, …)   -> not supported
2. Several common Hinglish words, making up a good share     -> not supported
3. A longer review in which hardly any words are known English -> not supported
The Hinglish word list is hand-written plus 300 words taken from human-tagged
tweets (SentiMix train split; see scripts/build_hinglish_words.py).
Short English reviews ("Good", "Fast delivery") are always kept. How well this
works is measured in docs/PLAN.md, Phase 4, and its limits are listed there.
"""
import re
import unicodedata
from pathlib import Path

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

SUPPORTED = "analysed"
NOT_SUPPORTED = "language_not_supported"

# Frequent Hindi words as typed in Latin letters. Words that are also common in
# English reviews (me, to, par, so, band, tab, lie, hum, fir) are deliberately left out.
HINGLISH_WORDS = {
    "hai", "hain", "nahi", "nahin", "nhi", "nai", "bahut", "bohot", "bhot", "bahot", "accha", "acha",
    "achha", "achcha", "bekar", "bekaar", "bakwas", "bakwaas", "kya", "kyu", "kyun", "kyon", "ki", "ka", "ke",
    "ko", "se", "mein", "mai", "aur", "lekin", "magar", "yaar", "yar", "bhai", "mast", "ekdum", "sab", "kuch",
    "koi", "kaam", "karta", "karti", "karte", "kar", "karo", "raha", "rahi", "rahe", "gaya", "gayi", "hota",
    "hoti", "hote", "tha", "thi", "wala", "wali", "wale", "paisa", "paise", "bilkul", "sahi",
    "jaldi", "dikkat", "kharab", "ghatiya", "zabardast", "shandar", "shaandar", "bura", "achi", "acchi",
    "pasand", "chalta", "chalti", "baar", "kabhi", "abhi", "hamesha", "isko", "isme",
    "usme", "mujhe", "hame", "humko", "aap", "aapka", "apna", "apne", "liye", "diya", "diye",
    "mila", "mili", "milta", "kuchh", "bas", "sirf", "jab", "phir", "bohat",
    # common spelling variants
    "acche", "achhe", "acchha", "bht", "bhaut", "bhot", "krte", "krta", "kro", "rha", "rhi", "hy",
}
def _read_words(name: str) -> set[str]:
    """A generated word list in app/nlp/data/ (scripts/build_hinglish_words.py)."""
    path = Path(__file__).with_name("data") / name
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


# Plus 300 frequent Hindi words found in human-tagged tweets.
HINGLISH_WORDS |= _read_words("hinglish_words.txt")
# Words known to be English: VADER's dictionary, common stopwords and the review vocabularies. Telegraphic
# English reviews ("Really good app. Super fast delivery") have no stopwords, so stopwords alone aren't enough.
def _known_english() -> frozenset[str]:
    from .aspects import APP_ASPECTS, APP_CATEGORY_EXTRAS, PRODUCT_ASPECTS
    from .keywords import REVIEW_STOPWORDS
    from .sentiment import _analyzer

    vocabularies = [PRODUCT_ASPECTS, APP_ASPECTS, *APP_CATEGORY_EXTRAS.values()]
    terms = {w for vocabulary in vocabularies for words in vocabulary.values() for t in words for w in t.split()}
    lexicon = {w for w in _analyzer.lexicon if w.isalpha()}
    informal = _read_words("english_words.txt")  # everyday English from human-tagged tweets
    return frozenset(ENGLISH_STOP_WORDS | REVIEW_STOPWORDS | terms | lexicon | informal) - HINGLISH_WORDS


KNOWN_ENGLISH = _known_english()
MIN_ENGLISH_SHARE = 0.25
HINGLISH_MIN_WORDS = 2
HINGLISH_MIN_SHARE = 0.2

_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")


def _script_of(char: str) -> str | None:
    """'LATIN', 'DEVANAGARI', … for letters; None for digits, punctuation, emoji."""
    if not char.isalpha():
        return None
    name = unicodedata.name(char, "")
    return name.split(" ")[0] if name else None


def detect_language(text: str) -> dict:
    """Return {"status": "analysed" | "language_not_supported", "language": code, "reason": str | None}."""
    letters = [s for s in map(_script_of, text or "") if s]
    if letters:
        non_latin = [s for s in letters if s != "LATIN"]
        if len(non_latin) / len(letters) > 0.3:
            script = max(set(non_latin), key=non_latin.count).title()
            return {"status": NOT_SUPPORTED, "language": f"{script.lower()} script",
                    "reason": f"Written mainly in {script} script."}

    words = _WORD.findall((text or "").lower())
    hinglish = [w for w in words if w in HINGLISH_WORDS]
    if len(hinglish) >= HINGLISH_MIN_WORDS and len(hinglish) / len(words) >= HINGLISH_MIN_SHARE:
        return {"status": NOT_SUPPORTED, "language": "hinglish",
                "reason": "Looks like Hindi written in English letters (Hinglish)."}

    if len(words) >= 6 and sum(w in KNOWN_ENGLISH for w in words) / len(words) < MIN_ENGLISH_SHARE:
        return {"status": NOT_SUPPORTED, "language": "unknown",
                "reason": "Doesn’t look like English."}
    return {"status": SUPPORTED, "language": "en", "reason": None}
