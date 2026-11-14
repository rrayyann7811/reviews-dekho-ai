"""Checks an AI-written overview against the evidence package it was given.

Every sentence must cite the claims (C1, C2… or O for the overview figures)
and excerpts (E1, E2…) it relies on. A sentence is rejected when:

1. it cites nothing, cites an ID that isn't in the package, or cites an excerpt
   that belongs to a claim the sentence doesn't cite (evidence for something else);
2. it contains a number that doesn't appear in the cited evidence;
3. it quotes text that isn't a verbatim part of a cited excerpt;
4. it names a feature that isn't one of the cited claims;
5. it praises a feature the evidence calls a complaint, or the reverse, or
   states an overall tone different from the computed one;
6. it generalises the sample to all customers ("most customers", "everyone");
7. it contains markup or links, or the answer has too many / too long sentences.

These rules catch common, *detectable* errors. They are not a guarantee: a
sentence can pass every check and still be misleading (for example by
emphasising a minor point), which is why the overview is labelled as AI-written
and shown next to — never instead of — the evidence-backed summary.
"""
import re

from ..nlp.aspects import APP_ASPECTS, APP_CATEGORY_EXTRAS, PRODUCT_ASPECTS

MAX_SENTENCES = 6
MAX_SENTENCE_CHARS = 320

FEATURE_NAMES = sorted({name for vocabulary in (PRODUCT_ASPECTS, APP_ASPECTS, *APP_CATEGORY_EXTRAS.values())
                        for name in vocabulary}, key=len, reverse=True)
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# Double quotes, curly or straight; single quotes too, allowing apostrophes inside words ("can't").
_QUOTE = re.compile(r"“([^”]{3,})”|\"([^\"]{3,})\"|‘((?:[^’]|(?<=\w)’(?=\w)){3,})’"
                    r"|(?<!\w)'((?:[^']|(?<=\w)'(?=\w)){3,})'(?!\w)")
_NEGATIVE_WORDS = re.compile(r"\b(complain\w*|criticis\w*|criticiz\w*|negative\w*|poor\w*|bad|worst|disappoint\w*|"
                             r"problem\w*|issue\w*|dislike\w*|weak\w*|terribl\w*|frustrat\w*)\b", re.I)
_POSITIVE_WORDS = re.compile(r"\b(prais\w*|positive\w*|like[sd]?|lov\w*|great|excellent|good|strength\w*|best|"
                             r"impress\w*|satisf\w*|happy)\b", re.I)
_GENERALISATION = re.compile(r"\b(all|every|most|many|the majority of)\s+(customers|users|buyers|people|owners|"
                             r"shoppers)\b|\beveryone\b|\b(customers|users|people)\s+(think|agree|feel|say|believe)\b",
                             re.I)
_TONE = re.compile(r"\bmostly\s+(positive|negative|neutral)\b", re.I)
# Citation markers the model sometimes writes inside its text: "(C1)", "(claims C5 and C6)", "(O)".
_CITATION_GROUP = re.compile(r"\s*\((?:(?:claims?|excerpts?)\s+)?(?:[CE]\d+|O)(?:\s*(?:,|and|&)\s*(?:[CE]\d+|O))*\)")
_CITATION_ID = re.compile(r"\b[CE]\d+\b")


def strip_citations(text: str) -> str:
    """Remove citation markers from a sentence (they are shown separately, as chips)."""
    return " ".join(_CITATION_GROUP.sub("", text).split())


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in _NUMBER.findall(text)]


