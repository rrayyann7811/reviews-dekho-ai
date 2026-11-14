# Synthetic demo reviews

**Every review, product and reviewer name in this folder is invented** for demonstrating and testing Reviews Dekho AI.
Nothing is copied from a real website or a real customer. Reviewer names are placeholders ("Demo user 001").

| File | What it shows |
|---|---|
| `aurora_x5_phone.csv` (150) | A second phone, to compare with the bundled Kestrel sample (`../sample/demo_kestrel_orbit_5g.csv`) |
| `quickcart_app_october.csv` (120) | An app (domain "app", category "Shopping") before a fictional update |
| `quickcart_app_november_update.csv` (90) | Reviews after the update — added to the same app, so it gets a second analysis run to compare |
| `saffron_buds_earphones_mixed_language.csv` (72) | Earphones with 12 Hinglish reviews, which the app marks "not analysed" |

Re-create the files with `.venv/bin/python scripts/make_demo_data.py` (deterministic; `git diff` should stay empty).
Load them into a separate demo database with `.venv/bin/python scripts/seed_demo.py` — see the main README.
