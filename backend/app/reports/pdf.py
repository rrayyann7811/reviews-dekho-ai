"""PDF report for ONE stored analysis run.

Everything in the report comes from the selected run's stored snapshot (stats,
features, summary and per-review results) plus the product's source details,
so historical and current results are never mixed. Only aggregates and a few
representative excerpts are included — never the full review list — and
reviewer names are left out: excerpts are identified by review ID.

Built with ReportLab: text in DejaVu Sans (fonts/LICENSE), charts drawn as
vector shapes, "Page X of Y" footers.
"""
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

from ..models import AnalysisResult, Product
from ..services.review_query import tone_by_rating

# ---------- Fonts and colours ----------

FONT_DIR = Path(__file__).with_name("fonts")
pdfmetrics.registerFont(TTFont("DejaVuSans", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold",
                              italic="DejaVuSans", boldItalic="DejaVuSans-Bold")
_GLYPHS = pdfmetrics.getFont("DejaVuSans").face.charToGlyph
MISSING_GLYPH = "□"

# Same colours as the web app (frontend/src/index.css).
INK, INK_2, INK_3 = colors.HexColor("#1b1c1e"), colors.HexColor("#4b4e54"), colors.HexColor("#686c73")
LINE, SUBTLE, TRACK = colors.HexColor("#e6e6e2"), colors.HexColor("#f9f9f8"), colors.HexColor("#ecece8")
BRAND, BRAND_SOFT = colors.HexColor("#22577a"), colors.HexColor("#eef4f8")
SENTIMENT_COLOURS = {"positive": colors.HexColor("#2d7a4e"), "neutral": colors.HexColor("#8a8f98"),
                     "negative": colors.HexColor("#b4321f"), "mixed": colors.HexColor("#9a5b06")}

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
CELL_PADDING = 5  # left and right padding of table cells (points)

_base = dict(fontName="DejaVuSans", textColor=INK, leading=13, fontSize=9.5)
STYLES = {
    "kicker": ParagraphStyle("kicker", **_base | dict(fontSize=8.5, textColor=BRAND, leading=11)),
    "title": ParagraphStyle("title", **_base | dict(fontName="DejaVuSans-Bold", fontSize=19, leading=24)),
    "h2": ParagraphStyle("h2", **_base | dict(fontName="DejaVuSans-Bold", fontSize=12.5, leading=16,
                                               spaceBefore=12, spaceAfter=5)),
    "h3": ParagraphStyle("h3", **_base | dict(fontName="DejaVuSans-Bold", fontSize=10, leading=13, spaceBefore=6)),
    "group": ParagraphStyle("group", **_base | dict(fontName="DejaVuSans-Bold", fontSize=11, leading=14,
                                                     spaceBefore=12, spaceAfter=4, textColor=INK)),
    "body": ParagraphStyle("body", **_base),
    "muted": ParagraphStyle("muted", **_base | dict(textColor=INK_2, fontSize=8.5, leading=11.5)),
    "small": ParagraphStyle("small", **_base | dict(textColor=INK_3, fontSize=7.5, leading=10)),
    "quote": ParagraphStyle("quote", **_base | dict(textColor=INK_2, fontSize=8.8, leading=12, leftIndent=9)),
    "cell": ParagraphStyle("cell", **_base | dict(fontSize=8.5, leading=11)),
    "cell_bold": ParagraphStyle("cell_bold", **_base | dict(fontName="DejaVuSans-Bold", fontSize=8.5, leading=11)),
    "figure": ParagraphStyle("figure", **_base | dict(fontName="DejaVuSans-Bold", fontSize=15, leading=18)),
}


# ---------- Text helpers ----------

class _Text:
    """Makes any value safe for ReportLab paragraphs and remembers whether characters were replaced."""

    def __init__(self):
        self.replaced = False

    def __call__(self, value) -> str:
        text = "" if value is None else str(value)
        safe = []
        for char in text:
            if ord(char) in _GLYPHS or char in "\n\t":
                safe.append(char)
            else:
                safe.append(MISSING_GLYPH)
                self.replaced = True
        # Paragraph text is parsed as markup, so "<", ">" and "&" from reviews must be escaped.
        return escape("".join(safe))


def _date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
    return f"{value.day} {value.strftime('%b %Y')}"


def _pct(value) -> str:
    return "—" if value is None else f"{value:.1f}".rstrip("0").rstrip(".") + "%"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


# ---------- Charts (vector) ----------

def _bar_chart(rows: list[tuple[str, int, colors.Color, str]], width: float) -> Drawing:
    """Horizontal bars: (label, value, colour, value text). Zero rows keep their track and label."""
    row_h, label_w, value_w = 15, 62, 78
    bar_w = width - label_w - value_w
    top = max((value for _, value, _, _ in rows), default=0) or 1
    drawing = Drawing(width, row_h * len(rows))
    for i, (label, value, colour, value_text) in enumerate(rows):
        y = row_h * (len(rows) - 1 - i)
        drawing.add(String(label_w - 6, y + 4, label, fontName="DejaVuSans", fontSize=8, fillColor=INK_2,
                           textAnchor="end"))
        drawing.add(Rect(label_w, y + 3, bar_w, 8, fillColor=TRACK, strokeColor=None))
        if value:
            drawing.add(Rect(label_w, y + 3, bar_w * value / top, 8, fillColor=colour, strokeColor=None))
        drawing.add(String(label_w + bar_w + 6, y + 4, value_text, fontName="DejaVuSans", fontSize=8, fillColor=INK_2))
    return drawing


def _split_bar(positive: int, neutral: int, negative: int, width: float, height: float = 7) -> Drawing:
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=TRACK, strokeColor=None))
    total, x = positive + neutral + negative, 0.0
    for value, key in ((positive, "positive"), (neutral, "neutral"), (negative, "negative")):
        if total and value:
            w = width * value / total
            drawing.add(Rect(x, 0, w, height, fillColor=SENTIMENT_COLOURS[key], strokeColor=None))
            x += w
    return drawing


