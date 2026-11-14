"""Review-specific rules that help the rule-based VADER engine.

VADER scores words from a general-purpose dictionary. Measured on real review
phrases (docs/PLAN.md, Phase 4), it gets these wrong:

    "The app is not working"           -> neutral   ("working" has no score)
    "keeps crashing", "can't log in"   -> neutral
    "Customer support never responds"  -> POSITIVE  ("support" is a positive word)
    "No issues at all"                 -> NEGATIVE  ("issues" is negative)
    "Too many ads", "👍", "Goooood"    -> neutral

The fixes below are small and readable:
1. PHRASE_RULES rewrite a few unambiguous phrases into one word VADER knows
   ("keeps crashing" -> "fails"). Only the text VADER scores is rewritten; the
   review shown to the user and exported is never changed.
2. DOMAIN_LEXICON adds review words VADER's dictionary lacks.
3. EMOJI_WORDS turns a few common emoji VADER can't score into words.

The transformer engine does not use these rules: it reads the original text.
"""
import re

DOMAIN_LEXICON = {
    # physical products
    "drains": -1.5, "drain": -1.2, "lag": -1.5, "lags": -1.5, "lagging": -1.8,
    "laggy": -1.8, "heats": -1.2, "overheating": -2.0, "grainy": -1.5,
    "blurry": -1.5, "bloatware": -1.5, "overpriced": -2.0, "defective": -2.5,
    "scratched": -1.5, "crushed": -1.5, "torn": -1.5, "stutter": -1.2, "sluggish": -1.5,
    "crisp": 1.5, "vibrant": 1.5, "smooth": 1.5, "sturdy": 1.3,
    # apps and software
    "crash": -2.0, "crashes": -2.0, "crashing": -2.0, "crashed": -2.0,
    "freeze": -1.8, "freezes": -1.8, "freezing": -1.8, "frozen": -1.5, "hangs": -1.5,
    "bug": -1.3, "bugs": -1.5, "buggy": -1.8, "glitch": -1.5, "glitches": -1.5, "glitchy": -1.8,
    "unresponsive": -1.8, "slow": -1.3, "slower": -1.3, "spam": -1.5, "spammy": -1.8,
    "unusable": -2.5, "uninstall": -1.5, "uninstalled": -1.5, "uninstalling": -1.5,
    # replacement words used by PHRASE_RULES
    "fails": -2.0, "flawless": 2.2,
}

# Applied in order, case-insensitive. "fails" / "flawless" carry the score (see DOMAIN_LEXICON).
_NEG_VERB = r"(?:not|isn'?t|is not|aren'?t|are not|doesn'?t|does not|don'?t|do not|won'?t|will not|didn'?t|did not|never|stopped)"
PHRASE_RULES = [
    # "not working", "doesn't open", "stopped loading", "never responds"
    (re.compile(rf"\b{_NEG_VERB}\s+(?:even\s+)?(?:work|works|working|worked|load|loads|loading|open|opens|opening|"
                r"respond|responds|responding|responded|reply|replies|replied|function|functioning|start|starts|"
                r"arrive|arrives|arrived|deliver|delivered|sync|syncing|connect|connecting)\b", re.I), "fails"),
    # "keeps crashing", "keep logging me out"
    (re.compile(r"\bkeeps?\s+(?:on\s+)?(?:crashing|freezing|hanging|lagging|buffering|loading|closing|"
                r"logging (?:me )?out|signing (?:me )?out|stopping)\b", re.I), "fails"),
    # "can't log in", "unable to pay", "not able to open"
    (re.compile(r"\b(?:can'?t|cannot|can not|couldn'?t|could not|unable to|not able to)\s+(?:even\s+)?"
                r"(?:log ?in|login|sign ?in|sign ?up|signup|register|pay|open|access|use|connect|order|book|"
                r"upload|download|update|install|verify|see|find|load|send|receive|contact|reach|make|place|complete|"
                r"get|play|watch|withdraw|transfer|add|change|reset|delete|cancel|track)\b", re.I), "fails"),
    # "no response", "zero help"
    (re.compile(r"\b(?:no|zero)\s+(?:response|reply|replies|help|refund|resolution|solution)\b", re.I), "fails"),
    # "too many ads", "full of bugs"
    (re.compile(r"\b(?:too many|so many|way too many|lots of|tons of|full of|loads of)\s+"
                r"(?:ads|adverts|advertisements|bugs|glitches|popups|pop-ups|notifications)\b", re.I), "fails"),
    # "no issues", "without any problems", "never had any lag"
    (re.compile(r"\b(?:no|zero|without any|without|never had any|not a single)\s+"
                r"(?:issues?|problems?|complaints?|bugs?|lag|glitch(?:es)?|crash(?:es)?)\b", re.I), "flawless"),
]

EMOJI_WORDS = {"👍": " good ", "👎": " bad ", "💯": " perfect ", "🤬": " angry ", "🙄": " annoying "}

_REPEATED_LETTERS = re.compile(r"([a-z])\1{2,}", re.I)


def squeeze_letters(text: str, known_words) -> str:
    """'goooood' -> 'good', 'sooooo' -> 'so': shorten stretched words to a known spelling."""
    def fix(word_match):
        word = word_match.group(0)
        if not _REPEATED_LETTERS.search(word):
            return word
        double = _REPEATED_LETTERS.sub(r"\1\1", word)
        if double.lower() in known_words:
            return double
        single = _REPEATED_LETTERS.sub(r"\1", word)
        return single if single.lower() in known_words else double
    return re.sub(r"[A-Za-z]+", fix, text)


def rewrite_for_vader(text: str, known_words) -> str:
    for emoji, word in EMOJI_WORDS.items():
        text = text.replace(emoji, word)
    text = squeeze_letters(text, known_words)
    for pattern, replacement in PHRASE_RULES:
        text = pattern.sub(replacement, text)
    return text
