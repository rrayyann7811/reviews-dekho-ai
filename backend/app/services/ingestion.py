"""Reading, previewing and cleaning uploaded review files (CSV / Excel).

The steps are:
1. read_table()      bytes -> pandas DataFrame (all values as text)
2. detect_columns()  guess which column holds the review text, rating, date…
3. build_preview()   first rows + guesses, shown to the user before importing
4. clean_reviews()   apply the user's column choices, validate and clean every
                     row, and report what was skipped and why
"""
import csv
import io
import re
from pathlib import Path

import pandas as pd

from .. import config
from ..errors import AppError
from ..nlp.preprocess import dedupe_key, normalize_text

ALLOWED_EXTENSIONS = (".csv", ".xlsx")

# Header names we recognise for each field, compared after lower-casing and
# removing everything except letters and digits ("Review Text" -> "reviewtext").
COLUMN_ALIASES = {
    "text": ["reviewtext", "review", "text", "comment", "comments", "reviewbody", "body", "content",
             "feedback", "reviewcontent", "reviewdescription", "description", "opinion"],
    "rating": ["rating", "stars", "star", "starrating", "score", "reviewrating", "ratings", "overallrating"],
    "date": ["reviewdate", "date", "reviewedon", "createdat", "postedon", "timestamp", "time", "datetime"],
    "title": ["reviewtitle", "title", "summary", "headline", "subject", "heading"],
    "reviewer": ["reviewername", "reviewer", "name", "author", "username", "customer", "customername", "user"],
    "productName": ["productname", "product", "producttitle", "item", "itemname"],
    "id": ["reviewid", "id", "commentid", "feedbackid"],
}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ---------- 1. Reading ----------

def check_file(file_name: str | None, content: bytes) -> str:
    """Validate name, size and type; return a safe display name."""
    name = Path(file_name or "").name
    if not name:
        raise AppError("No file was received. Choose a CSV or Excel (.xlsx) file.")
    if not name.lower().endswith(ALLOWED_EXTENSIONS):
        raise AppError(f"“{name}” isn’t a CSV or Excel (.xlsx) file. Older .xls files need to be re-saved as .xlsx.",
                       415)
    if not content:
        raise AppError(f"“{name}” is empty.")
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise AppError(f"“{name}” is larger than the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.", 413)
    return name


def _delimiter(text: str) -> str:
    """Detect comma, semicolon, tab or pipe from the header line; default to comma."""
    header = next((line for line in text.splitlines() if line.strip()), "")
    try:
        return csv.Sniffer().sniff(header, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","  # e.g. a single-column file


def _read_csv(content: bytes) -> pd.DataFrame:
    # Spreadsheet programs often save CSV as UTF-8 with a BOM, or as Windows-1252.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise AppError("The file’s text encoding couldn’t be read. Save it as “CSV UTF-8” and try again.")
    if "\x00" in text:
        raise AppError("This doesn’t look like a text CSV file. If it’s a spreadsheet, save it as .xlsx or CSV.")
    try:
        return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=_delimiter(text),
                           skip_blank_lines=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, csv.Error) as exc:
        detail = str(exc).strip().replace("Error tokenizing data. C error: ", "").rstrip(".")
        raise AppError(f"The CSV file couldn’t be read ({detail}). Check that text containing commas "
                       "is wrapped in double quotes.") from exc


def _read_xlsx(content: bytes) -> pd.DataFrame:
    try:
        df = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str, engine="openpyxl")
    except Exception as exc:  # openpyxl raises many different errors for damaged or non-Excel files
        raise AppError("The Excel file couldn’t be opened. Make sure it is a valid .xlsx file.") from exc
    return df.fillna("")


def read_table(file_name: str, content: bytes) -> pd.DataFrame:
    df = _read_csv(content) if file_name.lower().endswith(".csv") else _read_xlsx(content)
    df.columns = [normalize_text(c) for c in df.columns]
    # Drop columns with no header and no data (common in exported spreadsheets).
    unnamed = [c for c in df.columns if (not c or c.startswith("Unnamed:")) and (df[c].str.strip() == "").all()]
    df = df.drop(columns=unnamed)
    # Drop rows where every cell is empty.
    df = df[~(df.apply(lambda col: col.str.strip()) == "").all(axis=1)].reset_index(drop=True)

    if df.columns.empty:
        raise AppError("The file has no columns. The first row should contain column names.")
    if df.empty:
        raise AppError("The file has column names but no rows of data.")
    if len(df) > config.MAX_ROWS:
        raise AppError(f"The file has {len(df):,} rows. The limit is {config.MAX_ROWS:,} reviews per upload.", 413)
    return df


# ---------- 2. Column detection ----------

def detect_columns(columns: list[str]) -> dict[str, str | None]:
    keys = {c: _key(c) for c in columns}
    detected: dict[str, str | None] = {}
    used: set[str] = set()
    for role, aliases in COLUMN_ALIASES.items():
        match = None
        for alias in aliases:  # aliases are in order of preference
            match = next((c for c, k in keys.items() if k == alias and c not in used), None)
            if match:
                break
        detected[role] = match
        if match:
            used.add(match)
    return detected


