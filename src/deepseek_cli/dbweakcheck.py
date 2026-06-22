from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterable, Sequence


DEFAULT_PORTS = {
    "mysql": 3306,
    "mssql": 1433,
    "oracle": 1521,
    "postgresql": 5432,
    "redis": 6379,
}

DRIVER_HINTS = {
    "mysql": "Install optional dependency: python -m pip install pymysql",
    "mssql": "Install optional dependency: python -m pip install pymssql",
    "oracle": "Install optional dependency: python -m pip install oracledb",
    "postgresql": "Install optional dependency: python -m pip install psycopg[binary]",
    "redis": "Install optional dependency: python -m pip install redis",
}


class MissingDriverError(RuntimeError):
    def __init__(self, db_type: str) -> None:
        super().__init__(DRIVER_HINTS[db_type])
        self.db_type = db_type


@dataclass(frozen=True)
class TargetConfig:
    db_type: str
    host: str
    port: int
    database: str | None
    service_name: str | None
    sid: str | None
    timeout: float


@dataclass(frozen=True)
class CredentialAttempt:
    username: str
    password: str


@dataclass
class CheckResult:
    db_type: str
    host: str
    port: int
    username: str
    password: str
    found: bool
    status: str
    message: str
    elapsed_ms: int

    def public_dict(self, *, reveal_password: bool) -> dict[str, object]:
        data = asdict(self)
        if not reveal_password:
            data["password"] = mask_secret(self.password)
        return data


Checker = Callable[[TargetConfig, str, str], tuple[bool, str]]


def mask_secret(value: str) -> str:
    if value == "":
        return "<empty>"
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def read_word_file(path: Path) -> list[str]:
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        values.append(line)
    return values


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def collect_values(direct: Sequence[str], file_path: str | None, *, label: str) -> list[str]:
    values = list(direct)
    if file_path:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise ValueError(f"{label} file does not exist: {path}")
        values.extend(read_word_file(path))
    return unique_preserve_order(values)


def collect_attempts(args: argparse.Namespace) -> list[CredentialAttempt]:
    users = collect_values(args.user or [], args.user_file, label="User")
    passwords = collect_values(args.password or [], args.password_file, label="Password")
    if args.empty_password:
        passwords.insert(0, "")
        passwords = unique_preserve_order(passwords)
    if not users:
        raise ValueError("At least one --user or --user-file value is required.")
    if not passwords:
        raise ValueError("At least one --password, --password-file, or --empty-password value is required.")
    return [CredentialAttempt(username=user, password=password) for user in users for password in passwords]


def build_target(args: argparse.Namespace) -> TargetConfig:
    port = args.port or DEFAULT_PORTS[args.db]
    return TargetConfig(
        db_type=args.db,
        host=args.host,
        port=port,
        database=args.database,
        service_name=args.service_name,
        sid=args.sid,
        timeout=args.timeout,
    )


def check_mysql(target: TargetConfig, username: str, password: str) -> tuple[bool, str]:
    try:
        import pymysql
    except ImportError as exc:
        raise MissingDriverError("mysql") from exc
    try:
        conn = pymysql.connect(
            host=target.host,
            port=target.port,
            user=username,
            password=password,
            database=target.database,
            connect_timeout=target.timeout,
            read_timeout=target.timeout,
            write_timeout=target.timeout,
            charset="utf8mb4",
        )
        conn.close()
        return True, "login accepted"
    except pymysql.err.OperationalError as exc:
        return False, str(exc)


def check_mssql(target: TargetConfig, username: str, password: str) -> tuple[bool, str]:
    try:
        import pymssql
    except ImportError as exc:
        raise MissingDriverError("mssql") from exc
    try:
        timeout = max(1, int(target.timeout))
        conn = pymssql.connect(
            server=target.host,
            port=target.port,
            user=username,
            password=password,
            database=target.database,
            login_timeout=timeout,
            timeout=timeout,
        )
        conn.close()
        return True, "login accepted"
    except pymssql.Error as exc:
        return False, str(exc)


