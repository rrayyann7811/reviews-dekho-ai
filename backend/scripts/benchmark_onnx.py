"""Fresh-process synthetic ONNX/VADER benchmark. Never opens application databases or starts a worker loop.

Run from backend/: .venv/bin/python scripts/benchmark_onnx.py --help
Outputs belong outside the repository; there is no network/model download path in this harness.
"""
import argparse
import ast
import ctypes
import errno
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time

BACKEND = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024


_rss_library = None
_rss_function = None


def rss_bytes(pid=None):
    """Current resident set (not virtual address space). No psutil dependency or subprocess sampling."""
    pid = os.getpid() if pid is None else pid
    if sys.platform == 'darwin':
        global _rss_library, _rss_function
        if _rss_function is None:
            _rss_library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
            _rss_function = _rss_library.proc_pidinfo
            _rss_function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            _rss_function.restype = ctypes.c_int
        function = _rss_function
        buffer = ctypes.create_string_buffer(96)  # proc_taskinfo: resident size is its second uint64
        size = function(pid, 4, 0, buffer, len(buffer))
        if size != len(buffer):
            code = ctypes.get_errno() or (errno.ESRCH if pid != os.getpid() and size == 0 else errno.EIO)
            raise OSError(code, 'Cannot read process RSS')
        return struct.unpack_from('Q', buffer.raw, 8)[0]
    if sys.platform.startswith('linux'):
        fields = Path(f'/proc/{pid}/statm').read_text().split()
        if len(fields) < 2:
            raise OSError(errno.ESRCH if pid != os.getpid() else errno.EIO, 'Cannot read process RSS')
        resident_pages = int(fields[1])
        return resident_pages * os.sysconf('SC_PAGE_SIZE')
    raise RuntimeError('RSS measurement supports macOS and Linux only')