def _table(data, col_widths, header=True, zebra=False) -> Table:
    table = Table(data, colWidths=col_widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), CELL_PADDING),
             ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PADDING), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), SUBTLE), ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE)]
    table.setStyle(TableStyle(style))
    return table


# ---------- Page furniture ----------

class _NumberedCanvas(Canvas):
    """Draws "Page X of Y" once the total number of pages is known."""

    footer_text = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("DejaVuSans", 7.5)
            self.setFillColor(INK_3)
            self.drawString(MARGIN, 10 * mm, self.footer_text)
            self.drawRightString(PAGE_W - MARGIN, 10 * mm, f"Page {self._pageNumber} of {total}")
            self.setStrokeColor(LINE)
            self.setLineWidth(0.5)
            self.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
            super().showPage()
        super().save()


# ---------- Content ----------

def _source_lines(product: Product, run: AnalysisResult, t: _Text) -> list[tuple[str, str]]:
    ingestion = run.ingestion or {}
    if product.source == "url":
        region = f" ({(product.source_region or '').upper()} store)" if product.source_region else ""
        source = f"Collected from {ingestion.get('source') or 'a product link'}{region}"
        lines = [("Source", t(source)), ("Link", t(product.source_url or "—")),
                 ("Collected", t(_date(ingestion.get("collectedAt") or product.collected_at)))]
        if isinstance(ingestion.get("storeRating"), (int, float)) and ingestion.get("storeRatingCount"):
            lines.append(("Store rating", t(f"{ingestion['storeRating']:.1f} / 5 from {ingestion['storeRatingCount']:,} "
                                            "ratings — the store’s own overall figure, not part of this analysis")))
    elif product.source == "upload":
        lines = [("Source", t(f"Uploaded file: {product.file_name or ingestion.get('fileName') or '—'}"))]
    else:
        lines = [("Source", "Reviews added manually")]
    return lines


def _figures(stats: dict) -> Table:
    total = stats["totalReviews"]
    analysed = stats.get("analysedReviews", total)
    excluded = (stats.get("notAnalysed") or {}).get("languageNotSupported", total - analysed)
    pct, counts = stats["sentimentPercent"], stats["sentimentCounts"]
    measurable = analysed > 0

    def cell(label, value, detail):
        return [Paragraph(label, STYLES["small"]), Paragraph(value, STYLES["figure"]), Paragraph(detail, STYLES["small"])]

    row = [
        cell("Reviews analysed", f"{analysed:,}", f"of {total:,} in this run"),
        cell("Not analysed", f"{excluded:,}", "not in English"),
        cell("Average star rating", "—" if stats.get("averageRating") is None else f"{stats['averageRating']:.1f} / 5",
             f"from {_plural(stats.get('ratedReviews', 0), 'rated review')}"),
        cell("Positive", _pct(pct["positive"]) if measurable else "—", f"{counts['positive']:,} of {analysed:,}"),
        cell("Neutral", _pct(pct["neutral"]) if measurable else "—", f"{counts['neutral']:,} of {analysed:,}"),
        cell("Negative", _pct(pct["negative"]) if measurable else "—", f"{counts['negative']:,} of {analysed:,}"),
    ]
    table = Table([row[:3], row[3:]], colWidths=[CONTENT_W / 3] * 3, hAlign="LEFT")
    table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return table


