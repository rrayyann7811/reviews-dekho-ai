"""Finite native ONNX test harness. All model inputs and databases are synthetic."""
import asyncio
import csv
import hashlib
import io
import json
import os
import platform
import resource
import signal
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Event
from unittest.mock import patch

STATE = Path("/state")
CGROUP = Path("/sys/fs/cgroup")
CAP = 2 * 1024**3
PREVIEW_PEAK = int(1.25 * 1024**3)
# The full matrix includes six long imports at roughly 40 seconds each.
# This is a subprocess watchdog. The preview latency gates are checked below.
MATRIX_WATCHDOG_SECONDS = 330
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
    "MAX_ROWS": "100",
    "MAX_REVIEW_CHARS": "1000",
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


def configure(label):
    os.environ.update(POLICY, DATABASE_URL=f"sqlite:///{database_path(label)}")
    verify_limits()


def db_counts(label):
    with sqlite3.connect(f"{database_path(label).as_uri()}?mode=ro", uri=True, timeout=5) as db:
        return tuple(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in SNAPSHOT_TABLES)


def start_app(label):
    configure(label)
    start = time.perf_counter()
    from app.main import app
    from app.nlp.engines import get_engine
    from fastapi.testclient import TestClient

    record(f"{label}.imports", seconds=round(time.perf_counter() - start, 4))
    return app, TestClient, get_engine, start


def load_model(get_engine):
    start = time.perf_counter()
    engine, reason = get_engine("transformer")
    assert engine.id == "transformer" and reason is None, reason
    assert engine.session.get_providers() == ["CPUExecutionProvider"]
    return engine, time.perf_counter() - start


def fixture(kind, size, long=False):
    rows = [("review", "rating")]
    for index in range(size):
        tone = index % 3
        text = TEXTS[tone]
        if long:
            filler = FILL[tone]
            text += (" " + filler) * ((960 - len(text)) // (len(filler) + 1))
        text += f" Unit number {index}."
        assert len(text) <= 1000 and (not long or len(text) >= 940)
        rows.append((text, (5, 1, 3)[tone]))

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
    assert result["stats"]["sentimentCounts"] == dict(Counter(CLASSES[i % 3] for i in range(count))), result["stats"]
    aspects = {row["aspect"]: row for row in result["aspects"]}
    for name in ("Battery", "Camera"):
        assert name in aspects, aspects
        row = aspects[name]
        assert row["mentions"] == (count + 2) // 3 + (count + 1) // 3, row
        assert row["positive"] == (count + 2) // 3 and row["negative"] == (count + 1) // 3, row


def check_engine(result):
    assert result["engine"]["id"] == "transformer" and result["engine"]["fallbackReason"] is None, result["engine"]


def upload(client, label, kind, count, long=False, cold_started=None):
    files = fixture(kind, count, long)
    preview = timed(client, f"{label}.preview", "POST", "/api/uploads/preview", 200, files=files)
    assert preview.json()["rowCount"] == count, preview.text
    product = timed(client, f"{label}.import", "POST", "/api/uploads/import", 201,
                    files=files, data=form(label)).json()
    if cold_started is not None:
        record("cold.import-end-to-end", seconds=round(time.perf_counter() - cold_started, 4))
    url = f"/api/products/{product['id']}"
    result = timed(client, f"{label}.analysis", "GET", url + "/analysis", 200).json()
    check_analysis(result, count)
    pdf = timed(client, f"{label}.pdf", "GET", url + "/report.pdf", 200)
    assert pdf.content.startswith(b"%PDF-") and pdf.content.rstrip().endswith(b"%%EOF")
    export = timed(client, f"{label}.csv", "GET", url + "/report.csv", 200)
    rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
    assert len(rows) == count
    assert Counter(row["sentiment"] for row in rows) == Counter(result["stats"]["sentimentCounts"])
    record(f"{label}.verified", review_count=count, format=kind, long=long, engine="transformer",
           sentiment=result["stats"]["sentimentCounts"], product_id=product["id"])
    return product["id"], result


def cold():
    app, client_type, get_engine, start = start_app("cold")
    with client_type(app) as client:
        assert client.get("/api/health").status_code == 200
        record("cold.ready", seconds=round(time.perf_counter() - start, 4))
        _, model_time = load_model(get_engine)
        record("cold.model", seconds=round(model_time, 4))
        product, analysis = upload(client, "cold.csv.100", "csv", 100, long=True, cold_started=start)
        record("cold.total", seconds=round(time.perf_counter() - start, 4),
               product_id=product, analysis_id=analysis["analysisId"])


def matrix():
    app, client_type, get_engine, _ = start_app("matrix")
    with client_type(app) as client:
        _, elapsed = load_model(get_engine)
        record("matrix.model", seconds=round(elapsed, 4))
        for repetition in range(1, 4):
            for kind in ("csv", "xlsx"):
                for count in (10, 50, 100):
                    label = f"warm.{kind}.{count}.{repetition}"
                    product, result = upload(client, label, kind, count, long=count == 100)
                    if (repetition, kind, count) == (3, "xlsx", 100):
                        (STATE / "persist.json").write_text(json.dumps({"id": product, "result": result}))
                    else:
                        assert client.delete(f"/api/products/{product}").status_code == 204


def persist():
    app, client_type, _, _ = start_app("matrix")
    saved = json.loads((STATE / "persist.json").read_text())
    original = saved["result"]
    url = f"/api/products/{saved['id']}"
    with client_type(app) as client:
        result = timed(client, "persistence.reopen", "GET", url + "/analysis", 200).json()
        assert result == original
        assert db_counts("matrix") == (1, 100, 1)
        updated = timed(client, "persistence.reanalyze", "POST", url + "/analyze", 200).json()
        check_analysis(updated, 100)
        assert updated["analysisId"] != original["analysisId"]
        history = timed(client, "persistence.history", "GET",
                        f"/api/history/{original['analysisId']}", 200).json()
        assert history["reviews"] == original["reviews"]
        check_engine(history)
        assert db_counts("matrix") == (1, 100, 2)
    record("persistence.verified", old_analysis=original["analysisId"], new_analysis=updated["analysisId"])


async def incomplete(app):
    messages = iter((
        {"type": "http.request", "body": b"--ab", "more_body": True},
        {"type": "http.disconnect"},
    ))

    async def receive():
        return next(messages)

    async def send(message):
        raise AssertionError(f"Disconnected request sent a response: {message['type']}")

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/api/uploads/import",
             "raw_path": b"/api/uploads/import", "query_string": b"", "root_path": "",
             "server": ("localhost", 80), "client": ("127.0.0.1", 12345),
             "headers": [(b"content-type", b"multipart/form-data; boundary=ab")]}
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    assert next(messages, None) is None