def high_water_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def synthetic_reviews(count, chars):
    """Stable sentiment mix; no user text. Long inputs exercise the unchanged token truncation path."""
    prefixes = (
        'The battery is excellent and the camera is great. I am happy with this item. ',
        'The battery is terrible and the camera is poor. I am disappointed with this item. ',
        'The battery is normal and the camera is ordinary. I used this item yesterday. ',
    )
    filler = 'I have used this item every day at home and during my daily work. '
    rows = []
    for i in range(count):
        prefix = prefixes[i % len(prefixes)].replace('I ', f'Entry{i:05d}. I ', 1)
        text = (prefix + filler * (chars // len(filler) + 1))[:chars]
        rows.append({'id': f'synthetic-{i}', 'text': text, 'rating': (5, 1, 3)[i % 3],
                     'title': None, 'date': None, 'reviewer': None})
    return rows


class Monitor:
    def __init__(self, interval=0.01):
        self.interval = interval
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.peak = 0
        self.error = None
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self.stop.wait(self.interval):
            try:
                value = rss_bytes()
                with self.lock: self.peak = max(self.peak, value)
            except Exception:
                self.error = 'RSS sampler failed'
                return

    def __enter__(self):
        self.thread.start()
        return self

    def measure(self, name, operation):
        baseline = rss_bytes()
        with self.lock: self.peak = baseline
        start = time.perf_counter()
        result = operation()
        seconds = time.perf_counter() - start
        end = rss_bytes()
        with self.lock: peak = max(self.peak, baseline, end)
        if self.error: raise RuntimeError(self.error)
        return result, {'phase': name, 'seconds': seconds, 'start_rss_bytes': baseline,
                        'end_rss_bytes': end, 'sampled_peak_rss_bytes': peak,
                        'lifetime_peak_rss_bytes': high_water_bytes()}

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()


def predictions_digest(predictions):
    return hashlib.sha256(json.dumps(predictions, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def environment():
    packages = {}
    for name in ('onnxruntime', 'tokenizers', 'numpy', 'scikit-learn', 'SQLAlchemy', 'vaderSentiment'):
        try: packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name] = None
    return {'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
            'logical_cpus': os.cpu_count(), 'packages': packages, 'sample_interval_seconds': 0.01,
            'rss_method': 'libproc proc_pidinfo' if sys.platform == 'darwin' else '/proc/self/statm',
            'peak_method': 'getrusage ru_maxrss (bytes normalized)',
            'thread_environment': {name: os.getenv(name) for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                'MKL_NUM_THREADS', 'TOKENIZERS_PARALLELISM')}}


def file_manifest(model_dir):
    result = {}
    for name in ('model_quantized.onnx', 'tokenizer.json', 'config.json'):
        path = model_dir / name
        if path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(MIB), b''): digest.update(chunk)
            result[name] = {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
    return result


def budget_assessment(peak, budgets=(512, 1024, 2048)):
    return [{'ram_mib': value, 'measured_peak_rss_mib': peak / MIB,
             'remaining_mib': value - peak / MIB,
             'observed_process_rss_fits': peak <= value * MIB,
             'hard_limit_tested': False} for value in budgets]


def validate_case(case):
    if (type(case) is not dict or set(case) - {'history_count'} != {'engine', 'mode', 'count', 'chars', 'threads', 'repeats', 'arena', 'cold_run'}
            or case['engine'] not in {'transformer', 'vader', 'missing', 'runtime-failure'}
            or case['mode'] not in {'engine', 'pipeline', 'worker', 'api'}
            or type(case['arena']) is not bool
            or any(type(case[name]) is not int for name in ('count', 'chars', 'threads', 'repeats', 'cold_run'))
            or not 1 <= case['count'] <= 20000 or not 40 <= case['chars'] <= 5000
            or not 1 <= case['threads'] <= 8 or not 1 <= case['repeats'] <= 5 or not 0 <= case['cold_run'] <= 2
            or type(case.get('history_count', 0)) is not int or not 0 <= case.get('history_count', 0) <= 19
            or case.get('history_count', 0) + case['repeats'] > 20
            or (case.get('history_count', 0) and case['mode'] not in {'api', 'worker'})
            or (case['engine'] == 'runtime-failure' and case['mode'] == 'engine')):
        raise ValueError('Invalid or unbounded child case')


def child_case(case, start_file=None, ready_file=None):
    validate_case(case)
    # Set isolation BEFORE importing application modules. There is no user-supplied database option.
    sys.path.insert(0, str(BACKEND))
    phases = []
    wall_start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='reviews-onnx-benchmark-') as folder:
        for name in list(os.environ):
            if name.startswith(('DB_', 'JOB_', 'RATE_LIMIT_', 'MAX_', 'AUTH_')): os.environ.pop(name)
        os.environ['AUTH_MODE'] = 'local'
        os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(folder) / 'synthetic.db')
        os.environ.pop('TEST_POSTGRESQL_URL', None)
        os.environ['SENTIMENT_ENGINE'] = 'vader' if case['engine'] == 'vader' else 'auto'
        os.environ['AI_SUMMARIES'] = 'off'
        with Monitor() as monitor:
            _, item = monitor.measure('baseline', lambda: None); phases.append(item)
            def imports():
                from app import config
                from app.nlp import engines
                if case['mode'] != 'engine':
                    from app.nlp.pipeline import analyze_reviews  # noqa: F401
                if case['mode'] == 'worker':
                    from app.job_worker import run_once  # noqa: F401
                if case['mode'] == 'api':
                    from app.main import create_app  # noqa: F401
                return config, engines
            (config, engines), item = monitor.measure('imports', imports); phases.append(item)
            if config.MODEL_BATCH_SIZE != 1:
                raise RuntimeError('Benchmark requires semantics-preserving production batch size one')
            if start_file is not None:
                if ready_file is None: raise ValueError('Missing benchmark synchronization target')
                ready_file.touch()
                deadline = time.monotonic() + 300
                while not start_file.exists():
                    if time.monotonic() > deadline: raise TimeoutError('Benchmark synchronization expired')
                    time.sleep(0.01)
            if case['engine'] == 'missing':
                config.MODEL_DIR = Path(folder) / 'missing-model'
            original = engines.TransformerEngine
            def load():
                if case['engine'] in {'transformer', 'runtime-failure'} and engines._transformer is None and engines._transformer_error is None:
                    import onnxruntime as ort
                    options = ort.SessionOptions()
                    options.intra_op_num_threads = case['threads']
                    options.enable_cpu_mem_arena = case['arena']
                    engines.TransformerEngine = lambda: original(session_options=options)
                return engines.get_engine('vader' if case['engine'] == 'vader' else 'transformer')
            (engine, reason), item = monitor.measure('model_load', load); phases.append(item)
            if case['engine'] in {'transformer', 'runtime-failure'} and engine.id != 'transformer':
                raise RuntimeError('Transformer benchmark fell back; refusing mislabeled measurement')
            if case['engine'] == 'missing' and (engine.id != 'vader' or not reason):
                raise RuntimeError('Missing-model fallback was not exercised')
            runtime_options = None
            token_width = None
            if engine.id == 'transformer':
                options = engine.session.get_session_options()
                runtime_options = {name: getattr(options, name) for name in
                    ('intra_op_num_threads', 'inter_op_num_threads', 'enable_cpu_mem_arena', 'enable_mem_pattern')}
                runtime_options['execution_mode'] = str(options.execution_mode)
                runtime_options['providers'] = engine.session.get_providers()
            (again, _), item = monitor.measure('cached_load', load); phases.append(item)
            if again is not engine: raise RuntimeError('Engine cache did not reuse the instance')
            reviews, item = monitor.measure('synthetic_input', lambda: synthetic_reviews(case['count'], case['chars']))
            phases.append(item)
            texts = [r['text'] for r in reviews]
            input_digest = predictions_digest(texts)
            if engine.id == 'transformer': token_width = len(engine.tokenizer.encode(texts[0]).ids)
            # One fixed warmup; cold first prediction remains separately measured.
            _, item = monitor.measure('first_prediction', lambda: engine.predict([texts[0]])); phases.append(item)
            cold_ready_ns = time.monotonic_ns()
            selected_id = 'vader' if case['engine'] in {'missing', 'runtime-failure'} else case['engine']
            def verify_selection(metadata):
                if metadata['id'] != selected_id: raise RuntimeError('Unexpected inference engine selection')
                if case['engine'] == 'runtime-failure' and not metadata.get('fallbackReason'):
                    raise RuntimeError('Runtime fallback was not exercised')
            calls = 0
            real_predict = engine.predict
            def counted_predict(values):
                nonlocal calls
                calls += len(values)
                if case['engine'] == 'runtime-failure': raise RuntimeError('Synthetic model inference failure')
                return real_predict(values)
            engine.predict = counted_predict
            db_engine = None
            setup = None
            api_client = None
            if case['mode'] in {'worker', 'api'}:
                from app.database import make_engine, init_db
                from app.models import Product, Review
                from app.services.jobs import create
                from app.auth import Principal
                from sqlalchemy.orm import Session
                from app.job_worker import run_once
                def setup_worker():
                    target = make_engine(os.environ['DATABASE_URL']); init_db(target)
                    with Session(target) as db:
                        product = Product(name='Synthetic benchmark', owner_id='local', source='manual')
                        product.reviews = [Review(external_id=r['id'], text=r['text'], rating=r['rating']) for r in reviews]
                        db.add(product); db.commit(); product_id = product.id
                    return target, product_id
                (db_engine, product_id), setup = monitor.measure('worker_database_setup', setup_worker)
                phases.append(setup)
                if case['mode'] == 'api':
                    from fastapi.testclient import TestClient
                    from app.main import create_app
                    api_client = TestClient(create_app())
                    api_client.__enter__()
                if case.get('history_count', 0):
                    from app.services import analysis as analysis_service
                    from app.models import AnalysisResult
                    from sqlalchemy import insert, select
                    def seed_history():
                        # Historical rows are valid synthetic VADER snapshots; measured work still uses the requested engine.
                        original_analyse = analysis_service.analyze_reviews
                        analysis_service.analyze_reviews = lambda *a, **kw: original_analyse(*a, engine_preference='vader', **kw)
                        try:
                            with Session(db_engine) as db:
                                initial = analysis_service.run_analysis(db, db.get(Product, product_id))
                                db.commit(); initial_id = initial.id
                        finally:
                            analysis_service.analyze_reviews = original_analyse
                        table = AnalysisResult.__table__
                        columns = [column for column in table.columns if column.name != 'id']
                        with db_engine.begin() as conn:
                            for _ in range(case['history_count'] - 1):
                                conn.execute(insert(table).from_select([column.name for column in columns],
                                    select(*columns).where(table.c.id == initial_id)))
                    _, item = monitor.measure('synthetic_history_seed', seed_history); phases.append(item)
                def operation(index):
                    if api_client is not None:
                        response = api_client.post(f'/api/products/{product_id}/analyze')
                        if response.status_code != 200: raise RuntimeError('Synthetic API analysis failed')
                        value = response.json()
                        verify_selection(value['engine'])
                        if value['stats']['analysedReviews'] != case['count']: raise RuntimeError('Synthetic API input skipped analysis')
                        return [{'label': r['sentiment'], 'score': r['score']} for r in value['reviews']]

                    with Session(db_engine) as db:
                        db.info['principal'] = Principal('local', local=True)
                        job = create(db, product_id, f'benchmark-{index:08d}'); db.commit(); job_id = job.id
                    if not run_once(db_engine): raise RuntimeError('Synthetic worker job was not processed')
                    from app.models import ProcessingJob, AnalysisResult
                    with Session(db_engine) as db:
                        job = db.get(ProcessingJob, job_id)
                        if job.status != 'succeeded': raise RuntimeError('Synthetic worker job failed')
                        result = db.get(AnalysisResult, job.result_analysis_id)
                        verify_selection(result.engine)
                        if result.stats['analysedReviews'] != case['count']: raise RuntimeError('Synthetic worker input skipped analysis')
                        return [{'label': r['sentiment'], 'score': r['score']} for r in result.review_results]
            elif case['mode'] == 'pipeline':
                from app.nlp.pipeline import analyze_reviews
                def operation(index):
                    result = analyze_reviews(reviews, product_name='Synthetic benchmark')
                    verify_selection(result['engine'])
                    if result['stats']['analysedReviews'] != case['count']: raise RuntimeError('Synthetic pipeline input skipped analysis')
                    return [{'label': r['sentiment'], 'score': r['score']} for r in result['reviews']]
            else:
                def operation(index): return engine.predict(texts)
            digests, times, inference_count = [], [], []
            for index in range(case['repeats']):
                calls = 0
                result, item = monitor.measure(f'warm_{index}', lambda: operation(index)); phases.append(item)
                digests.append(predictions_digest(result)); times.append(item['seconds']); inference_count.append(calls)
                del result
            if len(set(digests)) != 1: raise RuntimeError('Repeated deterministic predictions differed')
            if api_client is not None: api_client.__exit__(None, None, None)
            if db_engine is not None: db_engine.dispose()
            engine.predict = real_predict
            del reviews, texts, again, engine, real_predict, counted_predict
            engines.reset_engines()
            _, item = monitor.measure('reset_and_gc', gc.collect); phases.append(item)
            peak = high_water_bytes()
    return {'case': case, 'selected_engine': selected_id, 'cold_ready_monotonic_ns': cold_ready_ns,
            'fallback_exercised': bool(reason) or case['engine'] == 'runtime-failure', 'cache_reused': True, 'phases': phases,
            'runtime_options': runtime_options, 'first_text_tokens_after_truncation': token_width,
            'synthetic_input_digest': input_digest,
            'warm_seconds': times, 'median_warm_seconds': statistics.median(times),
            'reviews_per_second': case['count'] / statistics.median(times),
            'inference_texts_per_repeat': inference_count, 'prediction_digest': digests[0],
            'peak_rss_bytes': peak, 'elapsed_seconds': time.perf_counter() - wall_start,
            'budgets': budget_assessment(peak)}