def _distribution(stats: dict) -> list:
    analysed = stats.get("analysedReviews", stats["totalReviews"])
    rated = stats.get("ratedReviews", 0)
    half = (CONTENT_W - 8 * mm) / 2
    if analysed:
        sentiment = _bar_chart([(label, stats["sentimentCounts"][key], SENTIMENT_COLOURS[key],
                                 f"{stats['sentimentCounts'][key]:,} · {_pct(stats['sentimentPercent'][key])}")
                                for key, label in (("positive", "Positive"), ("neutral", "Neutral"),
                                                   ("negative", "Negative"))], half)
    else:
        sentiment = Paragraph("No review could be analysed for tone (none is in English).", STYLES["muted"])
    if rated:
        stars = _bar_chart([(f"{r['stars']} star{'s' if r['stars'] > 1 else ''}", r["count"], BRAND,
                             f"{r['count']:,} · {_pct(100 * r['count'] / rated)}") for r in stats["ratingDistribution"]],
                           half)
    else:
        stars = Paragraph("This data has no star ratings.", STYLES["muted"])
    grid = Table([[Paragraph("<b>Tone of the review text</b>", STYLES["cell"]),
                   Paragraph("<b>Star ratings</b>", STYLES["cell"])],
                  [Paragraph(f"How the wording of the {analysed:,} analysed reviews reads." if analysed else
                             "Only reviews in English are analysed for tone.", STYLES["small"]),
                   Paragraph(f"{rated:,} of {stats['totalReviews']:,} reviews have a star rating.", STYLES["small"])],
                  [sentiment, stars]], colWidths=[half + 4 * mm, half + 4 * mm], hAlign="LEFT")
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 1), (-1, 1), 6)]))
    return [grid, Spacer(1, 4),
            Paragraph("Star ratings and text sentiment are measured separately: the stars are what reviewers chose; "
                      "the tone is estimated from their wording.", STYLES["small"])]


def _tone_by_rating(reviews: list | None) -> list:
    if reviews is None:
        return [Paragraph("This run was stored without per-review results, so tone by star rating isn’t available.",
                          STYLES["muted"])]
    rows = [r for r in tone_by_rating(reviews) if r["reviews"]]
    if not rows:
        return []
    bar_w = CONTENT_W - 30 * mm - 52 * mm
    data = [[Paragraph("Rating", STYLES["cell_bold"]), Paragraph("Tone of the text", STYLES["cell_bold"]),
             Paragraph("Positive / neutral / negative", STYLES["cell_bold"])]]
    for r in rows:
        extra = f" · {r['notAnalysed']} not analysed" if r["notAnalysed"] else ""
        data.append([Paragraph(f"{r['stars']} star{'s' if r['stars'] > 1 else ''}", STYLES["cell"]),
                     _split_bar(r["positive"], r["neutral"], r["negative"], bar_w - 10),
                     Paragraph(f"{r['positive']} / {r['neutral']} / {r['negative']}{extra}", STYLES["cell"])])
    return [Paragraph("Tone of the text by star rating", STYLES["h3"]), Spacer(1, 3),
            _table(data, [30 * mm, bar_w, 52 * mm])]


FEATURE_HEADERS = ["Feature", "Reviews", "Positive", "Neutral", "Negative", "Split", "Overall"]
FEATURE_SPLIT_W = 30 * mm


def feature_columns() -> list[float]:
    """Column widths for the feature table. Number columns are sized so their bold header never wraps."""
    header_w = max(pdfmetrics.stringWidth(h, "DejaVuSans-Bold", 8.5) for h in FEATURE_HEADERS[1:5])
    number_w = header_w + 2 * CELL_PADDING + 2
    widths = [40 * mm] + [number_w] * 4 + [FEATURE_SPLIT_W]
    return widths + [CONTENT_W - sum(widths)]


