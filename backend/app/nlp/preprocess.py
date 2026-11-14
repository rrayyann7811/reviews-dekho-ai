"""Text cleaning helpers shared by the sentiment, aspect and keyword steps."""
import math
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
# Split into clauses at sentence ends, semicolons and contrast words
# ("but", "though", "however"), because one sentence often holds two opinions:
# "Great battery, but the camera is poor."
_CLAUSE_SPLIT = re.compile(
    r"(?<=[.!?])\s+|\s*;\s*|,?\s+\bbut\b\s+|,?\s+\bthough\b\s*|,?\s*\bhowever\b,?\s*",
    flags=re.IGNORECASE,
)


def normalize_text(value) -> str:
    """Return a clean single-line string; missing values become ""."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return _WHITESPACE.sub(" ", text).strip()


_REPEATED_PUNCTUATION = re.compile(r"([!?.,])\1{3,}")


def tidy_for_analysis(text: str) -> str:
    """Text as given to the sentiment engines: "Good!!!!!!!!" -> "Good!!!".

    Only analysis input is tidied; the original review text is what users see
    and what is exported.
    """
    return _REPEATED_PUNCTUATION.sub(r"\1\1\1", normalize_text(text))


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def split_clauses(text: str) -> list[str]:
    """Split a review into short clauses that each tend to carry one opinion."""
    parts = _CLAUSE_SPLIT.split(normalize_text(text))
    return [p.strip(" ,.") for p in parts if p and p.strip(" ,.")]


def dedupe_key(text: str) -> str:
    """Lower-case, punctuation-free form used to spot duplicate review text."""
    return re.sub(r"[^a-z0-9 ]", "", normalize_text(text).lower())
