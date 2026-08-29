from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
GATE_RE = re.compile(r"^G[0-9]+(?:-[A-Z])?$")
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
SENSITIVE_ENV_RE = re.compile(
    r"(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE_KEY|API_KEY|ACCESS_KEY)(_|$)"
)
MOVING_GITHUB_REF_RE = re.compile(
    r"https://github\.com/[^\s)]+/(?:blob|tree)/(?:main|master)(?:/|\)|$)"
)
CREDENTIAL_PATTERNS = (
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"nsec1[0-9a-z]{10,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
MARKDOWN_LINK_RE = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
TEXT_SUFFIXES = {"", ".md", ".py", ".json", ".toml", ".yml", ".yaml"}
IGNORED_PARTS = {".git", "artifacts", "build", "dist", "__pycache__"}


class ContractError(ValueError):
    """A repository or evidence contract is invalid."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load JSON {path}: {exc}") from exc


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    return value


def _require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{context} must be a non-empty string")
    return value


def validate_baselines(data: Any) -> None:
    root = _require_object(data, "baselines")
    if root.get("schema_version") != 1:
        raise ContractError("baselines.schema_version must be 1")
    dependencies = root.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ContractError("baselines.dependencies must be a non-empty array")

    seen: set[str] = set()
    for index, raw_dependency in enumerate(dependencies):
        dependency = _require_object(raw_dependency, f"dependencies[{index}]")
        dependency_id = _require_string(dependency.get("id"), f"dependencies[{index}].id")
        if dependency_id in seen:
            raise ContractError(f"duplicate dependency id: {dependency_id}")
        seen.add(dependency_id)

        repository = _require_string(
            dependency.get("repository"), f"dependencies[{index}].repository"
        )
        if not repository.startswith("https://github.com/") or not repository.endswith(".git"):
            raise ContractError(f"dependency {dependency_id} must use a canonical HTTPS Git URL")

        commit = _require_string(dependency.get("commit"), f"dependencies[{index}].commit")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"dependency {dependency_id} commit must be 40 lowercase hex digits")

        for field in ("role", "integration", "evidence_class"):
            _require_string(dependency.get(field), f"dependencies[{index}].{field}")


def validate_toolchain(data: Any) -> None:
    root = _require_object(data, "toolchain")
    if root.get("schema_version") != 1:
        raise ContractError("toolchain.schema_version must be 1")
    python = _require_object(root.get("python"), "toolchain.python")
    _require_string(python.get("minimum"), "toolchain.python.minimum")
    ci = _require_object(root.get("ci"), "toolchain.ci")
    _require_string(ci.get("runner"), "toolchain.ci.runner")
    actions = ci.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ContractError("toolchain.ci.actions must be a non-empty array")
    for index, raw_action in enumerate(actions):
        action = _require_object(raw_action, f"toolchain.ci.actions[{index}]")
        repository = _require_string(
            action.get("repository"), f"toolchain.ci.actions[{index}].repository"
        )
        if not repository.startswith("https://github.com/") or not repository.endswith(".git"):
            raise ContractError(f"toolchain action {index} must use a canonical HTTPS Git URL")
        commit = _require_string(action.get("commit"), f"toolchain.ci.actions[{index}].commit")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"toolchain action {index} commit must be 40 lowercase hex digits")


def validate_scenario(data: Any) -> None:
    root = _require_object(data, "scenario")
    if root.get("schema_version") != 1:
        raise ContractError("scenario.schema_version must be 1")

    scenario_id = _require_string(root.get("scenario_id"), "scenario.scenario_id")
    if not SCENARIO_ID_RE.fullmatch(scenario_id):
        raise ContractError("scenario.scenario_id has an invalid format")

    classification = root.get("classification")
    if classification not in {"harness-only", "experiment"}:
        raise ContractError("scenario.classification must be harness-only or experiment")
    if not isinstance(root.get("execution_enabled"), bool):
        raise ContractError("scenario.execution_enabled must be a boolean")

    repetitions = root.get("repetitions")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool):
        raise ContractError("scenario.repetitions must be an integer")
    if repetitions < 1 or repetitions > 1000:
        raise ContractError("scenario.repetitions must be between 1 and 1000")

    gate_ids = root.get("gate_ids", [])
    if not isinstance(gate_ids, list) or any(
        not isinstance(gate_id, str) or not GATE_RE.fullmatch(gate_id) for gate_id in gate_ids
    ):
        raise ContractError("scenario.gate_ids contains an invalid gate identifier")
    if len(set(gate_ids)) != len(gate_ids):
        raise ContractError("scenario.gate_ids must be unique")

    cases = root.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContractError("scenario.cases must be a non-empty array")

    seen: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = _require_object(raw_case, f"cases[{index}]")
        case_id = _require_string(case.get("case_id"), f"cases[{index}].case_id")
        if not ID_RE.fullmatch(case_id):
            raise ContractError(f"cases[{index}].case_id has an invalid format")
        if case_id in seen:
            raise ContractError(f"duplicate case id: {case_id}")
        seen.add(case_id)

        command = case.get("command")
        if not isinstance(command, list) or not command:
            raise ContractError(f"cases[{index}].command must be a non-empty argument array")
        if any(not isinstance(argument, str) or not argument or "\x00" in argument for argument in command):
            raise ContractError(f"cases[{index}].command contains an invalid argument")
        if root["execution_enabled"] and any(
            argument.startswith("REPLACE_WITH_") for argument in command
        ):
            raise ContractError(f"cases[{index}].command still contains a placeholder")

        timeout = case.get("timeout_seconds")
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
            or timeout > 3600
        ):
            raise ContractError(f"cases[{index}].timeout_seconds must be in (0, 3600]")

        exit_code = case.get("expected_exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool) or not 0 <= exit_code <= 255:
            raise ContractError(f"cases[{index}].expected_exit_code must be in [0, 255]")

        environment = case.get("environment", {})
        if not isinstance(environment, dict):
            raise ContractError(f"cases[{index}].environment must be an object")
        for name, value in environment.items():
            if not isinstance(name, str) or not ENV_NAME_RE.fullmatch(name):
                raise ContractError(f"cases[{index}].environment contains an invalid name")
            if SENSITIVE_ENV_RE.search(name):
                raise ContractError(f"cases[{index}].environment may not contain secret-like names")
            if not isinstance(value, str) or "\x00" in value:
                raise ContractError(f"cases[{index}].environment.{name} must be a safe string")


def validate_result(data: Any) -> None:
    root = _require_object(data, "result")
    if root.get("schema_version") != 1:
        raise ContractError("result.schema_version must be 1")
    if root.get("status") not in {"passed", "failed"}:
        raise ContractError("result.status must be passed or failed")
    if root.get("classification") not in {"harness-only", "experiment"}:
        raise ContractError("result.classification is invalid")
    for field in ("run_id", "started_at", "finished_at"):
        _require_string(root.get(field), f"result.{field}")

    scenario = _require_object(root.get("scenario"), "result.scenario")
    _require_string(scenario.get("id"), "result.scenario.id")
    digest = _require_string(scenario.get("sha256"), "result.scenario.sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ContractError("result.scenario.sha256 is invalid")

    provenance = _require_object(root.get("provenance"), "result.provenance")
    _require_string(provenance.get("project_revision"), "result.provenance.project_revision")
    if provenance.get("project_tree_state") not in {"clean", "dirty", "unavailable"}:
        raise ContractError("result.provenance.project_tree_state is invalid")
    baseline_digest = _require_string(
        provenance.get("baselines_sha256"), "result.provenance.baselines_sha256"
    )
    if not re.fullmatch(r"[0-9a-f]{64}", baseline_digest):
        raise ContractError("result.provenance.baselines_sha256 is invalid")
    toolchain_digest = _require_string(
        provenance.get("toolchain_sha256"), "result.provenance.toolchain_sha256"
    )
    if not re.fullmatch(r"[0-9a-f]{64}", toolchain_digest):
        raise ContractError("result.provenance.toolchain_sha256 is invalid")

    cases = root.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContractError("result.cases must be a non-empty array")
    for index, raw_case in enumerate(cases):
        case = _require_object(raw_case, f"result.cases[{index}]")
        _require_string(case.get("case_id"), f"result.cases[{index}].case_id")
        if case.get("status") not in {"passed", "failed"}:
            raise ContractError(f"result.cases[{index}].status is invalid")
        if not isinstance(case.get("timed_out"), bool):
            raise ContractError(f"result.cases[{index}].timed_out must be a boolean")
        for stream_name in ("stdout", "stderr"):
            stream = _require_object(case.get(stream_name), f"result.cases[{index}].{stream_name}")
            if not isinstance(stream.get("bytes"), int) or stream["bytes"] < 0:
                raise ContractError(f"result.cases[{index}].{stream_name}.bytes is invalid")
            stream_digest = _require_string(
                stream.get("sha256"), f"result.cases[{index}].{stream_name}.sha256"
            )
            if not re.fullmatch(r"[0-9a-f]{64}", stream_digest):
                raise ContractError(f"result.cases[{index}].{stream_name}.sha256 is invalid")


def validate_fips_source_assessment(data: Any) -> None:
    root = _require_object(data, "FIPS source assessment")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS assessment schema_version must be 1")
    if root.get("evidence_type") != "fips-source-assessment":
        raise ContractError("FIPS assessment evidence_type is invalid")

    assessment_id = _require_string(root.get("assessment_id"), "assessment_id")
    if not SCENARIO_ID_RE.fullmatch(assessment_id):
        raise ContractError("assessment_id has an invalid format")
    observed_on = _require_string(root.get("observed_on"), "observed_on")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", observed_on):
        raise ContractError("observed_on must use YYYY-MM-DD")

    gate_ids = root.get("gate_ids")
    if not isinstance(gate_ids, list) or not gate_ids:
        raise ContractError("gate_ids must be a non-empty array")
    if any(not isinstance(gate_id, str) or not GATE_RE.fullmatch(gate_id) for gate_id in gate_ids):
        raise ContractError("gate_ids contains an invalid gate identifier")

    toolchain = _require_object(root.get("toolchain"), "toolchain")
    for field in ("rustc", "cargo", "host"):
        _require_string(toolchain.get(field), f"toolchain.{field}")

    candidates = root.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ContractError("candidates must contain at least two entries")
    candidate_ids: set[str] = set()
    for index, raw_candidate in enumerate(candidates):
        candidate = _require_object(raw_candidate, f"candidates[{index}]")
        candidate_id = _require_string(candidate.get("id"), f"candidates[{index}].id")
        if not ID_RE.fullmatch(candidate_id) or candidate_id in candidate_ids:
            raise ContractError(f"candidates[{index}].id is invalid or duplicated")
        candidate_ids.add(candidate_id)
        repository = _require_string(candidate.get("repository"), f"candidates[{index}].repository")
        if not repository.startswith("https://github.com/") or not repository.endswith(".git"):
            raise ContractError(f"candidate {candidate_id} must use a canonical HTTPS Git URL")
        commit = _require_string(candidate.get("commit"), f"candidates[{index}].commit")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"candidate {candidate_id} commit must be 40 lowercase hex digits")
        if candidate.get("source_tree_state") != "clean":
            raise ContractError(f"candidate {candidate_id} source_tree_state must be clean")
        for field in ("cargo_lock_sha256", "rust_toolchain_sha256"):
            digest = _require_string(candidate.get(field), f"candidates[{index}].{field}")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ContractError(f"candidate {candidate_id} {field} is invalid")

        build = _require_object(candidate.get("build"), f"candidates[{index}].build")
        if build.get("status") != "passed" or build.get("locked") is not True:
            raise ContractError(f"candidate {candidate_id} requires a passed locked build")
        artifacts = build.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ContractError(f"candidate {candidate_id} build.artifacts must be non-empty")
        for artifact_index, raw_artifact in enumerate(artifacts):
            artifact = _require_object(
                raw_artifact, f"candidates[{index}].build.artifacts[{artifact_index}]"
            )
            _require_string(artifact.get("name"), "artifact.name")
            digest = _require_string(artifact.get("sha256"), "artifact.sha256")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ContractError(f"candidate {candidate_id} artifact sha256 is invalid")
            if not isinstance(artifact.get("bytes"), int) or artifact["bytes"] <= 0:
                raise ContractError(f"candidate {candidate_id} artifact bytes is invalid")

        tests = _require_object(candidate.get("tests"), f"candidates[{index}].tests")
        attempts = tests.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ContractError(f"candidate {candidate_id} tests.attempts must be non-empty")
        if not any(isinstance(attempt, dict) and attempt.get("status") == "passed" for attempt in attempts):
            raise ContractError(f"candidate {candidate_id} requires a passing full test attempt")
        for attempt_index, raw_attempt in enumerate(attempts):
            attempt = _require_object(raw_attempt, f"candidate {candidate_id} attempt {attempt_index}")
            if attempt.get("status") not in {"passed", "failed"}:
                raise ContractError(f"candidate {candidate_id} test attempt status is invalid")
            for field in ("passed", "failed", "ignored"):
                count = attempt.get(field)
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise ContractError(f"candidate {candidate_id} test attempt {field} is invalid")

    decision = _require_object(root.get("decision"), "decision")
    primary_candidate_id = _require_string(
        decision.get("primary_candidate_id"), "decision.primary_candidate_id"
    )
    if primary_candidate_id not in candidate_ids:
        raise ContractError("decision.primary_candidate_id is not an assessed candidate")
    if decision.get("status") != "accepted":
        raise ContractError("decision.status must be accepted")

    smoke = _require_object(root.get("runtime_smoke"), "runtime_smoke")
    if smoke.get("candidate_id") != primary_candidate_id:
        raise ContractError("runtime_smoke must exercise the primary candidate")
    if smoke.get("status") != "passed":
        raise ContractError("runtime_smoke.status must be passed")
    if smoke.get("transport") != "udp-loopback":
        raise ContractError("runtime_smoke.transport must be udp-loopback")
    if smoke.get("tun_enabled") is not False:
        raise ContractError("runtime_smoke.tun_enabled must explicitly be false")
    for field in ("connected_peer_count", "connected_link_count"):
        if smoke.get(field) != 1:
            raise ContractError(f"runtime_smoke.{field} must be 1")
    if smoke.get("peers_after_disconnect") != 0:
        raise ContractError("runtime_smoke.peers_after_disconnect must be 0")

    limitations = root.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise ContractError("limitations must be a non-empty string array")


def _iter_repository_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        yield path


def _validate_markdown_links(root: Path, path: Path, text: str) -> list[str]:
    errors: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        relative_target = unquote(target.split("#", 1)[0])
        if not relative_target:
            continue
        resolved = (path.parent / relative_target).resolve()
        if not resolved.exists():
            errors.append(f"{path.relative_to(root)}: broken local link {target}")
    return errors


def validate_repository(root: Path) -> None:
    root = root.resolve()
    if not (root / "README.md").is_file():
        raise ContractError("repository root does not contain README.md")

    errors: list[str] = []
    try:
        validate_baselines(load_json(root / "dependency-pins/baselines.json"))
    except ContractError as exc:
        errors.append(str(exc))
    try:
        validate_toolchain(load_json(root / "dependency-pins/toolchain.json"))
    except ContractError as exc:
        errors.append(str(exc))

    schema_paths = sorted((root / "schema").rglob("*.json"))
    if not schema_paths:
        errors.append("repository has no JSON schemas")
    for path in schema_paths:
        try:
            schema = _require_object(load_json(path), str(path.relative_to(root)))
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                errors.append(f"{path.relative_to(root)}: unsupported or missing $schema")
            _require_string(schema.get("$id"), f"{path.relative_to(root)}.$id")
        except ContractError as exc:
            errors.append(str(exc))

    scenario_paths = sorted((root / "qualification/scenarios").glob("*.json"))
    if not scenario_paths:
        errors.append("repository has no qualification scenarios")
    for path in scenario_paths:
        try:
            validate_scenario(load_json(path))
        except ContractError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")

    retained_paths = sorted((root / "qualification/retained-results").glob("*.json"))
    for path in retained_paths:
        try:
            retained = _require_object(load_json(path), str(path.relative_to(root)))
            if retained.get("evidence_type") == "fips-source-assessment":
                validate_fips_source_assessment(retained)
            else:
                errors.append(f"{path.relative_to(root)}: unknown retained evidence_type")
        except ContractError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")

    for path in _iter_repository_files(root):
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"Makefile"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if MOVING_GITHUB_REF_RE.search(text):
            errors.append(f"{path.relative_to(root)}: moving GitHub main/master reference")
        for pattern in CREDENTIAL_PATTERNS:
            if pattern.search(text):
                errors.append(f"{path.relative_to(root)}: possible credential material")
        if path.suffix == ".md":
            errors.extend(_validate_markdown_links(root, path, text))

    if errors:
        raise ContractError("repository validation failed:\n- " + "\n- ".join(errors))
