# Phase 2D ONNX memory and performance

## Audit and benchmark plan

Base: `74cf57238dcd71485bdf6f8c8095d1d4595e380b`. This phase measures synthetic workloads before
hosting selection. It does not deploy, provision, start an application worker/scheduler or migrate an
application database. Docker hard-limit benchmarking is deferred by explicit decision.

The installed model is the existing int8 Xenova conversion of
`cardiffnlp/twitter-roberta-base-sentiment-latest`, pinned by `scripts/download_model.py` to revision
`f3ec4d0925f90c3ca7ee7814f52d6ee7cf180445`. The ONNX weights, tokenizer and label config are SHA-256
verified before transformer benchmarks. Nothing downloads or substitutes another model. Dependencies
are the existing ONNX Runtime, tokenizers, NumPy and VADER packages; the full pipeline also imports
scikit-learn/SciPy for keyword extraction, and API/worker paths add their existing database/framework stack.

`get_engine` lazily loads one transformer per process under a lock, caches it, and caches load failures
until reset/restart. VADER is constructed at import. A missing model chooses VADER; the pipeline can also
fall back after inference failure. Benchmarks distinguish explicit VADER from missing-model fallback and
refuse to label an unexpected fallback as ONNX throughput. Repeated selection must return the same object.

Production inference uses CPUExecutionProvider, four intra-op threads, default ORT inter-op/allocator/graph
settings, batch size **one**, maximum **256 tokens**, dynamic padding and length sorting. Batch size stays
one: prior evaluations found quantization-dependent predictions when batching reviews together. No model,
labels, score computation, truncation, batch size or production thread/allocator default changes here.
The only production code addition is optional SessionOptions injection into TransformerEngine for isolated
experiments; ordinary loading follows its unchanged four-thread path.

Full analysis prepares all reviews, builds aspect mentions, predicts whole reviews plus aspect clauses,
creates keyword matrices, summaries and per-review results, then stores JSON snapshots. Its memory and
throughput differ from model-only prediction. Work is bounded by existing upload/review/history quotas,
but those quotas are not RSS limits. API and standalone worker processes can each load their own model.
Worker concurrency defaults to one; SQLite serializes writes. PostgreSQL concurrency above one can also
increase concurrent activation buffers. Shared inference/worker-concurrency sizing needs measurement before
raising defaults. No persistent worker is started: worker measurements call finite `run_once` jobs against
a fresh synthetic SQLite database.

The plan measures fresh-process imports/model load/first prediction, repeated warm inference, full pipeline,
real in-process API analysis and finite worker transactions. It compares intra-op threads 1/2/4, counts and
text lengths, default/off CPU arenas, VADER/fallback, cleanup, and simultaneous API/worker process RSS.

## Methodology and interpretation

`backend/scripts/benchmark_onnx.py` is a standard-library supervisor and fresh-interpreter harness. Every
case starts with synthetic-only data and an internally generated temporary SQLite URL **before app imports**.
It clears inherited authentication, database-pool, rate/quota and job settings, fixes local authentication
and disables AI. There is no database URL argument, collector, private input or network/download path.
Generated JSON output is refused inside the repository; temporary data is removed after each child.

Current RSS uses macOS libproc proc_pidinfo or Linux /proc statm. A 10 ms sampler records phase start/end/
sampled peak. getrusage supplies a normalized whole-process high-water RSS (macOS bytes, Linux KiB × 1024).
High-water marks are never subtracted to fabricate phase peaks. Short spikes can evade phase/aggregate
sampling, while the process lifetime high-water still captures the kernel-reported peak. The supervisor
has a configurable sampled RSS safety guard (default 1536 MiB), which is **not** a kernel-enforced RAM cap.
The parent benchmark process is excluded from deployed-process RSS measurements.

Baseline is the child after standard-library imports; `imports` includes the selected application stack.
`model_load` includes ORT import/session/tokenizer initialization; `cached_load` checks model reuse.
`first_prediction` is the fresh session's first one-review inference. Warm repeats follow that one fixed
warmup, retaining normal model/allocator caches. The warm worker path includes durable enqueue, claim,
analysis, atomic publication and result readback. The API path uses TestClient and the existing synchronous
analyze route, including database/response serialization, but no external HTTP server, TLS or proxy.
Synthetic database seeding is reported separately. Worker/API warm repeats retain prior analysis snapshots
as production history does, up to the bounded repeat count.

