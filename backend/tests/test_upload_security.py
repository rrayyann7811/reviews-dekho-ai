"""Synthetic upload abuse cases. No application database or network is used."""
import asyncio
import io
from zipfile import ZipFile, ZIP_DEFLATED

import httpx
import pytest
from starlette.datastructures import UploadFile

from app import config
from app.api.uploads import _read_upload
from app.errors import AppError
from app.resource_limits import ResourceLimitsMiddleware
from app.services import analysis
from app.collectors.http import get_json
from app.collectors.base import SourceUnavailable
from .conftest import csv_file, import_file, xlsx_bytes
from .test_auth import identity


def archive(entries):
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as z:
        for name, content in entries.items(): z.writestr(name, content)
    return buffer.getvalue()


def rewrite_sheet(content, change):
    with ZipFile(io.BytesIO(content)) as z:
        return archive({n: change(z.read(n)) if n == 'xl/worksheets/sheet1.xml' else z.read(n) for n in z.namelist()})


@pytest.mark.parametrize('content', [b'PK\x03\x04bad', b'%PDF-1.4', b'\xd0\xcf\x11\xe0abc', b'review\n\x01private'])
def test_csv_rejects_binary_signatures(client, content):
    response = client.post('/api/uploads/preview', files={'file':('a.csv', content, 'text/csv')})
    assert response.status_code == 400
    assert 'private' not in response.text


def test_limits_rows_columns_fields_and_file_size(client, monkeypatch):
    monkeypatch.setattr(config, 'MAX_COLUMNS', 2)
    assert client.post('/api/uploads/preview', files=csv_file('a,b,c\nx,y,z\n')).status_code == 413
    monkeypatch.setattr(config, 'MAX_CSV_FIELD_CHARS', 8)
    response = client.post('/api/uploads/preview', files=csv_file('review\n'+'x'*9+'\n'))
    assert response.status_code in (400, 413)
    assert 'xxxxxxxxx' not in response.text
    monkeypatch.setattr(config, 'MAX_UPLOAD_BYTES', 8)
    assert client.post('/api/uploads/preview', files=csv_file()).status_code == 413


def test_content_not_mime_determines_csv(client):
    response = client.post('/api/uploads/preview', files={'file':('a.csv',b'review\nGood product\n','image/png')})
    assert response.status_code == 200


@pytest.mark.parametrize('limit,value', [('MAX_XLSX_ENTRIES',1),('MAX_XLSX_EXPANDED_BYTES',50),
                                       ('MAX_XLSX_ENTRY_BYTES',50),('MAX_XLSX_RATIO',1)])
def test_xlsx_archive_budgets(client, monkeypatch, limit, value):
    content = xlsx_bytes([{'review':'fine'}])
    monkeypatch.setattr(config, limit, value)
    assert client.post('/api/uploads/preview', files={'file':('a.xlsx',content,'text/plain')}).status_code == 413


@pytest.mark.parametrize('payload', [b'not zip', archive({'bad':'not Excel'})])
def test_invalid_xlsx(client, payload):
    assert client.post('/api/uploads/preview', files={'file':('a.xlsx',payload)}).status_code == 400


def test_xlsx_formulas_and_hidden_sparse_dimensions(client, monkeypatch):
    content = xlsx_bytes([{'review':'=1+1'}])
    assert client.post('/api/uploads/preview', files={'file':('a.xlsx',content)}).status_code == 400
    content = xlsx_bytes([{'review':'good'}])
    sparse = rewrite_sheet(content, lambda b:b.replace(b'r="A2"',b'r="XFD2"'))
    assert client.post('/api/uploads/preview', files={'file':('a.xlsx',sparse)}).status_code == 413
    monkeypatch.setattr(config,'MAX_ROWS',1)
    sparse = rewrite_sheet(content, lambda b:b.replace(b'r="A2"',b'r="A999999"'))
    assert client.post('/api/uploads/preview', files={'file':('a.xlsx',sparse)}).status_code == 413


def test_xlsx_xml_entity_rejected(client):
    content = rewrite_sheet(xlsx_bytes([{'review':'good'}]), lambda b:b'<!DOCTYPE x [<!ENTITY private "secret">]>'+b)
    response = client.post('/api/uploads/preview', files={'file':('a.xlsx',content)})
    assert response.status_code == 400 and 'secret' not in response.text


def test_failed_analysis_rolls_back_all_imported_rows(client, monkeypatch):
    def fail(*args, **kwargs): raise AppError('Analysis unavailable.',503)
    monkeypatch.setattr(analysis,'run_analysis',fail)
    assert import_file(client).status_code == 503
    assert client.get('/api/products').json() == []