def check_overview(answer, package: dict) -> list[str]:
    """Return a list of problems (empty when every check passes)."""
    if not isinstance(answer, dict) or not isinstance(answer.get("sentences"), list):
        return ["The answer isn’t the requested JSON object with a “sentences” list."]
    sentences = answer["sentences"]
    if not 1 <= len(sentences) <= MAX_SENTENCES:
        return [f"The answer must have between 1 and {MAX_SENTENCES} sentences (it has {len(sentences)})."]

    claims = {c["id"]: c for c in package["claims"]}
    excerpts = {e["id"]: e for c in package["claims"] for e in c["excerpts"]}
    claim_of_excerpt = {e["id"]: c["id"] for c in package["claims"] for e in c["excerpts"]}
    # Models sometimes cite an excerpt by its text instead of its ID; accept only an exact match.
    excerpt_ids_by_text = {_norm(e["text"]): e["id"] for e in excerpts.values()}
    overview = package["overview"]
    problems = []
    for number, sentence in enumerate(sentences, start=1):
        where = f"Sentence {number}"
        if not isinstance(sentence, dict) or not isinstance(sentence.get("text"), str):
            problems.append(f"{where} isn’t an object with a “text” field.")
            continue
        text = sentence["text"].strip()
        cited_claims = [c.strip() for c in sentence.get("claims") or [] if isinstance(c, str) and c.strip()]
        cited_excerpts = []
        for e in sentence.get("excerpts") or []:
            if isinstance(e, str) and e.strip():
                cited_excerpts.append(excerpt_ids_by_text.get(_norm(e.strip(" \"“”")), e.strip()))
        sentence["claims"], sentence["excerpts"] = cited_claims, cited_excerpts  # normalised for display

        if not text:
            problems.append(f"{where} is empty.")
            continue
        if len(text) > MAX_SENTENCE_CHARS:
            problems.append(f"{where} is longer than {MAX_SENTENCE_CHARS} characters.")
        if re.search(r"[<>]|https?://|www\.", text):
            problems.append(f"{where} contains markup or a link.")

        # 1. Citations
        unknown = [c for c in cited_claims if c != "O" and c not in claims] + [e for e in cited_excerpts if e not in excerpts]
        if unknown:
            problems.append(f"{where} cites IDs that don’t exist: {', '.join(unknown)}.")
        known_claims = [claims[c] for c in cited_claims if c in claims]
        if not known_claims and "O" not in cited_claims:
            problems.append(f"{where} doesn’t cite any claim (C…) or the overview (O).")
        misattributed = [e for e in cited_excerpts if e in claim_of_excerpt and claim_of_excerpt[e] not in cited_claims]
        if misattributed:
            problems.append(f"{where} cites excerpts that support a different claim: {', '.join(misattributed)}.")

        # 3. Quotes must be verbatim parts of cited excerpts (checked before numbers, which may appear in quotes)
        quoted = [next(part for part in groups if part) for groups in _QUOTE.findall(text)]
        cited_texts = [_norm(excerpts[e]["text"]) for e in cited_excerpts if e in excerpts]
        for quote in quoted:
            if not any(_norm(quote) in source for source in cited_texts):
                problems.append(f"{where} quotes text that isn’t in the cited excerpts: “{quote}”.")
        # Citation markers like "(C1)" are not part of the claim: their digits aren't numbers to check.
        unquoted = _CITATION_ID.sub(" ", _CITATION_GROUP.sub(" ", _QUOTE.sub(" ", text)))

        # 2. Numbers must come from the cited evidence
        allowed = {5.0}  # "out of 5"
        if "O" in cited_claims:
            allowed |= set(overview["numbers"])
        for claim in known_claims:
            allowed |= set(claim["numbers"])
        invented = [n for n in _numbers(unquoted) if round(n, 1) not in {round(a, 1) for a in allowed}]
        if invented:
            shown = ", ".join(f"{n:g}" for n in invented)
            problems.append(f"{where} uses numbers that aren’t in the cited evidence: {shown}.")

        # 4. Features must be cited
        cited_features = {c["aspect"].lower() for c in known_claims}
        lowered = unquoted.lower()
        for name in FEATURE_NAMES:  # longest first, so "Orders & delivery" is matched before "Delivery"
            pattern = rf"(?<![\w-]){re.escape(name.lower())}(?![\w-])"
            if re.search(pattern, lowered):
                if name.lower() not in cited_features:
                    problems.append(f"{where} mentions “{name}” without citing a claim about it.")
                lowered = re.sub(pattern, " ", lowered)  # remove it so shorter names inside it aren't matched again

        # 5. Direction must match the evidence. Only checked when the sentence is about features of one kind
        # (with the overall figures also cited, words like "negative" may refer to those instead).
        kinds = {c["kind"] for c in known_claims}
        about_overall = "O" in cited_claims
        if not about_overall and kinds == {"strength"} and _NEGATIVE_WORDS.search(unquoted):
            problems.append(f"{where} describes a strength negatively.")
        if not about_overall and kinds == {"complaint"} and _POSITIVE_WORDS.search(unquoted):
            problems.append(f"{where} describes a complaint positively.")
        tone = _TONE.search(unquoted) if about_overall else None  # "packaging is mostly negative" is about a feature
        majority = overview.get("majority", True)
        if tone and (tone.group(1).lower() != overview["lead"] or not majority):
            if overview["lead"] == "split":
                actual = "it is split (no majority)"
            elif not majority:
                actual = f"{overview['lead']} is only the most common tone, not a majority"
            else:
                actual = f"it is mostly {overview['lead']}"
            problems.append(f"{where} says the tone is mostly {tone.group(1).lower()}, but {actual}.")

        # 6. No generalising from reviewers to all customers
        if _GENERALISATION.search(unquoted):
            problems.append(f"{where} generalises the sample to all customers; say “reviewers in this sample”.")
    return problems