def _features(aspects: list[dict], t: _Text) -> list:
    if not aspects:
        return [Paragraph("No known features were mentioned in the analysed reviews.", STYLES["muted"])]
    widths, head, split_w = feature_columns(), FEATURE_HEADERS, FEATURE_SPLIT_W
    data = [[Paragraph(h, STYLES["cell_bold"]) for h in head]]
    verdicts = {"positive": "Positive", "negative": "Negative", "mixed": "Mixed", "insufficient": "Too few"}
    for a in aspects:
        colour = SENTIMENT_COLOURS.get(a["verdict"], INK_3).hexval()[2:]
        data.append([Paragraph(t(a["aspect"]), STYLES["cell"]), Paragraph(f"{a['mentions']:,}", STYLES["cell"]),
                     Paragraph(f"{a['positive']:,}", STYLES["cell"]), Paragraph(f"{a['neutral']:,}", STYLES["cell"]),
                     Paragraph(f"{a['negative']:,}", STYLES["cell"]),
                     _split_bar(a["positive"], a["neutral"], a["negative"], split_w - 10),
                     Paragraph(f'<font color="#{colour}">{verdicts.get(a["verdict"], a["verdict"])}</font>',
                               STYLES["cell"])])
    return [_table(data, widths),
            Spacer(1, 4),
            Paragraph("Reviews = analysed reviews that mention the feature. A review counts once per feature it "
                      "mentions; one review can mention several features. "
                      "“Overall” needs at least 3 mentions and 65% in one direction, otherwise it is Mixed.",
                      STYLES["small"])]


def _claim_block(claim: dict, version: int, t: _Text, direction: str) -> KeepTogether:
    if version >= 2:
        statement = claim["statement"]
        evidence = claim.get("evidence") or []
    else:  # summary version 1: no stored statement; describe the stored counts only
        statement = (f"{claim['aspect']}: {claim['count']} of {claim['mentions']} mentions {direction} "
                     f"({claim['percent']}%).")
        evidence = [claim["example"]] if claim.get("example") else []
    parts = [Paragraph(f"<b>{t(claim['aspect'])}</b>", STYLES["body"]), Paragraph(t(statement), STYLES["muted"])]
    for e in evidence:
        meta = [f"Review {t(e['reviewId'])}"]
        if e.get("rating"):
            meta.append(f"{e['rating']}★")
        if e.get("date"):
            meta.append(_date(e["date"]))
        if e.get("sentiment"):
            meta.append(e["sentiment"])
        if e.get("field") == "title":
            meta.append("from the review title")
        colour = SENTIMENT_COLOURS.get(e.get("sentiment"), INK_3).hexval()[2:]
        parts.append(Paragraph(f'<font color="#{colour}">▍</font>“{t(e["text"])}” '
                               f'<font size="7.5" color="#686c73">— {" · ".join(meta)}</font>', STYLES["quote"]))
    parts.append(Spacer(1, 6))
    return KeepTogether(parts)


def _summary(summary: dict, t: _Text) -> list:
    version = summary.get("version", 1)
    if not summary.get("overview"):
        # Too few analysed reviews: say so once (the notes explain why) instead of empty claim groups.
        return [Paragraph("There are too few analysed reviews for a summary.", STYLES["body"])]
    out = []
    if summary.get("overview"):
        out.append(Paragraph(t(summary["overview"]), STYLES["body"]))
    for key, title, tone in (("strengths", "What reviewers like", "positive"),
                             ("complaints", "Common complaints", "negative"), ("mixed", "Mixed opinions", "mixed")):
        claims = summary.get(key) or []
        colour = SENTIMENT_COLOURS[tone].hexval()[2:]
        out.append(Paragraph(f'<font color="#{colour}">●</font> {title}', STYLES["group"]))
        if not claims:
            empty = {"strengths": "No feature is clearly praised by most of the reviews that mention it.",
                     "complaints": "No feature is criticised by most of the reviews that mention it.",
                     "mixed": "No features with clearly divided opinions."}[key]
            out.append(Paragraph(empty, STYLES["muted"]))
        # Version 1 stored strengths with positive counts and the other groups with negative counts.
        out += [_claim_block(c, version, t, "positive" if key == "strengths" else "negative") for c in claims]
    if version < 2:
        out.append(Paragraph("This run was made with summary version 1 (one example per feature). Re-analyse the "
                             "product to get the evidence-backed version.", STYLES["small"]))
    return out


