"""The demo seed script: safety rules, repeatability and what it creates (Phase 8)."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "seed_demo.py"
REAL_DB = BACKEND / "storage" / "reviews_dekho.db"
sys.path.insert(0, str(BACKEND / "scripts"))
import make_demo_data  # noqa: E402
import seed_demo  # noqa: E402


def run(*args, env_db=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    if env_db:
        env["DATABASE_URL"] = env_db
    return subprocess.run([sys.executable, str(SCRIPT), "--engine", "vader", "--json", *args], cwd=BACKEND,
                          capture_output=True, text=True, env=env, timeout=300)


def digest_of(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def file_hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


# ---------- Safety (no subprocess needed: checks run before anything is touched) ----------

@pytest.mark.parametrize("target, reason", [
    (REAL_DB, "real database"),
    (BACKEND / "storage" / "reviews_dekho_demo.db", "real database"),
    (BACKEND / "storage" / "products.db", "isn't a demo database name"),
    (BACKEND / "storage" / "demo.sqlite", "isn't a demo database name"),
    (BACKEND / "app" / "demo.db", "inside the source tree"),
    (BACKEND / "data" / "demo" / "demo.db", "inside the source tree"),
])
def test_unsafe_targets_are_refused(target, reason):
    with pytest.raises(seed_demo.Refused, match=reason):
        seed_demo.check_target(str(target), reset=True)


def test_the_database_named_by_database_url_is_protected(tmp_path, monkeypatch):
    mine = tmp_path / "shop.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{mine}")
    seed_demo.check_target(str(tmp_path / "demo.db"), reset=False)          # a different, demo file is fine
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'my-demo-notes.db'}")
    seed_demo.check_target(str(tmp_path / "demo.db"), reset=False)


def test_symlinks_folders_and_unmarked_files_are_refused(tmp_path):
    real = tmp_path / "real.db"
    real.write_bytes(b"precious")
    (tmp_path / "demo.db").symlink_to(real)
    with pytest.raises(seed_demo.Refused, match="symbolic link"):
        seed_demo.check_target(str(tmp_path / "demo.db"), reset=True)
    (tmp_path / "folder-demo.db").mkdir()
    with pytest.raises(seed_demo.Refused, match="folder"):
        seed_demo.check_target(str(tmp_path / "folder-demo.db"), reset=True)
    unmarked = tmp_path / "other-demo.db"
    sqlite3.connect(unmarked).execute("CREATE TABLE notes (x)").connection.commit()
    with pytest.raises(seed_demo.Refused, match="wasn't made by this script"):
        seed_demo.check_target(str(unmarked), reset=True)
    with pytest.raises(seed_demo.Refused, match="already exists"):
        seed_demo.check_target(str(unmarked), reset=False)
    assert real.read_bytes() == b"precious" and unmarked.exists()


def test_refusal_exits_without_touching_anything():
    before = file_hash(REAL_DB)
    result = run("--db", str(REAL_DB), "--reset")
    assert result.returncode == 2 and "Refused" in result.stderr
    assert file_hash(REAL_DB) == before


# ---------- Seeding ----------

def test_seed_is_repeatable_and_protects_existing_demo_data(tmp_path):
    real_before = file_hash(REAL_DB)
    target = tmp_path / "demo.db"
    first = digest_of(run("--db", str(target)))
    assert seed_demo.has_marker(target)

    again = run("--db", str(target))                       # no --reset: refused, file untouched
    assert again.returncode == 2 and "already exists" in again.stderr
    assert first["contentDigest"] == seed_demo.content_digest(target)[0]

    second = digest_of(run("--db", str(target), "--reset"))
    assert second["contentDigest"] == first["contentDigest"]
    third = digest_of(run("--db", str(tmp_path / "other-demo.db")))
    assert third["contentDigest"] == first["contentDigest"]
    assert file_hash(REAL_DB) == real_before

    runs = [(r["product"], r["reviews"], r["analysed"]) for r in first["runs"]]
    assert runs == [("Aurora X5 (demo)", 150, 150), ("Kestrel Orbit 5G (demo)", 63, 63),
                    ("QuickCart (demo app)", 120, 120), ("QuickCart (demo app)", 210, 210),
                    ("Saffron Buds (demo)", 72, 60)]
    con = sqlite3.connect(target)
    assert con.execute("SELECT domain, category FROM products WHERE name = 'QuickCart (demo app)'").fetchone() == \
        ("app", "Shopping")
    # The new demo files use placeholder names; the Kestrel sample (Phase 1) has its own invented names.
    names = {n for (n,) in con.execute("SELECT DISTINCT r.reviewer FROM reviews r JOIN products p ON p.id = "
                                       "r.product_id WHERE p.name != 'Kestrel Orbit 5G (demo)'")}
    assert names and all(n.startswith("Demo user ") for n in names)


def test_demo_files_are_synthetic_and_reproducible(tmp_path, monkeypatch):
    monkeypatch.setattr(make_demo_data, "OUT", tmp_path)
    make_demo_data.main()
    committed = BACKEND / "data" / "demo"
    for csv_file in sorted(committed.glob("*.csv")):
        assert (tmp_path / csv_file.name).read_bytes() == csv_file.read_bytes(), csv_file.name
        assert all(line.split(",")[1].startswith("Demo user ") for line in csv_file.read_text().splitlines()[1:])
