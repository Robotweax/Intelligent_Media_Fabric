from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from .contracts import (
    ContractError,
    load_json,
    validate_baselines,
    validate_result,
    validate_scenario,
    validate_toolchain,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _StreamDigest:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._bytes = 0

    def drain(self, stream: BinaryIO) -> None:
        try:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                self._digest.update(chunk)
                self._bytes += len(chunk)
        finally:
            stream.close()

    def result(self) -> dict[str, Any]:
        return {"bytes": self._bytes, "sha256": self._digest.hexdigest()}


def _command_digest(command: list[str]) -> str:
    encoded = json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _sanitized_environment(additional: dict[str, str]) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "SYSTEMROOT", "WINDIR")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment.update(additional)
    return environment


def _git_provenance(root: Path) -> tuple[str, str]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if revision.returncode != 0:
        return "unavailable", "unavailable"

    state = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    tree_state = "unavailable" if state.returncode else ("dirty" if state.stdout else "clean")
    return revision.stdout.strip(), tree_state


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()


def _empty_stream_digest() -> dict[str, Any]:
    return {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}


def _run_case(case: dict[str, Any], repetition: int, root: Path) -> dict[str, Any]:
    command = case["command"]
    started_at = _utc_now()
    started_ns = time.monotonic_ns()
    timed_out = False
    exit_code: int | None = None
    error: str | None = None
    stdout_result = _empty_stream_digest()
    stderr_result = _empty_stream_digest()

    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=_sanitized_environment(case.get("environment", {})),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_digest = _StreamDigest()
        stderr_digest = _StreamDigest()
        stdout_thread = threading.Thread(target=stdout_digest.drain, args=(process.stdout,), daemon=True)
        stderr_thread = threading.Thread(target=stderr_digest.drain, args=(process.stderr,), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        try:
            exit_code = process.wait(timeout=case["timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out = True
            error = "timeout"
            _terminate(process)
            exit_code = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        stdout_result = stdout_digest.result()
        stderr_result = stderr_digest.result()
    except FileNotFoundError:
        error = "executable-not-found"
    except (OSError, subprocess.SubprocessError) as exc:
        error = f"execution-error:{type(exc).__name__}"

    elapsed_ms = round((time.monotonic_ns() - started_ns) / 1_000_000, 3)
    passed = not timed_out and error is None and exit_code == case["expected_exit_code"]
    return {
        "case_id": case["case_id"],
        "repetition": repetition,
        "status": "passed" if passed else "failed",
        "command_sha256": _command_digest(command),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "elapsed_ms": elapsed_ms,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "error": error,
        "stdout": stdout_result,
        "stderr": stderr_result,
    }


def run_scenario(scenario_path: Path, output_path: Path, root: Path) -> dict[str, Any]:
    scenario_path = scenario_path.resolve()
    output_path = output_path.resolve()
    root = root.resolve()
    if scenario_path == output_path:
        raise ContractError("output path must differ from the scenario path")

    scenario = load_json(scenario_path)
    validate_scenario(scenario)
    if not scenario["execution_enabled"]:
        raise ContractError("scenario execution is disabled")

    baselines_path = root / "dependency-pins/baselines.json"
    baselines = load_json(baselines_path)
    validate_baselines(baselines)
    toolchain_path = root / "dependency-pins/toolchain.json"
    toolchain = load_json(toolchain_path)
    validate_toolchain(toolchain)
    project_revision, project_tree_state = _git_provenance(root)

    started_at = _utc_now()
    case_results = []
    for repetition in range(1, scenario["repetitions"] + 1):
        for case in scenario["cases"]:
            case_results.append(_run_case(case, repetition, root))

    result = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "status": "passed" if all(case["status"] == "passed" for case in case_results) else "failed",
        "classification": scenario["classification"],
        "scenario": {
            "id": scenario["scenario_id"],
            "sha256": sha256_file(scenario_path),
            "repetitions": scenario["repetitions"],
            "gate_ids": scenario.get("gate_ids", []),
        },
        "provenance": {
            "project_revision": project_revision,
            "project_tree_state": project_tree_state,
            "baselines_sha256": sha256_file(baselines_path),
            "toolchain_sha256": sha256_file(toolchain_path),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "started_at": started_at,
        "finished_at": _utc_now(),
        "cases": case_results,
    }
    validate_result(result)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output_path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return result
