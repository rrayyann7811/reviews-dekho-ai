"""Integrity manifest shared by the downloader and strict runtime."""
import hashlib
from pathlib import Path


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


def verify_model_files(model_dir: Path) -> None:
    for filename, expected in FILES.items():
        if sha256(model_dir / Path(filename).name) != expected:
            raise ValueError("Pinned model checksum mismatch")