These are **fresh interpreter**, not flushed-disk-cache, cold starts: model hashing warms the filesystem
cache, and no privileged cache flushing is performed. Model readiness is assessed from import/load/first-
prediction phases, not mislabeled as an Internet request's cold-start time. Each repeat records latency,
throughput, actual model text count (including aspect clauses), token width and a digest of labels/scores.
Synthetic text is a deterministic positive/negative/neutral English mix with distinct entry markers, fixed
character lengths and limited vocabulary. Long text is intentionally truncated by the unchanged tokenizer.
This does not represent every language, keyword vocabulary, aspect density or adversarial review.

Paired runs start API and finite worker children together, synchronizing before model loading. They sample
**simultaneous sum of their RSS**, and also retain the sum of individual high-water marks as a conservative
upper envelope. RSS can double-count shared pages; neither sum is Linux cgroup charged memory. Pair latency
includes CPU contention. No number here includes PostgreSQL, reverse proxy, OS, platform agent, deployment
startup overlap or other services unless explicitly stated.

The 512 MiB, 1 GiB and 2 GiB comparisons report whether measured process RSS fits each budget and remaining
space. They do not silently turn a macOS observation into proof that Linux will survive a hard cgroup limit.
A budget exceeded by measured RSS is rejected for that workload; an observed fit still needs headroom and
hard-limit deployment testing. Docker hard-limit benchmarking is deferred; no such tests were performed.

## Measured environment and short-input calibration

Local measurement: Apple M3, eight physical/logical cores, 8 GiB unified RAM, macOS 27.2.1 arm64, Python 3.14.3. At audit the host reported 36% free memory and 61 GiB available disk. These are native macOS observations, not a constrained Linux cloud VM.

Installed versions: ONNX Runtime 1.32.0, tokenizers 0.23.3, NumPy 2.5.4, scikit-learn 1.9.1, SQLAlchemy 2.1.8 and vaderSentiment 3.3.2. ONNX weights are 125,905,426 bytes; tokenizer 2,108,615 bytes; config 887 bytes (122.1 MiB combined). Hashes matched the existing download pins.

The calibration used 100 × 80-character reviews, two fresh processes per thread setting and three warm repeats per process. The table reports median warm throughput across six repeats and maximum process high-water RSS. OMP/BLAS/tokenizer thread environment overrides were unset. ORT reported sequential execution, inter-op threads 0 (runtime default), CPU arena and memory-pattern optimization enabled, CPU provider only.

| Path | 1 thread reviews/s | 2 threads reviews/s | 4 threads reviews/s | 4-thread peak RSS (MiB) |
|---|---:|---:|---:|---:|
| engine | 79.5 | 138.7 | 199.3 | 259.9 |
| pipeline | 33.1 | 57.0 | 81.2 | 372.4 |
| worker | 33.5 | 54.0 | 70.4 | 425.8 |
| api | 32.4 | 55.6 | 75.1 | 452.9 |

All calibration whole-review label/score digests matched across 1/2/4 threads and both cold runs within each path. This is sample parity, not a proof covering every possible text or a reason to change production settings. Four threads won on this eight-core host; that does not establish the best choice for a one-vCPU quota.

| Path (4 threads) | Imported stack RSS, max MiB | Model-load sampled peak, MiB | Model-load time range, s | First prediction range, ms | Cached selection, µs |
|---|---:|---:|---:|---:|---:|
| engine | 41.8 | 256.8 | 0.130–0.214 | 5.1–5.3 | 4.5 |
| pipeline | 154.0 | 369.2 | 0.143–0.159 | 5.0–5.2 | 5.3 |
| worker | 206.8 | 420.4 | 0.164–0.166 | 5.5–6.2 | 4.2 |
| api | 227.5 | 442.8 | 0.166–0.365 | 5.0–7.4 | 2.8 |

The standard-library process baseline was about 29 MiB. Stack imports themselves took 0.03 s for engine-only, 0.66–0.69 s for pipeline, 0.95–0.99 s for worker and 1.35–1.45 s for API in these four-thread cases. Model-load time is not end-to-end API startup. RSS varies with allocation/compression/host activity, so these small samples do not support tail-latency percentiles.

## Review-count and text-length measurements

