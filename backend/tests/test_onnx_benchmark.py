"""Benchmark accounting and isolation, not assertions about machine-specific performance."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import config
from app.nlp.engines import TransformerEngine

PATH = Path(__file__).resolve().parents[1] / 'scripts/benchmark_onnx.py'
spec = importlib.util.spec_from_file_location('onnx_benchmark', PATH)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def case(**changes):
    return {'engine': 'vader', 'mode': 'engine', 'count': 3, 'chars': 80, 'threads': 1,
            'repeats': 2, 'arena': True, 'cold_run': 0, **changes}


def test_synthetic_inputs_are_bounded_deterministic_and_distinct():
    rows = benchmark.synthetic_reviews(10, 5000)
    assert rows == benchmark.synthetic_reviews(10, 5000)
    assert len({row['id'] for row in rows}) == 10
    assert len({row['text'] for row in rows}) == 10
    assert all(len(row['text']) == 5000 and row['reviewer'] is None for row in rows)


@pytest.mark.parametrize('changes', [{'count': 0}, {'count': 20001}, {'chars': 5001}, {'threads': 9},
    {'repeats': 6}, {'arena': 'on'}, {'cold_run': 3}, {'mode': 'production'}, {'engine': 'remote'},
    {'count': True}, {'database': 'private.db'}])
def test_child_configuration_cannot_bypass_bounds(changes):
    with pytest.raises(ValueError): benchmark.validate_case(case(**changes))


def test_budget_units_and_boundary_do_not_claim_hard_limits():
    values = benchmark.budget_assessment(512 * benchmark.MIB + 1)
    assert not values[0]['observed_process_rss_fits']
    assert values[1]['observed_process_rss_fits'] and values[2]['observed_process_rss_fits']
    assert all(not value['hard_limit_tested'] for value in values)


def test_phase_peak_is_not_an_invalid_subtraction_of_high_water_marks(monkeypatch):
    monkeypatch.setattr(benchmark, 'rss_bytes', lambda: 1000)
    monkeypatch.setattr(benchmark, 'high_water_bytes', lambda: 2000)
    result, record = benchmark.Monitor().measure('measured', lambda: 42)
    assert result == 42 and record['sampled_peak_rss_bytes'] == 1000
    assert record['lifetime_peak_rss_bytes'] == 2000 and record['seconds'] >= 0


@pytest.mark.parametrize('system,expected', [('darwin', 123), ('linux', 123 * 1024)])
def test_peak_rss_units_are_normalized(monkeypatch, system, expected):
    monkeypatch.setattr(benchmark.sys, 'platform', system)
    monkeypatch.setattr(benchmark.resource, 'getrusage', lambda _: SimpleNamespace(ru_maxrss=123))
    assert benchmark.high_water_bytes() == expected


def test_generated_artifacts_are_refused_inside_repository(monkeypatch):
    monkeypatch.setattr(benchmark, 'run_children', lambda *args, **kwargs: pytest.fail('must reject before spawning'))
    with pytest.raises(SystemExit):
        benchmark.main(['--engines', 'vader', '--output', str(PATH.parent / 'do-not-create.json')])
    assert not (PATH.parent / 'do-not-create.json').exists()


@pytest.mark.parametrize('mode,engine', [('engine', 'missing'), ('pipeline', 'vader'), ('worker', 'vader'), ('api', 'vader')])
def test_fresh_process_uses_synthetic_database_and_ignores_host_auth(tmp_path, monkeypatch, mode, engine):
    sentinel = tmp_path / 'private-application.db'
    sentinel.write_bytes(b'private sentinel must not be opened or modified')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(sentinel))
    monkeypatch.setenv('TEST_POSTGRESQL_URL', 'postgresql+psycopg://private.invalid/private')
    monkeypatch.setenv('AUTH_MODE', 'jwt')
    monkeypatch.setenv('RATE_LIMIT_ANALYSIS_REQUESTS', '1')
    monkeypatch.setenv('MAX_ROWS', '1')
    process = subprocess.run([sys.executable, str(PATH), '--child-case', json.dumps(case(mode=mode, engine=engine))],
                             text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result['selected_engine'] == 'vader' and result['fallback_exercised'] == (engine == 'missing')
    assert result['cache_reused'] and len(result['warm_seconds']) == 2
    assert result['peak_rss_bytes'] > 0 and result['reviews_per_second'] > 0
    assert sentinel.read_bytes() == b'private sentinel must not be opened or modified'


@pytest.mark.parametrize('injected', [False, True])
def test_session_options_injection_preserves_production_defaults(tmp_path, monkeypatch, injected):
    import types
    tokenizer = MagicMock()
    session = MagicMock(); session.get_inputs.return_value = [SimpleNamespace(name='input_ids')]
    factory = MagicMock(return_value=session)
    options_factory = MagicMock(return_value=SimpleNamespace(intra_op_num_threads=0))
    monkeypatch.setitem(sys.modules, 'onnxruntime', types.SimpleNamespace(
        SessionOptions=options_factory, InferenceSession=factory))
    monkeypatch.setitem(sys.modules, 'tokenizers', types.SimpleNamespace(
        Tokenizer=SimpleNamespace(from_file=lambda _: tokenizer)))
    (tmp_path / 'config.json').write_text(json.dumps({'id2label': {'0': 'negative', '1': 'neutral', '2': 'positive'}}))
    custom = SimpleNamespace(intra_op_num_threads=2) if injected else None
    TransformerEngine(tmp_path, session_options=custom)
    options = factory.call_args.args[1]
    assert options.intra_op_num_threads == (2 if injected else 4)
    if injected:
        assert options is custom and not options_factory.called
    tokenizer.enable_truncation.assert_called_once_with(max_length=256)
    assert config.MODEL_BATCH_SIZE == 1


@pytest.mark.parametrize('changes', [{'history_count': -1}, {'history_count': 20}, {'history_count': True},
    {'history_count': 19, 'repeats': 2, 'mode': 'worker'}, {'history_count': 1, 'mode': 'pipeline'},
    {'engine': 'runtime-failure', 'mode': 'engine'}])
def test_history_and_runtime_failure_cases_remain_bounded(changes):
    with pytest.raises(ValueError): benchmark.validate_case(case(**changes))


@pytest.mark.parametrize('mode', ['api', 'worker'])
def test_populated_history_is_synthetic_and_preserves_analysis_quota(mode):
    process = subprocess.run([sys.executable, str(PATH), '--child-case',
        json.dumps(case(mode=mode, history_count=19, repeats=1))], text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert any(phase['phase'] == 'synthetic_history_seed' for phase in result['phases'])
    assert result['selected_engine'] == 'vader'


@pytest.mark.skipif(not (config.MODEL_DIR / 'model_quantized.onnx').exists(), reason='pinned model not installed')
def test_runtime_fallback_is_not_mislabeled_as_lightweight_missing_model():
    process = subprocess.run([sys.executable, str(PATH), '--child-case',
        json.dumps(case(engine='runtime-failure', mode='pipeline'))], text=True, capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result['selected_engine'] == 'vader' and result['fallback_exercised']
    assert result['runtime_options'] is not None  # model really loaded before controlled prediction failure


def test_timeout_kills_only_owned_children_and_removes_synthetic_temp_tree(monkeypatch):
    roots, children = [], []
    class Child:
        pid = 123456
        returncode = None
        def __init__(self, command, **kwargs):
            root = Path(kwargs['env']['TMPDIR']); roots.append(root)
            data = root / 'synthetic-child'; data.mkdir()
            (data / 'synthetic.db').write_bytes(b'synthetic only')
            children.append(self)
        def poll(self): return self.returncode
        def kill(self): self.returncode = -9
        def wait(self): return self.returncode
    monkeypatch.setattr(benchmark.subprocess, 'Popen', Child)
    times = iter([0, 2])
    monkeypatch.setattr(benchmark.time, 'monotonic', lambda: next(times))
    with pytest.raises(TimeoutError): benchmark.run_children([case()], 1, 1536)
    assert children[0].returncode == -9 and not roots[0].exists()


def test_linux_current_rss_uses_resident_pages_not_virtual_size(monkeypatch):
    monkeypatch.setattr(benchmark.sys, 'platform', 'linux')
    monkeypatch.setattr(benchmark.Path, 'read_text', lambda *args, **kwargs: '999999 2 1')
    monkeypatch.setattr(benchmark.os, 'sysconf', lambda _: 4096)
    assert benchmark.rss_bytes() == 8192


@pytest.mark.parametrize('own_process', [False, True])
def test_empty_linux_statm_is_never_a_fabricated_zero_rss(monkeypatch, own_process):
    import errno
    monkeypatch.setattr(benchmark.sys, 'platform', 'linux')
    monkeypatch.setattr(benchmark.Path, 'read_text', lambda *args, **kwargs: '')
    with pytest.raises(OSError) as error:
        benchmark.rss_bytes() if own_process else benchmark.rss_bytes(123456)
    assert error.value.errno == (errno.EIO if own_process else errno.ESRCH)


def test_child_exit_statm_race_allows_a_later_valid_sample(monkeypatch):
    import errno
    import time
    class Child:
        pid = 123456
        returncode = None
        reads = 0
        def __init__(self, command, **kwargs):
            kwargs['stdout'].write(json.dumps({'cold_ready_monotonic_ns': time.monotonic_ns()}))
            kwargs['stdout'].flush()
        def poll(self):
            self.reads += 1
            if self.reads >= 7: self.returncode = 0
            return self.returncode
        def kill(self): self.returncode = -9
        def wait(self): return self.returncode
    monkeypatch.setattr(benchmark.subprocess, 'Popen', Child)
    values = iter([FileNotFoundError(errno.ENOENT, 'process exiting'), 500])
    def sample(_):
        value = next(values)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(benchmark, 'rss_bytes', sample)
    monkeypatch.setattr(benchmark.time, 'sleep', lambda _: None)
    result, peak = benchmark.run_children([case()], 5, 1536)
    assert len(result) == 1 and peak == 500
