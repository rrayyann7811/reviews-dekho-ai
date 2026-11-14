"""CSV export of one stored analysis run."""
import csv
import io

from ..models import AnalysisResult

BASE_COLUMNS = ["review_id", "rating", "date", "title", "text", "analysis_status", "sentiment", "sentiment_score",
                "mixed_opinion", "features"]


def _safe(value) -> str:
    """Stop spreadsheet programs from treating a cell as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def reviews_csv(run: AnalysisResult, include_reviewer: bool = False) -> str:
    """Every review of the run with its results. Reviewer names are left out unless asked for."""
    columns = BASE_COLUMNS[:3] + (["reviewer"] if include_reviewer else []) + BASE_COLUMNS[3:]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for r in run.review_results:
        features = "; ".join(f"{a['aspect']} ({a['sentiment']})" for a in (r.get("aspects") or []))
        row = [_safe(r["id"]), r.get("rating") or "", r.get("date") or ""]
        if include_reviewer:
            row.append(_safe(r.get("reviewer")))
        row += [_safe(r.get("title")), _safe(r.get("text")), r.get("status", "analysed"), r.get("sentiment") or "",
                "" if r.get("score") is None else f"{r['score']:.3f}", "yes" if r.get("mixed") else "no",
                _safe(features)]
        writer.writerow(row)
    return "\ufeff" + buffer.getvalue()  # BOM so Excel opens it as UTF-8