Four intra-op threads, batch one, one fresh process per case, two warm repeats. These are whole-review throughput figures, not raw ONNX calls: each review also scores aspect clauses. The input matrix included one and 1,000 reviews at 80, 500 and 5,000 characters. Maximum observed token width remained 256.

| Path | Reviews | Characters/review | Peak RSS, MiB | Median warm seconds | Reviews/s | Engine input texts/repeat |
|---|---:|---:|---:|---:|---:|---:|
| pipeline | 1000 | 80 | 389.1 | 12.54 | 79.7 | 3000 |
| pipeline | 1000 | 500 | 376.7 | 32.57 | 30.7 | 3000 |
| pipeline | 1000 | 5000 | 423.2 | 73.30 | 13.6 | 3000 |
| worker | 1000 | 80 | 453.5 | 13.77 | 72.6 | 3000 |
| worker | 1000 | 500 | 446.8 | 36.40 | 27.5 | 3000 |
| worker | 1000 | 5000 | 461.9 | 84.84 | 11.8 | 3000 |
| api | 1000 | 80 | 469.1 | 19.21 | 52.1 | 3000 |
| api | 1000 | 500 | 482.5 | 40.09 | 24.9 | 3000 |
| api | 1000 | 5000 | 496.0 | 78.96 | 12.7 | 3000 |

The API case intentionally includes the supported full-review response. The current dashboard requests include_reviews=false, which avoids some response bytes but does not eliminate model/pipeline/history allocations. TestClient also parses the response in the measured process, so these API figures include an extra client-side copy; an external client/server and JWT verification have different overhead. No TLS, network proxy or real database server is included.

## Simultaneous processes and populated history

For 20,000 × 80-character reviews, simultaneous ONNX API and finite worker processes reached **925.5 MiB aggregate sampled RSS**. Individual lifetime peaks summed to 959.4 MiB. Each processed approximately 28.9 reviews/s, taking 691–693 seconds; launch through first prediction took about 1.92 seconds. This pair used separate synthetic SQLite databases to measure process memory and CPU contention, not shared-database locking. It does not establish PostgreSQL transaction throughput.

The same maximum-row short-input VADER pair reached 776.6 MiB aggregate RSS (API 404.0, worker 372.6 MiB), with about 5,384/5,512 reviews/s. Large database/result allocations remain even without ONNX.

With 100 × 80-character reviews and three repeats per process:

| ONNX intra-op threads/process | Simultaneous RSS, MiB | API reviews/s | Worker reviews/s |
|---|---:|---:|---:|
| 1 | 853.5 | 32.7 | 32.6 |
| 2 | 882.0 | 49.7 | 49.7 |
| 4 | 869.4 | 39.0 | 42.5 |

Two threads improved combined throughput on this M3 in this small paired sample; four won the isolated calibration. This is a candidate for further target-host measurement, not a production configuration change or a one-vCPU result.

A separate populated-history test seeded 19 valid synthetic VADER snapshots, then performed one real ONNX analysis of 1,000 × 5,000-character reviews:

| Process | Operational high-water RSS, MiB | Diagnostic lifetime peak, MiB | Warm seconds | Reviews/s |
|---|---:|---:|---:|---:|
| Worker | 463.9 | 470.2 | 65.95 | 15.2 |
| API | 541.8 | 624.3 | 68.30 | 14.6 |

Operational peak is the maximum recorded lifetime high-water **before** the final reset/GC diagnostic. It is not a subtraction of two high-water marks. The API's final explicit reset/GC increased RSS to 624.3 MiB; it was not an analysis-request peak and does not prove model memory was returned to the OS. The seed phase itself reached about 520 MiB in the API process. Historical snapshots used VADER to avoid unnecessary repeated ONNX computation; only the current measured analysis used ONNX.

`Product.latest_analysis` accesses the full ORM analysis collection. Analysis and API serialization can therefore materialize historical review JSON, even when only the latest result is needed. Seven-day retention does not prevent large allocations within that period. This implementation documents the risk without changing production queries or data.

## Fallback and allocator experiments

For 1,000 reviews, explicit VADER lifetime RSS and median throughput were:

| Path | 80-char RSS MiB | 80-char reviews/s | 5,000-char RSS MiB | 5,000-char reviews/s |
|---|---:|---:|---:|---:|
| Pipeline | 159.4 | 6,407 | 182.9 | 220.5 |
| Worker | 218.7 | 5,606 | 270.3 | 220.7 |
| API | 247.6 | 5,712 | 303.2 | 214.8 |

Missing-model fallback had similar throughput and peaks (long-input API 310.0 MiB). A controlled runtime prediction exception after successfully loading ONNX also selected VADER correctly, but retained model memory: long-input peaks were pipeline 403.0, worker 483.0 and API 537.2 MiB. These are controlled inference failures, not simulated kernel OOM recovery. Kernel termination cannot be rescued by Python fallback.

Disabling the ORT CPU arena did not provide a convincing benefit for 20 × 5,000-character reviews, two fresh processes per path, three repeats each. Worker peaks were 430.9–444.5 MiB with arena on and 436.3–445.8 off; API peaks 470.1–471.0 on and 472.2–472.3 off. Throughput was similar or lower with it off. Defaults remain unchanged.

Across all 80 measured child cases and 192 warm operations, 34 comparable groups (selected engine, path, count and text length) had identical whole-review label/score digests across applicable thread/arena/fallback/history variants. Digests do not cover every aspect/keyword field or prove equivalence on arbitrary real inputs.

## RAM sizing and operational recommendations

| RAM budget | Assessment from native measurements |
|---|---|
| 512 MiB | Not suitable for the measured populated-history API: operational RSS alone reached 541.8 MiB. A roughly 480 MiB worker leaves very little room for other allocations. No Linux hard-cap test completed. |
| 1 GiB | Some individual processes fit the measured profile. The paired 20,000-row run reached 925.5 MiB simultaneously; sum of individual peaks was 959.4 MiB, leaving only 64.6 MiB before database/OS/proxy overhead. Not recommended as a combined API/worker production budget. |
| 2 GiB | A candidate for one API process plus one concurrency-one worker on the **bounded profiles measured here**. Not a validated guarantee for current maximum input/history settings, Linux cgroups or colocated PostgreSQL. |

Adding the separately measured populated-history operational peaks gives about 1,005.7 MiB, leaving only 18.3 MiB in 1 GiB; adding diagnostic lifetime peaks gives 1,094.4 MiB. Those sums are conservative planning comparisons, **not** an observed simultaneous populated-history run.

Current bounds can still permit 20,000 × 5,000-character review text across 20 stored snapshots: roughly two billion raw text bytes before Python/JSON/model overhead. That dangerous combined maximum was intentionally not run on this 8 GiB host. A 2 GiB service cannot be declared safe for those settings. Hosting selection requires lower deployment-specific input/history budgets or a separately reviewed latest-snapshot/query-memory improvement. Lowering future quotas does not shrink existing data.

Keep model reuse, batch one and worker concurrency one. Multiple API server processes each load a model; budget them independently. Keep CPU arena and four-thread defaults pending target-host experiments. Do not use per-request engine resets or explicit GC as a RAM limit. Querying only the necessary ingestion/latest snapshot, reducing retained result copies and measuring the dashboard's reduced response are future optimization candidates, not changes implemented here.

The maximum-row run lasted over eleven minutes on this host. Worker lease/recovery, graceful shutdown and HTTP proxy timeouts need deployment-specific review; a lease deadline is not an inference time limit, and existing execution locks/fencing remain necessary. This phase does not change job semantics or activate the worker/scheduler.

macOS RSS is neither physical footprint nor Linux cgroup accounting: compression, shared mappings, filesystem cache and allocator behavior differ. These runs do not constrain CPU to one core, measure swap, persistent-server idle/health traffic, adversarial vocabulary, other languages, concurrent exports/uploads, multiple workers or long-term fragmentation. No PostgreSQL performance run was made in this phase. The database, OS, reverse proxy and platform agents need additional memory outside the figures above.

## Deferred Linux hard-limit verification

Linux cgroup memory-limit viability has not been verified. No 512 MiB, 1 GiB or 2 GiB Docker hard-limit benchmarks were performed. The 2 GiB hosting recommendation is provisional and must not be interpreted as a validated deployment guarantee.

