"""Finite native ONNX test harness. All model inputs and databases are synthetic."""
import csv
import hashlib
import io
import json
import os
import platform
import resource
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

STATE = Path("/state")
CGROUP = Path("/sys/fs/cgroup")
CAP = 2 * 1024**3
PREVIEW_PEAK = int(1.25 * 1024**3)
SIZES = (10, 25, 50)
FORMATS = ("csv", "xlsx")
REPETITIONS = 3
REVIEW_CHARS = 1000
SNAPSHOT_TABLES = ("products", "reviews", "analysis_results")
CLASSES = ("positive", "negative", "neutral")
TEXTS = (
    "I love this amazing phone. The battery is excellent. The camera is wonderful.",
    "I hate this terrible phone. The battery is awful. The camera is dreadful.",
    "It arrived on Tuesday.",
)
FILL = ("I love it.", "I hate it.", "It arrived on Tuesday.")
POLICY = {
    "AUTH_MODE": "local",
    "SENTIMENT_ENGINE": "transformer",
    "AI_SUMMARIES": "off",
    "MAX_UPLOAD_BYTES": "1048576",
    "MAX_REQUEST_BYTES": "1310720",
    "MAX_REVIEW_CHARS": str(REVIEW_CHARS),
    "MAX_COLUMNS": "16",
    "MAX_XLSX_EXPANDED_BYTES": "8388608",
    "MAX_XLSX_ENTRY_BYTES": "4194304",
    "MAX_XLSX_ENTRIES": "96",
    "MAX_EXPENSIVE_REQUESTS": "1",
    "MAX_PRODUCTS_PER_OWNER": "5",
    "MAX_ANALYSIS_RUNS": "3",
    # Allow all back-to-back test operations while exercising the separate admission gate.
    "RATE_LIMIT_INGESTION_REQUESTS": "100",
    "RATE_LIMIT_EXPORT_REQUESTS": "100",
}


def cgroup_value(name):
    return (CGROUP / name).read_text().strip()


def counters(name):
    return {key: int(value) for key, value in
            (line.split() for line in cgroup_value(name).splitlines())}


def verify_limits():
    assert platform.system() == "Linux" and platform.machine() == "x86_64"
    assert sys.version_info[:3] == (3, 14, 10), sys.version
    assert len(os.sched_getaffinity(0)) == 1
    quota, period = cgroup_value("cpu.max").split()
    assert quota == period and int(period) > 0, (quota, period)
    assert int(cgroup_value("memory.max")) == CAP
    assert cgroup_value("memory.swap.max") == "0"
    assert int(cgroup_value("memory.peak")) <= CAP
    assert not any(counters("memory.events")[key] for key in ("oom", "oom_kill", "oom_group_kill"))


def metrics():
    fields = Path("/proc/self/status").read_text().splitlines()
    rss = next(int(line.split()[1]) for line in fields if line.startswith("VmRSS:"))
    return {
        "pid": os.getpid(),
        "process_rss_kib": rss,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cgroup_current_bytes": int(cgroup_value("memory.current")),
        "cgroup_peak_bytes": int(cgroup_value("memory.peak")),
        "memory_events": counters("memory.events"),
    }


def record(case, **values):
    line = json.dumps({"case": case, **values, **metrics()}, sort_keys=True)
    print(line, flush=True)
    with (STATE / "results.jsonl").open("a") as stream:
        stream.write(line + "\n")


def database_path(label):
    return STATE / f"{label}.sqlite3"


def configure(label, count):
    os.environ.update(POLICY, MAX_ROWS=str(count), DATABASE_URL=f"sqlite:///{database_path(label)}")
    verify_limits()


def db_counts(label):
    with sqlite3.connect(f"{database_path(label).as_uri()}?mode=ro", uri=True, timeout=5) as db:
        return tuple(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in SNAPSHOT_TABLES)


def start_app(label, count):
    start = time.perf_counter()
    configure(label, count)
    from app.main import app
    from app.nlp.engines import get_engine
    from fastapi.testclient import TestClient

    record(f"{label}.imports", seconds=round(time.perf_counter() - start, 4))
    return app, TestClient, get_engine


def load_model(get_engine):
    start = time.perf_counter()
    engine, reason = get_engine("transformer")
    assert engine.id == "transformer" and reason is None, reason
    assert engine.session.get_providers() == ["CPUExecutionProvider"]
    return engine, time.perf_counter() - start


EXTRA_ASPECTS = ("Display", "Performance", "Build quality", "Price", "Packaging")


def review_text(index):
    tone = index % len(CLASSES)
    text = TEXTS[tone]
    if tone != 2:
        adjective = ("excellent", "awful")[tone]
        text += "".join(f" The {aspect.lower()} is {adjective}."
                        for aspect in ("display", "performance", "build", "price", "packaging"))
    text += f" Unit number {index}."
    # Keep the whole field at the configured boundary, with a printable final character.
    return (text + (" " + FILL[tone]) * REVIEW_CHARS)[:REVIEW_CHARS - 1] + "."


