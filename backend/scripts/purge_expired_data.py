"""Bounded account-data retention. Requires explicit DATABASE_URL; never migrates the target schema."""
import argparse
import json
import os
import re
import signal
import sys
from pathlib import Path


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid arguments")


def main(argv=None):
    engine = None
    signals = {}
    interrupted_signal = signal.SIGINT
    def interrupt(number, frame):
        nonlocal interrupted_signal
        interrupted_signal = number
        raise KeyboardInterrupt
    report = {"status": "configuration_error", "error": "invalid_configuration", "deleted": {
        "products": 0, "reviews": 0, "analyses": 0, "ai_summaries": 0, "jobs": 0}}
    code = 2
    try:
        parser = Arguments(description=__doc__)
        parser.add_argument('--dry-run', action='store_true', help='Read-only, bounded eligibility estimate')
        parser.add_argument('--batch-size', type=int, default=100, help='Products per transaction: 1..1000')
        parser.add_argument('--max-batches', type=int, default=10, help='Transactions per invocation: 1..1000')
        parser.add_argument('--owner-id', help='Optional verified owner hash, 64 lowercase hexadecimal characters')
        args = parser.parse_args(argv)
        if (not 1 <= args.batch_size <= 1000 or not 1 <= args.max_batches <= 1000
                or (args.owner_id is not None and not re.fullmatch('[0-9a-f]{64}', args.owner_id))):
            raise ValueError("Invalid arguments")
        value = os.getenv('DATABASE_URL', '')
        if not value:
            raise ValueError("An explicit target is required")
        from sqlalchemy.engine import make_url
        try:
            url = make_url(value)
        except Exception:
            raise ValueError("Invalid target") from None
        if url.drivername not in {'sqlite', 'sqlite+pysqlite', 'postgres', 'postgresql', 'postgresql+psycopg'}:
            raise ValueError("Unsupported target")
        if url.get_backend_name() == 'sqlite':
            if not url.database or url.database == ':memory:' or url.query or not Path(url.database).is_file():
                raise ValueError("An existing SQLite file is required")
        for number in (signal.SIGINT, signal.SIGTERM):
            signals[number] = signal.signal(number, interrupt)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.database import make_engine
        from app.services.retention import run_cleanup, RetentionFailure
        engine = make_engine(value)
        try:
            report = run_cleanup(engine, batch_size=args.batch_size, max_batches=args.max_batches,
                                 dry_run=args.dry_run, owner_id=args.owner_id)
            code = 3 if report['remaining'] else 0
        except RetentionFailure as error:
            report = error.report
            code = (128 + interrupted_signal) if error.interrupted else (2 if report['status'] == 'configuration_error' else 4)
    except (ValueError, ImportError):
        pass  # never print credentials, invalid argument values or driver/configuration internals
    except KeyboardInterrupt:
        report.update(status='interrupted', error='interrupted')
        code = 128 + interrupted_signal
    except Exception:
        report.update(status='failed', error='database_or_transaction_failure')
        code = 4
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except KeyboardInterrupt:
                report.update(status='interrupted', error='interrupted')
                code = 128 + interrupted_signal
            except Exception:
                report.update(status='failed', error='resource_cleanup_failure')
                code = 4
        for number, previous in signals.items():
            signal.signal(number, previous)
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
