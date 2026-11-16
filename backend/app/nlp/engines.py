"""Sentiment engines: one interface, two implementations.

    engine.predict(["text", ...]) -> [{"label": "positive"|"neutral"|"negative", "score": -1..1}, ...]

* TransformerEngine — cardiffnlp/twitter-roberta-base-sentiment-latest, a RoBERTa
  model fine-tuned for 3-class sentiment (negative / neutral / positive). Runs an
  int8-quantized ONNX export with onnxruntime (no PyTorch). score = P(positive) - P(negative).
  predict() takes a list and processes it in batches of config.MODEL_BATCH_SIZE
  (1 by default, so every review's result is independent of the others; see config.py).
* VaderEngine — rule-based VADER with review-specific rules. Always available.

get_engine() picks the transformer when its files are installed
(scripts/download_model.py) and falls back to VADER otherwise. Every analysis
records which engine produced it, and why a fallback happened.
"""
import json
import logging
import threading
import time

import numpy as np

from .. import config
from .sentiment import score_text

log = logging.getLogger("reviews_dekho.nlp")

PIPELINE_VERSION = 2  # 1 = Phases 1-3 (VADER only, one product feature list)


class VaderEngine:
    id = "vader"
    name = "VADER (rule-based)"

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "model": "vaderSentiment 3.3.2 + review rules", "variant": None}

    def predict(self, texts: list[str]) -> list[dict]:
        results = []
        for text in texts:
            r = score_text(text)
            results.append({"label": r["label"], "score": r["compound"]})
        return results


class TransformerEngine:
    id = "transformer"
    name = "RoBERTa sentiment model"
    MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    LABELS = ("negative", "neutral", "positive")  # from the model's config.json

    def __init__(self, model_dir=None, *, session_options=None):
        import onnxruntime as ort  # imported here so the app still runs without it
        from tokenizers import Tokenizer

        model_dir = model_dir or config.MODEL_DIR
        cfg = json.loads((model_dir / "config.json").read_text())
        labels = tuple(cfg["id2label"][str(i)].lower() for i in range(len(cfg["id2label"])))
        if labels != self.LABELS:
            raise RuntimeError(f"Unexpected model labels {labels}")
        self.pad_id = cfg.get("pad_token_id", 1)
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=config.MODEL_MAX_TOKENS)
        # Optional injection supports isolated benchmarks; normal loading retains the exact defaults.
        options = session_options
        if options is None:
            options = ort.SessionOptions()
            options.intra_op_num_threads = 4
        self.session = ort.InferenceSession(str(model_dir / "model_quantized.onnx"), options,
                                            providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "model": self.MODEL,
                "variant": "int8-quantized ONNX (Xenova/twitter-roberta-base-sentiment-latest)"}

    def _run(self, texts: list[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch(texts)
        width = max(len(e.ids) for e in encodings)  # pad only to the longest text in this batch
        ids = np.full((len(texts), width), self.pad_id, dtype=np.int64)
        mask = np.zeros((len(texts), width), dtype=np.int64)
        for row, encoding in enumerate(encodings):
            ids[row, :len(encoding.ids)] = encoding.ids
            mask[row, :len(encoding.ids)] = 1
        inputs = {"input_ids": ids, "attention_mask": mask}
        logits = self.session.run(None, {k: v for k, v in inputs.items() if k in self.input_names})[0]
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        return exp / exp.sum(axis=1, keepdims=True)  # softmax -> probabilities

    def predict(self, texts: list[str]) -> list[dict]:
        results: list[dict | None] = [None] * len(texts)
        # Sort by length so each batch holds similar lengths (less padding, faster).
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        size = config.MODEL_BATCH_SIZE
        for start in range(0, len(order), size):
            batch = order[start:start + size]
            probabilities = self._run([texts[i] or "." for i in batch])
            for i, p in zip(batch, probabilities):
                results[i] = {"label": self.LABELS[int(p.argmax())], "score": round(float(p[2] - p[0]), 4)}
        return results


_vader = VaderEngine()
_transformer = None
_transformer_error = None
_lock = threading.Lock()


def _load_transformer():
    """Load the model once per process. Returns (engine, None) or (None, reason)."""
    global _transformer, _transformer_error
    with _lock:
        if _transformer is None and _transformer_error is None:
            started = time.perf_counter()
            try:
                if not (config.MODEL_DIR / "model_quantized.onnx").exists():
                    raise FileNotFoundError("model files are not installed (run scripts/download_model.py)")
                _transformer = TransformerEngine()
                log.info("Loaded sentiment model in %.1fs", time.perf_counter() - started)
            except Exception as exc:  # missing files, missing package, damaged model…
                # Stored with the run and shown in the UI, so don't include local folder paths.
                _transformer_error = f"{type(exc).__name__}: {exc}".replace(str(config.BACKEND_DIR), "backend")
                log.warning("Sentiment model unavailable, using VADER: %s", _transformer_error)
        return _transformer, _transformer_error


def reset_engines() -> None:
    """Forget the loaded model (used by tests and after installing the model)."""
    global _transformer, _transformer_error
    with _lock:
        _transformer, _transformer_error = None, None


def get_engine(preference: str | None = None):
    """Return (engine, fallback_reason). fallback_reason is None when the preferred engine is used."""
    preference = (preference or config.SENTIMENT_ENGINE).lower()
    if preference == "vader":
        return _vader, None
    engine, error = _load_transformer()
    if engine is not None:
        return engine, None
    return _vader, f"The sentiment model couldn’t be used, so VADER was used instead ({error})."


def vader_engine() -> VaderEngine:
    return _vader
