# AI overview evaluations

Live measurements of the optional AI overview (local Ollama model). Each file is one run; runs are never merged or
regenerated, and later runs don't replace earlier ones.

| File | What it is |
|---|---|
| `phase6-round4-historical.json` | The Phase 6 final round (2026-11-14): 11 cases — 8 synthetic, the synthetic bundled sample, and two **real App Store** apps. 8 of 10 generated overviews accepted; manual review of the 24 accepted sentences: 20 fully, 4 partially, 0 unsupported. For the App Store cases only numbers are kept (no model answers, sentences or review text). Written in Phase 8 from that run's saved output; the Phase 6 harness itself was not version-controlled. |
| `run-2026-11-14-phase8.json` | A new run with the version-controlled harness (`backend/scripts/evaluate_ai_overview.py`) on the 9 synthetic cases: 7 of 8 generated overviews accepted. **Manual review not done** (every `label` is empty). Not a reproduction of Phase 6: the overview wording changed in between (the majority fix), so most answers differ; the three cases whose input didn't change produced byte-identical answers. |

Reproduce a run (needs Ollama running with `llama3.2:3b`; nothing is downloaded or started by the script):

```bash
cd backend && .venv/bin/python scripts/evaluate_ai_overview.py --out ../docs/evaluation/ai_overview/run-<date>.json
```

The automatic checker is not a guarantee of factual accuracy. Acceptance only means no checkable error was found;
whether accepted sentences are supported by their evidence needs the manual review described in each file.