def fixture(kind, size):
    rows = [("review", "rating")]
    rows.extend((review_text(index), (5, 1, 3)[index % len(CLASSES)]) for index in range(size))

    if kind == "csv":
        output = io.StringIO()
        csv.writer(output).writerows(rows)
        value = output.getvalue().encode()
        return {"file": ("synthetic.csv", value, "text/csv")}

    from openpyxl import Workbook
    output = io.BytesIO()
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    workbook.save(output)
    return {"file": ("synthetic.xlsx", output.getvalue(),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def form(label):
    return {"product_name": label, "columns": '{"text":"review","rating":"rating"}'}


def timed(client, label, method, url, status, **kwargs):
    start = time.perf_counter()
    cpu = counters("cpu.stat")["usage_usec"]
    response = client.request(method, url, **kwargs)
    record(label, status=response.status_code, bytes=len(response.content),
           seconds=round(time.perf_counter() - start, 4),
           cpu_seconds=round((counters("cpu.stat")["usage_usec"] - cpu) / 1e6, 4))
    assert response.status_code == status, (label, status, response.status_code, response.text[:400])
    assert len(response.content) < 4_500_000, label
    return response


def check_analysis(result, count):
    assert result["engine"]["id"] == "transformer", result["engine"]
    assert result["engine"]["fallbackReason"] is None, result["engine"]
    assert result["stats"]["totalReviews"] == result["stats"]["analysedReviews"] == count, result["stats"]
    assert len(result["reviews"]) == count
    expected = {review_text(i): CLASSES[i % len(CLASSES)] for i in range(count)}
    actual = {review["text"]: review["sentiment"] for review in result["reviews"]}
    assert actual == expected, list(actual.values())
    assert result["ingestion"]["truncated"] == 0
    assert result["stats"]["sentimentCounts"] == dict(Counter(CLASSES[i % 3] for i in range(count))), result["stats"]
    aspects = {row["aspect"]: row for row in result["aspects"]}
    for name in EXTRA_ASPECTS:
        assert aspects[name]["mentions"] == (count + 2) // 3 + (count + 1) // 3, aspects[name]
    for name in ("Battery", "Camera"):
        assert name in aspects, aspects
        row = aspects[name]
        assert row["mentions"] == (count + 2) // 3 + (count + 1) // 3, row
        assert row["positive"] == (count + 2) // 3 and row["negative"] == (count + 1) // 3, row


def check_engine(result):
    assert result["engine"]["id"] == "transformer" and result["engine"]["fallbackReason"] is None, result["engine"]


def upload(client, label, kind, count, cold_started=None):
    files = fixture(kind, count)
    preview = timed(client, f"{label}.preview", "POST", "/api/uploads/preview", 200, files=files)
    assert preview.json()["rowCount"] == count, preview.text
    product = timed(client, f"{label}.import", "POST", "/api/uploads/import", 201,
                    files=files, data=form(label)).json()
    if cold_started is not None:
        record(f"{label}.import-end-to-end", seconds=round(time.perf_counter() - cold_started, 4))
    url = f"/api/products/{product['id']}"
    result = timed(client, f"{label}.analysis", "GET", url + "/analysis", 200).json()
    check_analysis(result, count)
    reopened = timed(client, f"{label}.stored", "GET", url + "/analysis", 200).json()
    assert reopened == result
    pdf = timed(client, f"{label}.pdf", "GET", url + "/report.pdf", 200)
    assert pdf.content.startswith(b"%PDF-") and pdf.content.rstrip().endswith(b"%%EOF")
    export = timed(client, f"{label}.csv", "GET", url + "/report.csv", 200)
    rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
    assert len(rows) == count
    assert Counter(row["sentiment"] for row in rows) == Counter(result["stats"]["sentimentCounts"])
    record(f"{label}.verified", review_count=count, format=kind, review_chars=REVIEW_CHARS, engine="transformer",
           sentiment=result["stats"]["sentimentCounts"], product_id=product["id"])
    return product["id"], result


def cold(kind, count, started):
    app, client_type, get_engine = start_app(f"cold-{kind}", count)
    with client_type(app) as client:
        assert client.get("/api/health").status_code == 200
        _, model_time = load_model(get_engine)
        record(f"cold.{kind}.model", seconds=round(model_time, 4))
        upload(client, f"cold.{kind}", kind, count, cold_started=started)
        assert db_counts(f"cold-{kind}") == (1, count, 1)


def warm(kind, count):
    label = f"warm-{kind}"
    app, client_type, get_engine = start_app(label, count)
    from app.errors import AppError
    from app.services import analysis as analysis_service

    with client_type(app) as client:
        _, model_time = load_model(get_engine)
        record(f"warm.{kind}.model", seconds=round(model_time, 4))
        for repetition in range(1, REPETITIONS + 1):
            product, _ = upload(client, f"warm.{kind}.{repetition}", kind, count)
            assert db_counts(label) == (1, count, 1)
            assert client.delete(f"/api/products/{product}").status_code == 204
            assert db_counts(label) == (0, 0, 0)

        target = "/api/uploads/import"
        timed(client, f"{kind}.row-limit", "POST", target, 413,
              files=fixture(kind, count + 1), data=form("over row limit"))
        assert db_counts(label) == (0, 0, 0)

        if count == SIZES[0] and kind == "csv":
            file_limit = int(POLICY["MAX_UPLOAD_BYTES"])
            body_limit = int(POLICY["MAX_REQUEST_BYTES"])
            for name, byte_count in (("file-limit", file_limit + 1), ("body-limit", body_limit + 1)):
                timed(client, name, "POST", target, 413,
                      files={"file": ("oversize.csv", b"x" * byte_count, "text/csv")},
                      data=form("over size limit"))
                assert db_counts(label) == (0, 0, 0)

        run_analysis = analysis_service.run_analysis

        def fail_after_analysis(db, *args, **kwargs):
            analysis = run_analysis(db, *args, **kwargs)
            check_engine({"engine": analysis.engine})
            db.flush()
            assert analysis.id is not None
            raise AppError("Synthetic failure after analysis, before commit.", 503)

        with patch.object(analysis_service, "run_analysis", fail_after_analysis):
            failure = timed(client, f"{kind}.forced-failure", "POST", target, 503,
                            files=fixture(kind, 3), data=form("before commit"))
            assert failure.json()["detail"] == "Synthetic failure after analysis, before commit."
        counts = db_counts(label)
        assert counts == (0, 0, 0), counts
        record(f"{kind}.rollback.verified", counts=counts)


def suite(count):
    verify_limits()
    record("limits", candidate=count, cpu_max=cgroup_value("cpu.max"),
           cpu_affinity=sorted(os.sched_getaffinity(0)),
           memory_max=int(cgroup_value("memory.max")), swap_max=int(cgroup_value("memory.swap.max")),
           architecture=platform.machine(), python=sys.version)
    for phase, watchdog in (("cold", 75), ("warm", 160)):
        for kind in FORMATS:
            print(f"BEGIN {count} {phase} {kind} (watchdog: {watchdog}s)", flush=True)
            command = [sys.executable, "-S", "-u", __file__, phase, str(count), kind]
            if phase == "cold":
                command.append(str(time.perf_counter()))
            try:
                subprocess.run(command, check=True, timeout=watchdog)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
                record("child.failed", phase=phase, format=kind, error_type=type(error).__name__)

    verify_limits()
    rows = {row["case"]: row for row in map(json.loads, (STATE / "results.jsonl").read_text().splitlines())}
    cold_times = [row["seconds"] for name, row in rows.items() if name.startswith("cold.") and
                  name.endswith(".import-end-to-end")]
    warm_times = [row["seconds"] for name, row in rows.items() if name.startswith("warm.") and
                  name.endswith(".import")]
    required = [
        case for kind in FORMATS for case in (
            f"cold.{kind}.verified", f"{kind}.rollback.verified",
            *(f"warm.{kind}.{n}.verified" for n in range(1, REPETITIONS + 1)),
        )
    ]
    missing = [case for case in required if case not in rows]
    functional = not missing and "child.failed" not in rows
    peak = int(cgroup_value("memory.peak"))
    warm_max = max(warm_times, default=None)
    cold_max = max(cold_times, default=None)
    latency = (len(warm_times) == len(FORMATS) * REPETITIONS and len(cold_times) == len(FORMATS)
               and warm_max <= 15 and cold_max <= 30)
    passed = functional and latency and peak <= PREVIEW_PEAK
    record("candidate.result", candidate=count, functional=functional, missing=missing,
           warm_cases=len(warm_times), cold_cases=len(cold_times),
           max_warm_import_seconds=warm_max, max_cold_end_to_end_seconds=cold_max,
           latency_pass=latency, memory_pass=peak <= PREVIEW_PEAK, passed=passed)
    if passed:
        (STATE / "candidate-passed").touch()
    return functional


if __name__ == "__main__":
    operation, raw_count, *args = sys.argv[1:]
    count = int(raw_count)
    assert count in SIZES
    if operation == "suite":
        sys.exit(0 if suite(count) else 1)
    kind, *timing = args
    assert kind in FORMATS
    if operation == "cold":
        cold(kind, count, float(timing[0]))
    else:
        assert operation == "warm" and not timing
        warm(kind, count)