def check_oracle(target: TargetConfig, username: str, password: str) -> tuple[bool, str]:
    try:
        import oracledb
    except ImportError as exc:
        raise MissingDriverError("oracle") from exc
    try:
        if target.sid:
            dsn = oracledb.makedsn(target.host, target.port, sid=target.sid)
        else:
            service_name = target.service_name or target.database
            dsn = oracledb.makedsn(target.host, target.port, service_name=service_name)
        conn = oracledb.connect(user=username, password=password, dsn=dsn)
        conn.close()
        return True, "login accepted"
    except oracledb.Error as exc:
        return False, str(exc)


def check_postgresql(target: TargetConfig, username: str, password: str) -> tuple[bool, str]:
    try:
        import psycopg
    except ImportError as exc:
        raise MissingDriverError("postgresql") from exc
    try:
        conn = psycopg.connect(
            host=target.host,
            port=target.port,
            dbname=target.database or "postgres",
            user=username,
            password=password,
            connect_timeout=target.timeout,
        )
        conn.close()
        return True, "login accepted"
    except psycopg.Error as exc:
        return False, str(exc)


def check_redis(target: TargetConfig, username: str, password: str) -> tuple[bool, str]:
    try:
        import redis
    except ImportError as exc:
        raise MissingDriverError("redis") from exc
    try:
        client = redis.Redis(
            host=target.host,
            port=target.port,
            username=username or None,
            password=password or None,
            socket_connect_timeout=target.timeout,
            socket_timeout=target.timeout,
            decode_responses=True,
        )
        client.ping()
        client.close()
        return True, "login accepted"
    except redis.RedisError as exc:
        return False, str(exc)


DEFAULT_CHECKERS: dict[str, Checker] = {
    "mysql": check_mysql,
    "mssql": check_mssql,
    "oracle": check_oracle,
    "postgresql": check_postgresql,
    "redis": check_redis,
}


def run_one(
    target: TargetConfig,
    attempt: CredentialAttempt,
    checker: Checker,
    *,
    delay: float,
    stop_event: Event,
) -> CheckResult:
    if stop_event.is_set():
        return result_from_attempt(target, attempt, False, "skipped", "stopped after a previous success", 0)
    if delay > 0:
        time.sleep(delay)
    start = time.monotonic()
    try:
        found, message = checker(target, attempt.username, attempt.password)
        status = "found" if found else "failed"
    except MissingDriverError as exc:
        found = False
        status = "missing-driver"
        message = str(exc)
    except TimeoutError as exc:
        found = False
        status = "timeout"
        message = str(exc)
    except OSError as exc:
        found = False
        status = "network-error"
        message = str(exc)
    except Exception as exc:  # pragma: no cover - defensive boundary for optional drivers.
        found = False
        status = "error"
        message = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return result_from_attempt(target, attempt, found, status, message, elapsed_ms)


def result_from_attempt(
    target: TargetConfig,
    attempt: CredentialAttempt,
    found: bool,
    status: str,
    message: str,
    elapsed_ms: int,
) -> CheckResult:
    return CheckResult(
        db_type=target.db_type,
        host=target.host,
        port=target.port,
        username=attempt.username,
        password=attempt.password,
        found=found,
        status=status,
        message=message,
        elapsed_ms=elapsed_ms,
    )


def run_checks(
    target: TargetConfig,
    attempts: Sequence[CredentialAttempt],
    checker: Checker,
    *,
    max_workers: int,
    delay: float,
    stop_on_success: bool,
) -> list[CheckResult]:
    stop_event = Event()
    pending = iter(attempts)
    futures: dict[Future[CheckResult], CredentialAttempt] = {}
    results: list[CheckResult] = []

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        if stop_on_success and stop_event.is_set():
            return False
        try:
            attempt = next(pending)
        except StopIteration:
            return False
        future = executor.submit(run_one, target, attempt, checker, delay=delay, stop_event=stop_event)
        futures[future] = attempt
        return True

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for _ in range(max_workers):
            if not submit_next(executor):
                break
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                futures.pop(future, None)
                result = future.result()
                results.append(result)
                if result.found and stop_on_success:
                    stop_event.set()
            while len(futures) < max_workers:
                if not submit_next(executor):
                    break
    return results