def test_product_and_history_limits_leave_existing_state(client, monkeypatch):
    product = import_file(client).json()
    monkeypatch.setattr(config,'MAX_PRODUCTS_PER_OWNER',1)
    assert import_file(client).status_code == 413
    monkeypatch.setattr(config,'MAX_ANALYSIS_RUNS',1)
    assert client.post(f'/api/products/{product["id"]}/analyze').status_code == 413
    assert len(client.get('/api/products').json()) == 1
    monkeypatch.setattr(config,'MAX_ROWS',6)
    response = client.post(f'/api/products/{product["id"]}/reviews',json={'reviews':[{'text':'Another good review'}]})
    assert response.status_code == 413
    assert client.get(f'/api/products/{product["id"]}/analysis').json()['stats']['totalReviews'] == 6


def test_upload_handle_closed_on_success_failure_and_cancellation(monkeypatch):
    async def run():
        for failure in (None, AppError('read failed'), asyncio.CancelledError()):
            file = UploadFile(io.BytesIO(b'review\ngood\n'),filename='a.csv')
            if failure:
                async def fail(*args): raise failure
                file.read = fail
                with pytest.raises(type(failure)): await _read_upload(file)
            else:
                await _read_upload(file)
            assert file.file.closed
    asyncio.run(run())


def test_body_limit_disconnect_and_admission(monkeypatch):
    async def run():
        called, output = [], []
        async def app(scope,receive,send): called.append(await receive())
        middleware = ResourceLimitsMiddleware(app)
        scope={'type':'http','method':'POST','path':'/api/uploads/preview','headers':[]}
        async def send(message): output.append(message)
        async def attempt(messages):
            async def receive(): return messages.pop(0)
            await middleware(scope,receive,send)
        monkeypatch.setattr(config,'MAX_REQUEST_BYTES',3)
        await attempt([{'type':'http.request','body':b'ab','more_body':True},{'type':'http.request','body':b'cd'}])
        assert output[0]['status'] == 413 and not called and middleware.active == 0
        output.clear()
        await attempt([{'type':'http.disconnect'}])
        assert not called and middleware.active == 0
        middleware.active=config.MAX_EXPENSIVE_REQUESTS
        await attempt([])
        assert output[0]['status'] == 429
        middleware.active=0
        await attempt([{'type':'http.request','body':b'abc'}])
        assert called[0]['body'] == b'abc' and middleware.active == 0
    asyncio.run(run())


def test_body_headers_and_malformed_multipart(client, monkeypatch):
    monkeypatch.setattr(config,'MAX_REQUEST_BYTES',100)
    assert client.post('/api/uploads/preview',content=b'x',headers={'Content-Length':'1000'}).status_code == 413
    assert client.post('/api/uploads/preview',content=b'x',headers={'Content-Encoding':'gzip'}).status_code == 415
    assert client.post('/api/uploads/preview',content=b'bad',headers={'Content-Type':'multipart/form-data'}).status_code == 400


def test_collection_response_size_limit(monkeypatch):
    monkeypatch.setattr(config,'MAX_COLLECTION_BYTES',5)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'{"private":"secret"}'))) as client:
        with pytest.raises(SourceUnavailable,match='size limit'):
            get_json(client,'https://example.invalid','Synthetic')


def test_spooled_files_closed_after_valid_and_rejected_requests(client, monkeypatch):
    import starlette.formparsers as parsers
    created = []
    original = parsers.SpooledTemporaryFile
    def track(*args, **kwargs):
        file = original(*args, **kwargs); created.append(file); return file
    monkeypatch.setattr(parsers, 'SpooledTemporaryFile', track)
    assert client.post('/api/uploads/preview', files=csv_file()).status_code == 200
    assert created and all(file.closed for file in created)
    assert client.post('/api/uploads/preview', files=csv_file('bad\n"unterminated')).status_code == 400
    assert all(file.closed for file in created)