def _guess_text_column(df: pd.DataFrame) -> str | None:
    """Fallback when no header looks like review text: the column with the longest values."""
    lengths = {c: df[c].str.len().mean() for c in df.columns}
    best = max(lengths, key=lengths.get)
    return best if lengths[best] >= 15 else None


# ---------- 3. Preview ----------

def build_preview(file_name: str, df: pd.DataFrame) -> dict:
    columns = list(df.columns)
    detected = detect_columns(columns)
    warnings = []
    if not detected["text"]:
        detected["text"] = _guess_text_column(df)
        if detected["text"]:
            warnings.append(f"No column is named like review text, so “{detected['text']}” was chosen because it "
                            "has the longest entries. Check that this is correct.")
        else:
            warnings.append("No column looks like review text. Choose it below.")

    product_name = None
    if detected["productName"]:
        names = [n for n in df[detected["productName"]].map(normalize_text).unique() if n]
        if names:
            product_name = names[0]
        if len(names) > 1:
            warnings.append(f"The file mentions {len(names)} different product names. All rows will be imported "
                            "as one product; split the file if they are different products.")

    sample = df.head(config.PREVIEW_ROWS)
    sample_rows = [{c: (v if v != "" else None) for c, v in row.items()} for row in sample.to_dict("records")]
    return {
        "fileName": file_name,
        "rowCount": len(df),
        "columns": columns,
        "sampleRows": sample_rows,
        "detected": detected,
        "productName": product_name,
        "warnings": warnings,
    }


# ---------- 4. Cleaning ----------

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def parse_rating(value) -> int | None:
    """Accepts 4, "4.0", "4/5", "4 stars", "4,5". Returns 1-5 or None if missing/invalid."""
    match = _NUMBER.search(str(value or ""))
    if not match:
        return None
    number = float(match.group().replace(",", "."))
    rating = int(number + 0.5)  # round half up: 4.5 -> 5
    return rating if 1 <= rating <= 5 else None


def parse_date(value):
    text = normalize_text(value)
    if not text:
        return None
    # Day-first is the norm for Indian and European exports; ISO dates (2026-01-31) are unaffected.
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=not re.match(r"^\d{4}-", text))
    return None if pd.isna(parsed) else parsed.date()


FIELDS = ("id", "text", "rating", "date", "title", "reviewer")


def clean_records(records: list[dict]) -> tuple[list[dict], dict]:
    """Validate and clean raw review records; return (reviews, report).

    Used for uploaded files AND reviews collected from websites, so both get
    exactly the same treatment. Each record may have: id, text, rating, date,
    title, reviewer (any type; missing keys are fine).

    Records are skipped when the text is empty or a duplicate (same review ID,
    or the same text when there is no ID). Invalid ratings and dates are kept
    as "not given" and counted in the report. An empty result is NOT an error
    here; callers decide what that means.
    """
    reviews, seen = [], set()
    report = {"rowsInFile": len(records), "emptyRemoved": 0, "duplicatesRemoved": 0,
              "invalidRatings": 0, "invalidDates": 0, "truncated": 0}
    for number, record in enumerate(records, start=1):
        text = normalize_text(record.get("text"))
        if not text:
            report["emptyRemoved"] += 1
            continue
        if len(text) > config.MAX_REVIEW_CHARS:
            text = text[: config.MAX_REVIEW_CHARS]
            report["truncated"] += 1

        review_id = normalize_text(record.get("id"))[:100]
        key = ("id", review_id) if review_id else ("text", dedupe_key(text))
        if key in seen:
            report["duplicatesRemoved"] += 1
            continue
        seen.add(key)

        raw_rating, raw_date = normalize_text(record.get("rating")), normalize_text(record.get("date"))
        rating, date = parse_rating(raw_rating), parse_date(raw_date)
        report["invalidRatings"] += bool(raw_rating and rating is None)
        report["invalidDates"] += bool(raw_date and date is None)

        reviews.append({
            "id": review_id or None,  # filled in below
            "row": number,
            "text": text,
            "rating": rating,
            "date": date,
            "title": normalize_text(record.get("title"))[:300] or None,
            "reviewer": normalize_text(record.get("reviewer"))[:120] or None,
        })

    # Reviews without an ID get "R-<row number>", skipping any ID already used.
    taken = {r["id"] for r in reviews if r["id"]}
    for review in reviews:
        row = review.pop("row")
        if not review["id"]:
            new_id, suffix = f"R-{row}", 1
            while new_id in taken:
                suffix += 1
                new_id = f"R-{row}-{suffix}"
            review["id"] = new_id
            taken.add(new_id)

    report["imported"] = len(reviews)
    return reviews, report


def clean_reviews(df: pd.DataFrame, columns: dict) -> tuple[list[dict], dict]:
    """Apply the user's column mapping to an uploaded table, then clean it with clean_records()."""
    missing = [name for name in columns.values() if name and name not in df.columns]
    if missing:
        raise AppError(f"These columns aren’t in the file: {', '.join(missing)}.", 422)
    if not columns.get("text"):
        raise AppError("Choose the column that contains the review text.", 422)

    records = [{field: row[columns[field]] for field in FIELDS if columns.get(field)}
               for row in df.to_dict("records")]
    reviews, report = clean_records(records)
    if not reviews:
        raise AppError("No usable reviews were found: every row had empty review text. "
                       "Check that the right column is selected.", 422)
    return reviews, report
