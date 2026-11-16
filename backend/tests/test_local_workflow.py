"""Real pinned-model integration; synthetic inputs and disposable SQLite only."""
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import config
from app.database import engine
from app.job_worker import run_once
from app.main import create_app
from app.nlp import engines
from .conftest import csv_file, import_file, xlsx_bytes

pytestmark = pytest.mark.skipif(
    not (config.MODEL_DIR / 'model_quantized.onnx').exists(), reason='pinned model not installed')
ROWS = [
    {'review': 'I love this phone. The battery is excellent and the camera is great.', 'rating': 5},
    {'review': 'Worst phone ever, I hate it. The battery is terrible and the camera is awful.', 'rating': 1},
    {'review': 'It arrived on Tuesday.', 'rating': 3},
]


def upload_files(kind):
    if kind == 'xlsx':
        return {'file': ('synthetic.xlsx', xlsx_bytes(ROWS),
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['review', 'rating'])
    writer.writeheader(); writer.writerows(ROWS)
    return csv_file(output.getvalue())


@pytest.fixture
def real_model(monkeypatch):
    monkeypatch.setattr(config, 'SENTIMENT_ENGINE', 'transformer')
    model, reason = engines.get_engine('transformer')
    assert model.id == 'transformer' and reason is None
    return model


@pytest.mark.parametrize('kind', ['csv', 'xlsx'])
def test_real_model_upload_persistence_and_reports(client, real_model, kind):
    files = upload_files(kind)
    preview = client.post('/api/uploads/preview', files=files)
    assert preview.status_code == 200 and preview.json()['rowCount'] == 3
    response = import_file(client, files=files, product_name=f'Synthetic {kind}',
                           columns={'text': 'review', 'rating': 'rating'})
    assert response.status_code == 201, response.text
    product_id = response.json()['id']
    result = client.get(f'/api/products/{product_id}/analysis').json()
    assert result['engine']['id'] == 'transformer' and result['engine']['fallbackReason'] is None
    assert result['stats']['sentimentCounts'] == {'positive': 1, 'neutral': 1, 'negative': 1}
    assert {r['sentiment'] for r in result['reviews']} == {'positive', 'neutral', 'negative'}
    assert {'Battery', 'Camera'} <= {a['aspect'] for a in result['aspects']}
    assert client.get(f'/api/products/{product_id}/reviews').json()['total'] == 3
    with TestClient(create_app()) as reopened:
        saved = reopened.get(f'/api/products/{product_id}/analysis').json()
        assert saved['analysisId'] == result['analysisId'] and saved['stats'] == result['stats']
        assert reopened.get(f'/api/history/{saved["analysisId"]}').json()['reviews'] == saved['reviews']
        pdf = reopened.get(f'/api/products/{product_id}/report.pdf')
        assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-') and len(pdf.content) > 1000
        report = reopened.get(f'/api/products/{product_id}/report.csv')
        assert report.status_code == 200
        assert len(list(csv.DictReader(io.StringIO(report.content.decode('utf-8-sig'))))) == 3
        assert 'It arrived on Tuesday.' in report.text


def test_finite_job_publishes_real_model_snapshot(client, real_model):
    response = import_file(client, files=upload_files('csv'), columns={'text': 'review', 'rating': 'rating'})
    assert response.status_code == 201
    product_id = response.json()['id']
    created = client.post(f'/api/products/{product_id}/jobs', json={'requestKey': 'synthetic_local_job'})
    assert created.status_code == 202 and created.json()['status'] == 'queued'
    job_id = created.json()['id']
    assert run_once(engine)
    job = client.get(f'/api/jobs/{job_id}').json()
    assert job['status'] == 'succeeded' and job['attempts'] == 1
    result = client.get(job['resultUrl']).json()
    assert result['engine']['id'] == 'transformer'
    assert result['stats']['sentimentCounts'] == {'positive': 1, 'neutral': 1, 'negative': 1}
    assert not run_once(engine)


def test_inference_failure_uses_supported_whole_run_fallback(client, real_model, monkeypatch):
    def failed_prediction(_):
        raise RuntimeError('Controlled synthetic inference failure')
    monkeypatch.setattr(real_model, 'predict', failed_prediction)
    response = import_file(client, files=upload_files('csv'), columns={'text': 'review', 'rating': 'rating'})
    assert response.status_code == 201, response.text
    result = client.get(f'/api/products/{response.json()["id"]}/analysis').json()
    assert result['engine']['id'] == 'vader' and result['engine']['fallbackReason']
    assert result['stats']['analysedReviews'] == 3