def test_owner_resource_quota_is_private(client, identity, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from .test_auth import auth_header
    monkeypatch.setattr(config,'MAX_PRODUCTS_PER_OWNER',1)
    with TestClient(create_app()) as secured:
        def upload(user):
            return secured.post('/api/uploads/import', headers=auth_header(identity(user)), files=csv_file(),
                                data={'product_name':'Synthetic','columns':'{"text":"review_text"}'})
        alice, bob = upload('alice'), upload('bob')
        assert alice.status_code == bob.status_code == 201
        assert upload('alice').status_code == 413
        assert secured.post(f'/api/products/{bob.json()["id"]}/analyze',headers=auth_header(identity('alice'))).status_code == 404
        assert len(secured.get('/api/products',headers=auth_header(identity('bob'))).json()) == 1


def test_truncated_multipart_closes_unfinished_spool(client, monkeypatch):
    import starlette.formparsers as parsers
    created=[]
    original=parsers.SpooledTemporaryFile
    def track(*args, **kwargs):
        file=original(*args, **kwargs); created.append(file); return file
    monkeypatch.setattr(parsers,'SpooledTemporaryFile',track)
    content=b'--test\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\nContent-Type: text/csv\r\n\r\nreview\ngood'
    response=client.post('/api/uploads/preview',content=content,headers={'Content-Type':'multipart/form-data; boundary=test'})
    assert response.status_code in (400,422)
    assert created and all(file.closed for file in created)


def test_duplicate_zip_members_rejected(client):
    import warnings
    buffer=io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        with ZipFile(buffer,'w') as z:
            z.writestr('[Content_Types].xml','x');z.writestr('xl/workbook.xml','x');z.writestr('xl/workbook.xml','x')
    assert client.post('/api/uploads/preview',files={'file':('a.xlsx',buffer.getvalue())}).status_code == 400


def test_multipart_file_and_field_count_limits_close_all_handles(client, monkeypatch):
    import starlette.formparsers as parsers
    created=[]; original=parsers.SpooledTemporaryFile
    def track(*args,**kwargs):
        file=original(*args,**kwargs);created.append(file);return file
    monkeypatch.setattr(parsers,'SpooledTemporaryFile',track)
    files=[('file',('a.csv',b'review\ngood')),('other',('b.csv',b'review\ngood'))]
    assert client.post('/api/uploads/preview',files=files).status_code == 400
    assert all(file.closed for file in created)
    assert client.post('/api/uploads/preview',files=csv_file(),data={f'f{i}':'x' for i in range(9)}).status_code == 400
    assert all(file.closed for file in created)


def test_failed_review_addition_rolls_back_earlier_pending_rows(client, monkeypatch):
    product=import_file(client).json()
    monkeypatch.setattr(config,'MAX_ROWS',7)
    response=client.post(f'/api/products/{product["id"]}/reviews',json={'reviews':[{'text':'Good extra item'},{'text':'Bad extra item'}]})
    assert response.status_code == 413
    assert client.get(f'/api/products/{product["id"]}/reviews').json()['total'] == 6


def test_cancelled_multipart_parser_closes_spools(monkeypatch):
    import starlette.formparsers as parsers
    from starlette.requests import Request
    from fastapi import File, UploadFile as FastAPIUploadFile
    from app.upload_route import UploadRoute
    created=[]; original=parsers.SpooledTemporaryFile
    def track(*args,**kwargs):
        file=original(*args,**kwargs);created.append(file);return file
    monkeypatch.setattr(parsers,'SpooledTemporaryFile',track)
    async def endpoint(file: FastAPIUploadFile = File(...)):
        raise AssertionError('Cancelled multipart must not invoke the endpoint')
    async def run():
        content=b'--test\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\nreview\ngood'
        delivered=False
        async def receive():
            nonlocal delivered
            if delivered: raise asyncio.CancelledError()
            delivered=True
            return {'type':'http.request','body':content,'more_body':True}
        request=Request({'type':'http','method':'POST','path':'/upload','query_string':b'',
                         'headers':[(b'content-type',b'multipart/form-data; boundary=test')]},receive)
        with pytest.raises(asyncio.CancelledError):
            await UploadRoute('/upload',endpoint=endpoint,methods=['POST']).get_route_handler()(request)
        assert created and all(file.closed for file in created)
    asyncio.run(run())


def test_concurrent_requests_cannot_bypass_owner_admission(monkeypatch):
    from app.auth import Principal
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def app(scope, receive, send):
            entered.set(); await release.wait()
        middleware=ResourceLimitsMiddleware(app)
        monkeypatch.setattr(config,'MAX_EXPENSIVE_REQUESTS',3)
        messages=[]
        async def send(message): messages.append(message)
        async def receive(): return {'type':'http.request','body':b''}
        scope={'type':'http','method':'POST','path':'/api/uploads/import','headers':[],
               'state':{'principal':Principal('alice')}}
        first=asyncio.create_task(middleware(scope,receive,send))
        await entered.wait()
        await middleware(scope,receive,send)
        assert messages[0]['status']==429
        assert middleware.active==1 and middleware.owners=={'alice'}
        release.set();await first
        assert middleware.active==0 and not middleware.owners
        await middleware(scope,receive,send)
        assert middleware.active==0 and not middleware.owners
    asyncio.run(run())


def test_concurrent_sqlite_owner_quota_is_not_exceeded(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from sqlalchemy import select,func
    from app.database import make_engine,init_db
    from app.auth import Principal
    from app.models import Product
    from app.services.ownership import new_product_identity
    engine=make_engine(f'sqlite:///{tmp_path / "quota.db"}');init_db(engine)
    monkeypatch.setattr(config,'MAX_PRODUCTS_PER_OWNER',1)
    barrier=Barrier(2)
    def create(_):
        with Session(engine) as db:
            db.info['principal']=Principal('alice')
            barrier.wait(timeout=5)
            try:
                db.add(Product(name='Synthetic',**new_product_identity(db)));db.commit();return 'created'
            except AppError as exc:
                db.rollback();assert exc.status_code==413;return 'limited'
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(create,range(2)))==['created','limited']
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Product))==1
    finally:
        engine.dispose()


