"""Download the pretrained sentiment model used by the "transformer" engine.

Model:   cardiffnlp/twitter-roberta-base-sentiment-latest (RoBERTa-base, 3 classes, CC-BY-4.0)
Files:   int8-quantized ONNX export by Xenova (community conversion of the model above)
Size:    about 128 MB in total. Saved to backend/models/ (git-ignored).

The files are pinned to one exact repository revision and checked against
SHA-256 hashes, so everyone gets byte-for-byte the same model that was evaluated
(docs/PLAN.md, Phase 4). Without these files the app falls back to VADER.

Run from backend/:  .venv/bin/python scripts/download_model.py
"""
import hashlib
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402

REPO = "Xenova/twitter-roberta-base-sentiment-latest"
REVISION = "f3ec4d0925f90c3ca7ee7814f52d6ee7cf180445"
FILES = {  # file in the repository -> SHA-256
    "onnx/model_quantized.onnx": "046f7e4cc46b399558fa9b2de966f6b0d42c69e4b01f582bfb4099b01a0bb5d7",
    "tokenizer.json": "1e6506713f00e34406a757acb80f9f3233c1c3950857d32bbc41bcd419d5d8b6",
    "config.json": "cdf2b36e0066bd9996e3b9fb3f7c095dc656a0e62c6e3a7327d4ff5541e55b51",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    target_dir = config.MODEL_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0)) as client:
        for name, expected in FILES.items():
            target = target_dir / Path(name).name
            if target.exists() and expected and sha256(target) == expected:
                print(f"✓ {target.name} already present")
                continue
            url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
            print(f"↓ {name} …", flush=True)
            partial = target.with_suffix(target.suffix + ".part")
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with partial.open("wb") as f:
                    for chunk in response.iter_bytes(1 << 20):
                        f.write(chunk)
            actual = sha256(partial)
            if expected and actual != expected:
                partial.unlink()
                print(f"✗ {name}: checksum mismatch (expected {expected}, got {actual}). Nothing was kept.")
                return 1
            partial.replace(target)
            print(f"✓ {target.name}  {target.stat().st_size / 1e6:.1f} MB  sha256={actual}")
    print(f"Model ready in {target_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