def _method(run: AnalysisResult, product: Product, t: _Text) -> list:
    engine = run.engine or {}
    if engine.get("id") == "transformer":
        sentiment = ("Pretrained model cardiffnlp/twitter-roberta-base-sentiment-latest (RoBERTa-base, 3 classes; "
                     "Loureiro et al., TimeLMs, ACL 2022; licensed CC BY 4.0), run locally as an int8 ONNX "
                     "conversion published by Xenova. Each review gets the model’s most likely label.")
    else:
        sentiment = ("VADER, a rule-based sentiment method (Hutto & Gilbert, ICWSM 2014), with extra rules for "
                     "review phrases.")
        if engine.get("pipelineVersion", 1) < 2:
            sentiment += " This run was made with the earlier (version 1) pipeline."
    if engine.get("fallbackReason"):
        sentiment += f" Note: {engine['fallbackReason']}"
    features = ("mobile-app features (login, crashes, speed, updates, ads, design, notifications, payments, "
                "support, privacy)" if product.domain == "app" else
                "product features (battery, camera, display, performance, build, price, delivery, packaging, service)")
    rows = [
        ("Sentiment", sentiment),
        ("Features", f"Keyword lists for {features}. Each feature is scored on the clause around its mention, not "
                     "on the whole review."),
        ("Language", "Reviews that look non-English (other scripts, Hinglish, other languages) are not analysed and "
                     "are left out of the percentages; their star ratings still count."),
        ("Summary", f"Built from the stored numbers and exact excerpts (summary version "
                    f"{(run.summary or {}).get('version', 1)}). No language model wrote this report."),
        ("Versions", f"Analysis pipeline version {engine.get('pipelineVersion', 1)}."),
    ]
    data = [[Paragraph(k, STYLES["cell_bold"]), Paragraph(t(v), STYLES["cell"])] for k, v in rows]
    return [_table(data, [28 * mm, CONTENT_W - 28 * mm], header=False)]


def _limitations(run: AnalysisResult, product: Product, stats: dict) -> list:
    analysed = stats.get("analysedReviews", stats["totalReviews"])
    items = [f"The figures describe the {analysed:,} analysed reviews in this run, not every customer of the product. "
             "People who write reviews are not a random sample of customers."]
    if product.source == "url" and product.source_site == "apple_app_store":
        items.append("Apple’s public feed lists at most the 500 most recent written reviews per country store, so "
                     "older reviews and other countries are not included.")
    excluded = (stats.get("notAnalysed") or {}).get("languageNotSupported", 0)
    if excluded:
        items.append(f"{excluded:,} reviews not in English were not analysed for tone.")
    if analysed < 30:
        items.append(f"Small sample ({analysed} analysed reviews): percentages can change a lot with a few reviews.")
    if stats.get("ratingSentimentMismatches"):
        items.append(f"{len(stats['ratingSentimentMismatches']):,} reviews have a star rating that disagrees with the "
                     "tone of their text; neither is treated as more reliable.")
    items += ["Sentiment is estimated automatically and can misread sarcasm, very short reviews and mixed opinions.",
              "Features are found by keywords, so features described in other words are missed."]
    return [Paragraph(f"• {escape(i)}", STYLES["muted"]) for i in items]


# ---------- Report ----------