def edges():
    app, client_type, get_engine, _ = start_app("edges")
    path = "/api/uploads/import"
    with client_type(app) as client:
        initial = db_counts("edges")
        invalid = (
            ("broken-xlsx", {"file": ("bad.xlsx", b"not XLSX")}, form("invalid"), 400),
            ("required-field", fixture("csv", 10), {"product_name": "invalid"}, 422),
            ("file-limit", {"file": ("large.csv", b"x" * 1_048_577)}, form("invalid"), 413),
            ("body-limit", {"file": ("large.csv", b"x" * 1_310_721)}, form("invalid"), 413),
            ("row-limit", fixture("csv", 101), form("invalid"), 413),
        )
        for name, files, data, code in invalid:
            timed(client, f"invalid.{name}", "POST", path, code, files=files, data=data)
            assert db_counts("edges") == initial
        mark = time.perf_counter()
        asyncio.run(incomplete(app))
        assert db_counts("edges") == initial
        record("invalid.disconnect", seconds=round(time.perf_counter() - mark, 4))

        engine, _ = load_model(get_engine)
        predict = engine.predict
        entered, release = Event(), Event()

        def hold_then_predict(texts):
            entered.set()
            assert release.wait(15), "Admission barrier timed out"
            return predict(texts)

        with patch.object(engine, "predict", hold_then_predict), ThreadPoolExecutor(1) as pool:
            active = pool.submit(timed, client, "admission.first", "POST", path, 201,
                                 files=fixture("csv", 10), data=form("concurrent first"))
            try:
                assert entered.wait(10), "Real import did not reach inference"
                busy = timed(client, "admission.busy", "POST", path, 429, files=fixture("xlsx", 10),
                             data=form("concurrent second"))
                assert busy.headers.get("Retry-After") == "5", busy.headers
                timed(client, "admission.health", "GET", "/api/health", 200)
            finally:
                release.set()
            created = active.result(timeout=45).json()
        result = client.get(f"/api/products/{created['id']}/analysis").json()
        check_analysis(result, 10)
        upload(client, "admission.next", "xlsx", 10)
        assert db_counts("edges") == (2, 20, 2)
        record("admission.verified", busy_status=429, retry_after=5)


def interrupted():
    app, client_type, get_engine, _ = start_app("interrupted")
    from app.models import AnalysisResult
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    def before_commit(session):
        analysis = session.scalars(select(AnalysisResult)).one()
        check_engine({"engine": analysis.engine})
        (STATE / "before-commit").touch()
        # The controller kills this process while the actual DB transaction is open.
        time.sleep(60)
        raise AssertionError("Controller did not terminate interrupted import")

    with client_type(app) as client:
        load_model(get_engine)
        with patch.object(Session, "commit", before_commit):
            timed(client, "interrupt.unexpected-completion", "POST", "/api/uploads/import", 201,
                  files=fixture("csv", 10), data=form("will be interrupted"))


def recover():
    app, client_type, _, _ = start_app("interrupted")
    with client_type(app) as client:
        counts = db_counts("interrupted")
        assert counts == (0, 0, 0), counts
        record("interrupt.rollback", counts=counts)
        upload(client, "interrupt.retry", "csv", 10)
        assert db_counts("interrupted") == (1, 10, 1)