# Reuse the strict loopback/database-marker guard; never create a separate unguarded engine.
from .test_postgres_integration import pg, upgrade


def test_postgres_upload_quota_rejection_is_atomic_and_owner_scoped(pg, monkeypatch, identity):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker,Session
    from sqlalchemy import select,func
    from app import database
    from app.main import create_app
    from app.models import Product,Review,AnalysisResult
    from .test_auth import auth_header
    upgrade(pg)
    monkeypatch.setattr(database,'engine',pg)
    monkeypatch.setattr(database,'SessionLocal',sessionmaker(bind=pg,autoflush=False,expire_on_commit=False))
    monkeypatch.setattr(config,'MAX_PRODUCTS_PER_OWNER',1)
    with TestClient(create_app()) as client:
        def upload(user):
            return client.post('/api/uploads/import',headers=auth_header(identity(user)),files=csv_file(),
                               data={'product_name':'Synthetic','columns':'{"text":"review_text"}'})
        alice,bob=upload('alice'),upload('bob')
        assert alice.status_code==bob.status_code==201
        assert upload('alice').status_code==413
        monkeypatch.setattr(config,'MAX_ANALYSIS_RUNS',1)
        assert client.post(f'/api/products/{alice.json()["id"]}/reviews',headers=auth_header(identity()),
                           json={'reviews':[{'text':'Another synthetic review'}]}).status_code==413
        assert client.post(f'/api/products/{bob.json()["id"]}/analyze',headers=auth_header(identity())).status_code==404
    with Session(pg) as db:
        assert db.scalar(select(func.count()).select_from(Product))==2
        assert db.scalar(select(func.count()).select_from(Review))==12
        assert db.scalar(select(func.count()).select_from(AnalysisResult))==2
        for product in db.scalars(select(Product)):
            assert (product.expires_at-product.created_at).days==7


def test_postgres_concurrent_analysis_quota_respects_root_lock(pg, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from sqlalchemy import select,func
    from app.auth import Principal
    from app.models import AnalysisResult
    from app.services.products import get_product
    from .test_retention import seed
    from datetime import datetime,timezone
    upgrade(pg)
    product_id=seed(pg,created=datetime.now(timezone.utc))
    monkeypatch.setattr(config,'MAX_ANALYSIS_RUNS',2)
    barrier=Barrier(2)
    def analyze(_):
        with Session(pg) as db:
            db.info.update(principal=Principal('alice'),write_request=True)
            barrier.wait(timeout=5)
            try:
                analysis.run_analysis(db,get_product(db,product_id));db.commit();return 'analyzed'
            except AppError as exc:
                db.rollback();assert exc.status_code==413;return 'limited'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(analyze,range(2)))==['analyzed','limited']
    with Session(pg) as db:
        assert db.scalar(select(func.count()).select_from(AnalysisResult))==2


def test_relocated_worksheet_cannot_bypass_coordinate_preflight():
    from app.services import ingestion
    content=xlsx_bytes([{'review':'good'}])
    with ZipFile(io.BytesIO(content)) as z:
        entries={}
        for name in z.namelist():
            value=z.read(name)
            if name=='xl/worksheets/sheet1.xml':
                name='xl/alternative.xml';value=value.replace(b'r="A2"',b'r="XFD2"')
            if name=='xl/_rels/workbook.xml.rels':
                value=value.replace(b'worksheets/sheet1.xml',b'alternative.xml')
            entries[name]=value
    with pytest.raises(AppError,match='column limits'):
        ingestion._check_archive(archive(entries))


def test_worksheet_relationship_requires_xml_target():
    from app.services import ingestion
    content=xlsx_bytes([{'review':'good'}])
    with ZipFile(io.BytesIO(content)) as z:
        entries={n:z.read(n) for n in z.namelist()}
    entries['xl/_rels/workbook.xml.rels']=entries['xl/_rels/workbook.xml.rels'].replace(b'sheet1.xml',b'sheet1.dat')
    with pytest.raises(AppError,match='XML parts'):
        ingestion._check_archive(archive(entries))