def _story(product: Product, run: AnalysisResult, generated_at: datetime) -> list:
    """The report's content, as ReportLab flowables."""
    t = _Text()
    stats = run.stats
    latest = product.latest_analysis
    run_note = ("latest run" if latest is None or latest.id == run.id
                else f"earlier run — a newer run (#{latest.id}) exists")

    story = [
        Paragraph("REVIEWS DEKHO AI · REVIEW ANALYSIS REPORT", STYLES["kicker"]),
        Spacer(1, 3),
        Paragraph(t(product.name), STYLES["title"]),
    ]
    subtitle = " · ".join(t(v) for v in (product.brand, product.category) if v)
    if subtitle:
        story.append(Paragraph(subtitle, STYLES["muted"]))
    story.append(Spacer(1, 8))
    meta = _source_lines(product, run, t) + [
        ("Analysis run", t(f"#{run.id} · analysed {_date(run.created_at)} · {run_note}")),
        ("Reviews dated", t(f"{_date(stats['dateRange']['from'])} to {_date(stats['dateRange']['to'])}")
         if stats.get("dateRange") else "—"),
        ("Report generated", t(_date(generated_at))),
    ]
    meta_table = _table([[Paragraph(k, STYLES["cell_bold"]), Paragraph(v, STYLES["cell"])] for k, v in meta],
                        [38 * mm, CONTENT_W - 38 * mm], header=False)
    meta_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND_SOFT), ("LINEBELOW", (0, 0), (-1, -1), 0,
                                                                                   BRAND_SOFT)]))
    story += [meta_table, Spacer(1, 4),
              Paragraph("Review IDs refer to records in this analysis. Reviewer names are not included in this report.",
                        STYLES["small"])]

    story += [Paragraph("Key figures", STYLES["h2"]), _figures(stats), Spacer(1, 10)]
    story += [CondPageBreak(60 * mm), Paragraph("Sentiment and star ratings", STYLES["h2"]), *_distribution(stats),
              Spacer(1, 6), *_tone_by_rating(run.review_results)]
    story += [CondPageBreak(50 * mm), Paragraph("Summary", STYLES["h2"]), *_summary(run.summary or {}, t)]
    for note in (run.summary or {}).get("notes", []):
        story.append(Paragraph(f"• {t(note)}", STYLES["small"]))
    story += [CondPageBreak(50 * mm), Paragraph("Features", STYLES["h2"]), *_features(run.aspects or [], t)]
    if run.keywords:
        words = ", ".join(f"{t(k['term'])} ({k['reviews']})" for k in run.keywords[:12])
        story += [Paragraph("Frequently used words", STYLES["h3"]),
                  Paragraph(f"{words}. Numbers are reviews using the word.", STYLES["muted"])]
    story += [CondPageBreak(60 * mm), Paragraph("How this was analysed", STYLES["h2"]), *_method(run, product, t)]
    story += [Paragraph("Limitations", STYLES["h2"]), *_limitations(run, product, stats)]
    attribution = ["Text set in DejaVu Sans (Bitstream Vera / DejaVu licence)."]
    if product.source == "url" and product.source_site == "apple_app_store":
        attribution.insert(0, "Review data: Apple App Store public customer-review feed.")
    if t.replaced:
        attribution.append(f"{MISSING_GLYPH} marks characters the report font can’t display (for example some emoji "
                           "or non-Latin scripts).")
    story += [Spacer(1, 8)] + [Paragraph(escape(a), STYLES["small"]) for a in attribution]
    return story


def _plain_text(flowable) -> list[str]:
    if isinstance(flowable, (list, tuple)):
        return [text for item in flowable for text in _plain_text(item)]
    if isinstance(flowable, Paragraph):
        return [flowable.getPlainText()]
    if isinstance(flowable, Table):
        return [text for row in flowable._cellvalues for cell in row
                for text in (_plain_text(cell) if not isinstance(cell, str) else [cell])]
    if isinstance(flowable, KeepTogether):
        return [text for inner in flowable._content for text in _plain_text(inner)]
    return []


def report_text(product: Product, run: AnalysisResult, generated_at: datetime | None = None) -> str:
    """The report's text, one block per line — used by tests to check figures and excerpts."""
    story = _story(product, run, generated_at or datetime.now(timezone.utc))
    return "\n".join(text for flowable in story for text in _plain_text(flowable))


def build_report(product: Product, run: AnalysisResult, generated_at: datetime | None = None) -> bytes:
    """Return the PDF for one stored analysis run of `product`."""
    story = _story(product, run, generated_at or datetime.now(timezone.utc))
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                          bottomMargin=20 * mm, title=f"Review analysis — {product.name}",
                          author="Reviews Dekho AI", subject=f"Analysis run #{run.id}", invariant=1)
    doc.addPageTemplates([PageTemplate(frames=[Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - MARGIN - 20 * mm,
                                                     id="body", leftPadding=0, rightPadding=0, topPadding=0,
                                                     bottomPadding=0)])])
    footer_name = "".join(c if ord(c) in _GLYPHS else MISSING_GLYPH for c in product.name[:60])
    canvas_class = type("_Canvas", (_NumberedCanvas,), {
        "footer_text": f"Reviews Dekho AI · {footer_name} · Analysis run #{run.id}"})
    doc.build(story, canvasmaker=canvas_class)
    return buffer.getvalue()
