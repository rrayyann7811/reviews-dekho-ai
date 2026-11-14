"""Frequent keyword and phrase extraction.

Counts in how many reviews each word or two-word phrase appears (document
frequency). Phrases are only built from words that are next to each other
in the original text, and any word or phrase containing a stopword is
dropped. Uses scikit-learn's CountVectorizer with a small custom tokenizer.
"""
import re

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

# Words that appear in almost every review and say nothing specific.
REVIEW_STOPWORDS = {
    "phone", "product", "products", "app", "apps", "application", "good", "great", "nice", "best", "bad",
    "really", "bit", "please", "pls", "plz", "thanks", "thank", "ok", "okay", "don", "doesn", "didn", "isn",
    "won", "wasn", "ve", "ll", "im", "ive", "dont", "doesnt", "cant", "wont", "didnt", "isnt", "star", "stars",
    "okay", "overall", "bought", "buy", "use", "using", "used", "just", "like",
    "also", "would", "one", "even", "much", "got", "get", "expected", "far",
    "day", "time", "lot", "little", "slightly", "totally", "thing", "things",
    "lasts", "quality", "works", "feels", "makes", "takes", "came",
}
STOPWORDS = ENGLISH_STOP_WORDS | REVIEW_STOPWORDS
_WORD = re.compile(r"[a-z][a-z0-9]+")


def _make_terms(extra_stopwords: frozenset[str]):
    stop = STOPWORDS | extra_stopwords

    def terms(text: str) -> list[str]:
        """Single words plus adjacent two-word phrases, skipping stopwords."""
        words = _WORD.findall(text.lower())
        unigrams = [w for w in words if w not in stop and len(w) > 2]
        bigrams = [f"{a} {b}" for a, b in zip(words, words[1:])
                   if a not in ENGLISH_STOP_WORDS and b not in ENGLISH_STOP_WORDS
                   and a not in extra_stopwords and b not in extra_stopwords
                   and a not in {"phone", "app", "good", "great", "nice", "very"}]
        return unigrams + bigrams
    return terms


def name_stopwords(*names: str | None) -> frozenset[str]:
    """Words of the product's own name and brand ("WhatsApp Messenger" -> whatsapp, messenger).

    They appear in a large share of reviews and say nothing about what people think.
    """
    return frozenset(w for name in names if name for w in _WORD.findall(name.lower()) if len(w) > 2)


def extract_keywords(texts: list[str], top_n: int = 15, min_reviews: int = 2,
                     extra_stopwords: frozenset[str] = frozenset()) -> list[dict]:
    """Return the most common terms as [{"term": str, "reviews": int}]."""
    texts = [t for t in texts if t]
    if len(texts) < min_reviews:
        return []
    vectorizer = CountVectorizer(analyzer=_make_terms(extra_stopwords), min_df=min_reviews, binary=True)
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:  # every word was filtered out
        return []
    counts = dict(zip(vectorizer.get_feature_names_out(), matrix.sum(axis=0).A1))

    # Drop a single word when a phrase containing it accounts for most of its
    # uses, e.g. keep "build quality" and drop "build".
    phrases = {t: c for t, c in counts.items() if " " in t}
    for word in [t for t in counts if " " not in t]:
        if any(word in p.split() and c >= 0.8 * counts[word] for p, c in phrases.items()):
            del counts[word]

    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [{"term": term, "reviews": int(count)} for term, count in ranked[:top_n]]