Docker hard-limit benchmarking is explicitly deferred for this checkpoint. No Docker engine, image build or Linux container was started, and no Docker resources were created by this phase. Temporary Docker planning files remain outside the repository and are not part of the four-file checkpoint. No production-readiness claim follows from native macOS RSS measurements. Future Linux hard-limit and target-CPU verification requires separate authorization and must report actual OOM failures, resource accounting and incomplete cases.

## Reproduction and evidence

Run from the repository root with the existing pinned model installed. All inputs are generated locally; model checks use the pins in `backend/scripts/download_model.py`. JSON output must be outside the repository. Commands below can consume substantial CPU time; the maximum-row pair took about twelve minutes. The sampled guard can overshoot and is not an OOM guarantee.

```sh
# Two fresh interpreters per setting, three warm operations each.
backend/.venv/bin/python backend/scripts/benchmark_onnx.py --engines transformer --modes engine,pipeline,worker,api --counts 100 --lengths 80 --threads 1,2,4 --cold-runs 2 --repeats 3 --output /private/tmp/reviews-2d-calibration.json
# Count/length matrix.
backend/.venv/bin/python backend/scripts/benchmark_onnx.py --engines transformer --modes pipeline,worker,api --counts 1,1000 --lengths 80,500,5000 --threads 4 --repeats 2 --timeout 600 --output /private/tmp/reviews-2d-workloads.json
# Paired topology and maximum-row short-input load.
backend/.venv/bin/python backend/scripts/benchmark_onnx.py --engines transformer --modes api,worker --paired --counts 100 --lengths 80 --threads 1,2,4 --repeats 3 --output /private/tmp/reviews-2d-paired-threads.json
backend/.venv/bin/python backend/scripts/benchmark_onnx.py --engines transformer,vader --modes api,worker --paired --counts 20000 --lengths 80 --threads 4 --repeats 1 --timeout 1200 --output /private/tmp/reviews-2d-max-rows-paired.json
# Populated history; the new analysis reaches the existing 20-snapshot quota.
backend/.venv/bin/python backend/scripts/benchmark_onnx.py --engines transformer --modes worker,api --counts 1000 --lengths 5000 --history-count 19 --repeats 1 --timeout 600 --output /private/tmp/reviews-2d-history.json
# Repeat once with --arena off and a different output filename.
backend/.venv/bin/python backend/scripts/benchmark_onnx.py --engines transformer --modes worker,api --counts 20 --lengths 5000 --cold-runs 2 --repeats 3 --arena on --output /private/tmp/reviews-2d-arena-on.json
backend/.venv/bin/python backend/scripts/benchmark_onnx.py --engines vader,missing,runtime-failure --modes pipeline,worker,api --counts 1000 --lengths 80,5000 --repeats 2 --timeout 600 --output /private/tmp/reviews-2d-fallback.json
```

Raw reports use the eight filenames above (including `reviews-2d-arena-off.json`) under `/private/tmp`; `reviews-2d-results-index.json` records their SHA-256 hashes, child/warm counts and harness revision hashes. These are temporary local artifacts, not committed portable evidence. Calibration/workload reports predate incremental checkpoint reporting: they omit `completed`, but contain all 24/18 expected successful cases. Later reports have `completed: true`; interrupted checkpoint reports would retain false. Earlier pilot/thread-scan/smoke files are not the final measurement matrix. Harness revisions added reporting, history and fallback coverage during measurement; each report records its source hash.

Tests verify accounting units, Linux resident-page selection and process-exit races, bounded synthetic inputs, output placement, default-preserving session options, fallback selection, inherited private DB/auth isolation, history quotas and timeout child/temp cleanup. Latest focused validation: **114 passed**, including **37 benchmark tests**, the complete transformer-engine tests and NLP unit tests. The earlier narrower focused run reported 52 passed. Default backend: **673 passed, 28 skipped**; frontend: **242 passed**. Lint, production/demo builds, both bundle checks and `git diff --check` passed. Skips cover optional PostgreSQL/Ollama integrations; no new live PostgreSQL run is claimed.

All ten protected demo files and both existing application SQLite databases match their approved SHA-256 hashes. Only the engine injection hook, benchmark script, benchmark tests and this document are in scope. No generated benchmark artifacts or credentials are staged. No production model configuration, application data, GitHub Pages, worker/scheduler activation, commit or push is included. Local benchmarking is ready for review; final hosting selection remains conditional on Linux hard-cap/target-CPU verification and resolving maximum-input/history memory risk.