def render_result(result: CheckResult, *, reveal_password: bool) -> str:
    password = result.password if reveal_password else mask_secret(result.password)
    return (
        f"[{result.status}] {result.db_type}://{result.host}:{result.port} "
        f"user={result.username!r} password={password!r} "
        f"elapsed={result.elapsed_ms}ms message={result.message}"
    )


def write_json(path: str, results: Sequence[CheckResult], *, reveal_password: bool) -> None:
    payload = [result.public_dict(reveal_password=reveal_password) for result in results]
    Path(path).expanduser().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: str, results: Sequence[CheckResult], *, reveal_password: bool) -> None:
    fields = ["db_type", "host", "port", "username", "password", "found", "status", "message", "elapsed_ms"]
    with Path(path).expanduser().open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(result.public_dict(reveal_password=reveal_password))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbweakcheck",
        description="Authorized database weak-password checker for common database services.",
    )
    parser.add_argument("--authorize", action="store_true", help="Confirm you are testing assets you own or are authorized to assess.")
    parser.add_argument("--db", required=True, choices=sorted(DEFAULT_PORTS), help="Database type to test.")
    parser.add_argument("--host", required=True, help="Target host or IP address.")
    parser.add_argument("--port", type=int, default=None, help="Target port. Defaults to the selected database port.")
    parser.add_argument("--database", default=None, help="Database name, PostgreSQL dbname, or Oracle service fallback.")
    parser.add_argument("--service-name", default=None, help="Oracle service name.")
    parser.add_argument("--sid", default=None, help="Oracle SID. Takes precedence over --service-name.")
    parser.add_argument("--user", action="append", default=[], help="Username to test. Repeatable.")
    parser.add_argument("--user-file", default=None, help="UTF-8 file with one username per line.")
    parser.add_argument("--password", action="append", default=[], help="Password to test. Repeatable.")
    parser.add_argument("--password-file", default=None, help="UTF-8 dictionary file with one password per line.")
    parser.add_argument("--empty-password", action="store_true", help="Also test an empty password.")
    parser.add_argument("--timeout", type=float, default=3.0, help="Connection timeout in seconds.")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay before each attempt in seconds.")
    parser.add_argument("--max-workers", type=int, default=4, help="Maximum concurrent login attempts.")
    parser.add_argument("--continue-after-success", action="store_true", help="Keep testing after a valid credential is found.")
    parser.add_argument("--verbose", action="store_true", help="Print failed attempts as well as findings and errors.")
    parser.add_argument("--reveal-password", action="store_true", help="Show raw passwords in console and output files.")
    parser.add_argument("--json-output", default=None, help="Write results to a JSON file.")
    parser.add_argument("--csv-output", default=None, help="Write results to a CSV file.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned attempt count without connecting.")
    parser.add_argument("--fail-on-found", action="store_true", help="Exit with code 3 if a valid credential is found.")
    return parser


def main(argv: list[str] | None = None, *, checkers: dict[str, Checker] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.authorize:
        print("Error: --authorize is required for explicit, authorized security testing.", file=sys.stderr)
        return 2
    if args.max_workers < 1:
        print("Error: --max-workers must be at least 1.", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("Error: --timeout must be greater than 0.", file=sys.stderr)
        return 2
    if args.delay < 0:
        print("Error: --delay cannot be negative.", file=sys.stderr)
        return 2

    try:
        target = build_target(args)
        attempts = collect_attempts(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Planned {len(attempts)} attempt(s) against {target.db_type}://{target.host}:{target.port}.")
        return 0

    checker_map = checkers or DEFAULT_CHECKERS
    checker = checker_map[target.db_type]
    results = run_checks(
        target,
        attempts,
        checker,
        max_workers=args.max_workers,
        delay=args.delay,
        stop_on_success=not args.continue_after_success,
    )

    for result in results:
        if result.found or result.status not in {"failed", "skipped"} or args.verbose:
            print(render_result(result, reveal_password=args.reveal_password))

    found_count = sum(1 for result in results if result.found)
    print(f"Checked {len(results)} attempt(s); found {found_count} valid credential(s).")

    if args.json_output:
        write_json(args.json_output, results, reveal_password=args.reveal_password)
    if args.csv_output:
        write_csv(args.csv_output, results, reveal_password=args.reveal_password)
    if found_count and args.fail_on_found:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