def run_children(cases, timeout, max_rss_mib, *, synchronize=False):
    processes, handles, launch_times = [], [], []
    with tempfile.TemporaryDirectory(prefix='reviews-onnx-supervisor-') as folder:
        root = Path(folder); gate = root / 'start'
        last_rss = {}
        try:
            for i, case in enumerate(cases):
                stdout = (root / f'{i}.json').open('w'); stderr = (root / f'{i}.log').open('w')
                handles.extend((stdout, stderr))
                command = [sys.executable, str(Path(__file__).resolve()), '--child-case', json.dumps(case)]
                if synchronize: command += ['--start-file', str(gate), '--ready-file', str(root / f'{i}.ready')]
                launch_times.append(time.monotonic_ns())
                processes.append(subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True,
                    env={**os.environ, 'TMPDIR': str(root)}))
            started = time.monotonic(); aggregate_peak = 0
            while any(process.poll() is None for process in processes):
                if time.monotonic() - started > timeout: raise TimeoutError('Synthetic benchmark exceeded timeout')
                if synchronize and not gate.exists() and all((root / f'{i}.ready').exists() for i in range(len(cases))): gate.touch()
                resident = 0
                for process in processes:
                    if process.poll() is None:
                        try:
                            last_rss[process.pid] = rss_bytes(process.pid)
                        except OSError as error:
                            if process.poll() is None and error.errno not in (errno.ESRCH, errno.ENOENT): raise
                        resident += last_rss.get(process.pid, 0)
                aggregate_peak = max(aggregate_peak, resident)
                if resident > max_rss_mib * MIB: raise MemoryError(f'Synthetic benchmark RSS {resident} bytes exceeded safety guard {max_rss_mib * MIB} bytes')
                time.sleep(0.01)
            for process in processes:
                if process.returncode: raise RuntimeError('Synthetic benchmark child failed; inspect temporary isolated run')
            if any(not last_rss.get(process.pid) for process in processes):
                raise RuntimeError('RSS sampling did not observe every benchmark child')
            values = [json.loads((root / f'{i}.json').read_text()) for i in range(len(cases))]
            for value, launched in zip(values, launch_times):
                value['process_start_to_first_prediction_seconds'] = (value['cold_ready_monotonic_ns'] - launched) / 1e9
                del value['cold_ready_monotonic_ns']
            return values, aggregate_peak
        finally:
            for process in processes:
                if process.poll() is None: process.kill()
            for process in processes: process.wait()
            for handle in handles: handle.close()


