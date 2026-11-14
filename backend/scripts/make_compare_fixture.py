"""Writes frontend/src/test/fixtures/comparison.json from the real /api/compare endpoint (synthetic reviews, VADER).
Run from backend/: .venv/bin/python scripts/make_compare_fixture.py ../frontend/src/test/fixtures/comparison.json
The reviews are synthetic, written for testing only."""
import json, os, sys, tempfile
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/fixture.db"
os.environ["SENTIMENT_ENGINE"] = "vader"
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from app.main import app

def rows(spec):
    out, i = "id,review,stars,date\n", 0
    for text, stars, count in spec:
        for _ in range(count):
            out += f"R{i},\"{text} ({i})\",{stars},2026-10-{1 + i % 28:02d}\n"; i += 1
    return out

alpha = rows([("The battery is excellent and lasts two days", 5, 35), ("Lovely display, very bright", 5, 10),
              ("The camera is terrible in low light", 1, 15), ("Delivery was slow", 2, 5), ("It is a phone", 3, 5)])
beta = rows([("The battery drains far too quickly", 1, 120), ("The display is great", 5, 60),
             ("Camera takes excellent photos", 5, 80), ("Packaging was damaged", 2, 30),
             ("bakwas phone hai yaar battery kharab", 1, 40)])
cols = json.dumps({"text": "review", "rating": "stars", "id": "id", "date": "date"})
with TestClient(app) as c:
    ids = [c.post("/api/uploads/import", files={"file": (f"{n}.csv", t.encode(), "text/csv")},
                  data={"product_name": n, "columns": cols, "domain": "product"}).json()["id"]
           for n, t in (("Alpha Phone", alpha), ("Beta Phone", beta))]
    body = c.get("/api/compare", params={"product_a": ids[0], "product_b": ids[1]}).json()
json.dump(body, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
print(ids, body["a"]["counts"], body["b"]["counts"], [c["code"] for c in body["caveats"]])
for s in body["statements"]: print(" S", s)
for f in body["features"]: print(" F", f["aspect"], f["a"]["status"], f["b"]["status"], f["comparable"])