def ambiguous_timeout():
    app, client_type, get_engine, _ = start_app("timeout")
    sent, release = Event(), Event()

    async def hold_response(scope, receive, send):
        async def gated(message):
            if message["type"] == "http.response.start":
                sent.set()
                assert await asyncio.to_thread(release.wait, 15), "Response barrier timed out"
            await send(message)
        await app(scope, receive, gated if scope["type"] == "http"
                  and scope["path"] == "/api/uploads/import" else send)

    target = "/api/uploads/import"
    name = "same request after deadline"
    files = fixture("xlsx", 10)
    with client_type(hold_response) as client, ThreadPoolExecutor(1) as pool:
        load_model(get_engine)
        first = pool.submit(timed, client, "timeout.original", "POST", target, 201,
                            files=files, data=form(name))
        try:
            assert sent.wait(15), "Import never reached response after commit"
            deadline_started = time.perf_counter()
            try:
                first.result(timeout=0.15)
            except TimeoutError:
                assert db_counts("timeout") == (1, 10, 1)
            else:
                raise AssertionError("Caller received the response before its synthetic deadline")
            record("timeout.caller-deadline", seconds=round(time.perf_counter() - deadline_started, 4),
                   durable_counts=(1, 10, 1))
        finally:
            release.set()
        first_id = first.result(timeout=10).json()["id"]

        original = timed(client, "timeout.reconcile", "GET", f"/api/products/{first_id}/analysis", 200).json()
        check_analysis(original, 10)
        duplicate = timed(client, "timeout.blind-retry", "POST", target, 201,
                          files=files, data=form(name)).json()
        assert duplicate["id"] != first_id and db_counts("timeout") == (2, 20, 2)
        check_analysis(client.get(f"/api/products/{duplicate['id']}/analysis").json(), 10)
        # A known preview blocker, distinct from failure of this diagnostic test.
        record("timeout.verified", original_id=first_id, blind_retry_id=duplicate["id"],
               recovery="Committed original persisted. Blind retry created a duplicate.")


def run_child(name, timeout=150):
    print(f"BEGIN {name} (watchdog: {timeout}s)", flush=True)
    try:
        subprocess.run([sys.executable, "-S", "-u", __file__, name], check=True, timeout=timeout)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
        record("child.failed", workload=name, error_type=type(error).__name__, watchdog_seconds=timeout)
        raise
    print(f"PASS {name}", flush=True)


def suite():
    verify_limits()
    record("limits", cpu_max=cgroup_value("cpu.max"), cpu_affinity=sorted(os.sched_getaffinity(0)),
           memory_max=int(cgroup_value("memory.max")), swap_max=int(cgroup_value("memory.swap.max")),
           architecture=platform.machine(), python=sys.version, libc=platform.libc_ver())
    for name in ("cold", "matrix", "persist", "edges"):
        run_child(name, timeout=MATRIX_WATCHDOG_SECONDS if name == "matrix" else 100)
    print("BEGIN interruption before commit", flush=True)
    process = subprocess.Popen([sys.executable, "-S", "-u", __file__, "interrupted"])
    start = time.monotonic()
    try:
        while not (STATE / "before-commit").exists():
            assert process.poll() is None, f"Interrupted child stopped: {process.returncode}"
            assert time.monotonic() - start < 45, "Child did not reach its pre-commit barrier"
            time.sleep(0.02)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
    assert process.returncode == -signal.SIGKILL, process.returncode
    record("interrupt.killed", seconds=round(time.monotonic() - start, 4),
           signal="SIGKILL", source="test controller")
    run_child("recover")
    run_child("ambiguous_timeout")

    rows = [json.loads(line) for line in (STATE / "results.jsonl").read_text().splitlines()]
    verified = {(row["format"], row["review_count"], row["case"])
                for row in rows if row["case"].startswith("warm.") and row["case"].endswith(".verified")}
    assert len(verified) == 18
    warm_imports = [row for row in rows if row["case"].startswith("warm.") and row["case"].endswith(".import")]
    assert len(warm_imports) == 18
    cold = next(row for row in rows if row["case"] == "cold.import-end-to-end")
    max_warm = max(row["seconds"] for row in warm_imports)
    peak = int(cgroup_value("memory.peak"))
    verify_limits()
    record("suite.result", warm_cases=len(verified), max_warm_import_seconds=max_warm,
           cold_end_to_end_seconds=cold["seconds"],
           latency_headroom=max_warm <= 15 and cold["seconds"] <= 30,
           memory_headroom=peak <= PREVIEW_PEAK,
           max_recorded_process_peak_rss_kib=max(row["process_peak_rss_kib"] for row in rows))
    assert max_warm <= 15 and cold["seconds"] <= 30, "Preview latency target exceeded"
    assert peak <= PREVIEW_PEAK, "Preview cgroup memory headroom target exceeded"
    (STATE / "suite-passed").touch()


if __name__ == "__main__":
    operations = {"suite": suite, "cold": cold, "matrix": matrix, "persist": persist, "edges": edges,
                  "interrupted": interrupted, "recover": recover, "ambiguous_timeout": ambiguous_timeout}
    operations[sys.argv[1]]()