def model_pin():
    tree = ast.parse((BACKEND / 'scripts/download_model.py').read_text())
    pins = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FILES' for t in node.targets))
    return {Path(name).name: value for name, value in pins.items()}


def write_report(report, target):
    target = target.resolve()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, prefix='.onnx-benchmark-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, indent=2)
            stream.write('\n')
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()


def parse_numbers(value):
    return [int(part) for part in value.split(',')]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engines', default='transformer,vader,missing')
    parser.add_argument('--modes', default='engine,pipeline,worker')
    parser.add_argument('--counts', type=parse_numbers, default=[1, 100])
    parser.add_argument('--lengths', type=parse_numbers, default=[80, 500])
    parser.add_argument('--threads', type=parse_numbers, default=[4])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cold-runs', type=int, default=1)
    parser.add_argument('--arena', choices=['on', 'off'], default='on')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--history-count', type=int, default=0, help='Seed 0-19 synthetic snapshots before measured API/worker analysis')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--paired', action='store_true', help='Run API and finite synthetic worker processes together')
    parser.add_argument('--max-rss-mib', type=int, default=1536, help='Supervisor safety guard; sampled RSS, not a hard memory limit')
    parser.add_argument('--start-file', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--ready-file', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--child-case', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child_case:
        print(json.dumps(child_case(json.loads(args.child_case), args.start_file, args.ready_file)))
        return 0
    engines, modes = args.engines.split(','), args.modes.split(',')
    if (set(engines) - {'transformer', 'vader', 'missing', 'runtime-failure'} or set(modes) - {'engine', 'pipeline', 'worker', 'api'}
            or not args.counts or not args.lengths or not args.threads
            or any(not 1 <= n <= 20000 for n in args.counts)
            or any(not 40 <= n <= 5000 for n in args.lengths)
            or any(not 1 <= n <= 8 for n in args.threads)
            or not 256 <= args.max_rss_mib <= 2048
            or not 1 <= args.repeats <= 5 or not 1 <= args.cold_runs <= 3 or not 1 <= args.timeout <= 1800):
        parser.error('Invalid or unbounded benchmark configuration')
    if (not 0 <= args.history_count <= 19 or args.history_count + args.repeats > 20
            or (args.history_count and set(modes) - {'api', 'worker'})
            or ('runtime-failure' in engines and 'engine' in modes)):
        parser.error('History or runtime-failure case is incompatible with the selected modes/repeats')
    if args.output and args.output.resolve().is_relative_to(BACKEND.parent.resolve()):
        parser.error('Write generated benchmark output outside the repository')
    if args.paired and set(modes) != {'api', 'worker'}:
        parser.error('Paired mode requires --modes api,worker')
    report = {'schema_version': 1, 'environment': environment(), 'model_files': file_manifest(
        Path(os.getenv('MODEL_DIR', str(BACKEND / 'models/twitter-roberta-sentiment')))),
        'cold_start_definition': 'new interpreter; OS filesystem/page cache not flushed',
        'hard_memory_limits_applied': False, 'completed': False, 'results': [], 'paired_results': [],
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'supervised_rss_guard_mib': args.max_rss_mib}
    if set(engines) & {'transformer', 'runtime-failure'} and any(report['model_files'].get(name, {}).get('sha256') != value
                                       for name, value in model_pin().items()):
        parser.error('Installed model files do not match the existing pinned model')
    if args.output: write_report(report, args.output)
    for engine in engines:
        for mode in (['paired'] if args.paired else modes):
            for count in args.counts:
                for chars in args.lengths:
                    for threads in (args.threads if engine in {'transformer', 'runtime-failure'} else [1]):
                        for cold_run in range(args.cold_runs):
                            case = {'engine': engine, 'mode': mode, 'count': count, 'chars': chars,
                                    'threads': threads, 'repeats': args.repeats, 'arena': args.arena == 'on',
                                    'cold_run': cold_run}
                            if args.history_count: case['history_count'] = args.history_count
                            started = time.perf_counter()
                            if args.paired:
                                cases = [{**case, 'mode': name} for name in ('api', 'worker')]
                                values, peak = run_children(cases, args.timeout, args.max_rss_mib, synchronize=True)
                                report['paired_results'].append({'case': case, 'children': values,
                                    'aggregate_sampled_peak_rss_bytes': peak,
                                    'sum_individual_peak_rss_bytes': sum(value['peak_rss_bytes'] for value in values),
                                    'budgets': budget_assessment(peak)})
                                if args.output: write_report(report, args.output)
                                print(f"{engine}/paired n={count} chars={chars}: {peak/MIB:.1f} MiB aggregate", file=sys.stderr)
                                continue
                            values, _ = run_children([case], args.timeout, args.max_rss_mib)
                            result = values[0]
                            result['parent_wall_seconds'] = time.perf_counter() - started
                            report['results'].append(result)
                            if args.output: write_report(report, args.output)
                            print(f"{engine}/{mode} n={count} chars={chars} threads={threads}: "
                                  f"{result['peak_rss_bytes']/MIB:.1f} MiB, {result['reviews_per_second']:.1f} reviews/s", file=sys.stderr)
    report['completed'] = True
    encoded = json.dumps(report, indent=2)
    if args.output:
        target = args.output.resolve()
        if target.is_relative_to(BACKEND.parent.resolve()):
            parser.error('Write generated benchmark output outside the repository')
        write_report(report, target)
    else: print(encoded)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
