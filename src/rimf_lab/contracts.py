from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
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
SRT_TELEMETRY_SCHEMA_ID = (
    "https://robotweax.com/schemas/srt-telemetry/telemetry-jsonl-line-v1alpha1.json"
)
SRT_TELEMETRY_SCHEMA_SHA256 = (
    "ec235ac4fcc4e1ffc0a3881dcb2fe7a206c80013de5f1b6e2a23a7de42ffcd8e"
)
SRT_TELEMETRY_VERSION = "0.1.0-alpha.0"
SRT_ADAPTER_CONTRACT = "rimf-srt-telemetry-adapter-v1"
RFC3339_NANO_RE = re.compile(
    r"^(?P<base>[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]{1,9}))?(?P<zone>[Zz]|[+-][0-9]{2}:[0-9]{2})$"
)


class ContractError(ValueError):
    """A repository or evidence contract is invalid."""


def rfc3339_to_unix_nano(value: str, field: str = "timestamp") -> int:
    match = RFC3339_NANO_RE.fullmatch(value)
    if match is None:
        raise ContractError(
            f"{field} must be an RFC 3339 timestamp with at most 9 fractional digits"
        )
    zone = match.group("zone")
    if zone.lower() == "z":
        zone = "+00:00"
    try:
        parsed = datetime.fromisoformat(
            f"{match.group('base').replace('t', 'T')}{zone}"
        ).astimezone(timezone.utc)
    except ValueError as exc:
        raise ContractError(f"{field} must be an RFC 3339 timestamp") from exc
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = parsed - epoch
    fractional_nano = int((match.group("fraction") or "0").ljust(9, "0"))
    return (
        delta.days * 86_400 * 1_000_000_000
        + delta.seconds * 1_000_000_000
        + fractional_nano
    )


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


def _require_nonnegative_integer(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"{context} must be a non-negative integer")
    return value


def _require_exact_fields(value: dict[str, Any], fields: set[str], context: str) -> None:
    missing = fields - set(value)
    unexpected = set(value) - fields
    if missing:
        raise ContractError(f"{context} is missing fields: {', '.join(sorted(missing))}")
    if unexpected:
        raise ContractError(f"{context} has unexpected fields: {', '.join(sorted(unexpected))}")


def _require_finite_json_numbers(value: Any, context: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError(f"{context} contains a non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            _require_finite_json_numbers(child, f"{context}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _require_finite_json_numbers(child, f"{context}[{index}]")


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


def _validate_observation_clock(value: Any) -> dict[str, Any]:
    clock = _require_object(value, "clock")
    _require_exact_fields(
        clock,
        {"domain_id", "synchronization", "max_error_ns", "cross_host_ordering_allowed"},
        "clock",
    )
    _require_string(clock.get("domain_id"), "clock.domain_id")
    synchronization = clock.get("synchronization")
    if synchronization not in {"local-only", "unknown", "ntp", "ptp", "gps"}:
        raise ContractError("clock.synchronization is invalid")
    cross_host_ordering = clock.get("cross_host_ordering_allowed")
    if not isinstance(cross_host_ordering, bool):
        raise ContractError("clock.cross_host_ordering_allowed must be a boolean")
    max_error_ns = clock.get("max_error_ns")
    if synchronization in {"local-only", "unknown"}:
        if max_error_ns is not None or cross_host_ordering:
            raise ContractError(
                "local-only or unknown clocks cannot authorize cross-host ordering"
            )
    else:
        _require_nonnegative_integer(max_error_ns, "clock.max_error_ns")
    return clock


def _validate_fabric_identity(value: Any) -> dict[str, Any]:
    fabric_identity = _require_object(value, "fabric_identity")
    _require_exact_fields(
        fabric_identity,
        {"tenant_id", "device_id", "stream_id", "mapping"},
        "fabric_identity",
    )
    mapping = _require_object(fabric_identity.get("mapping"), "fabric_identity.mapping")
    identity_fields = {"tenant_id", "device_id", "stream_id"}
    _require_exact_fields(mapping, identity_fields, "fabric_identity.mapping")
    for field in sorted(identity_fields):
        identity = fabric_identity.get(field)
        authority = mapping.get(field)
        if authority not in {"explicit-policy", "unavailable"}:
            raise ContractError(f"fabric_identity.mapping.{field} is invalid")
        if authority == "unavailable" and identity is not None:
            raise ContractError(f"fabric_identity.{field} must be null when mapping is unavailable")
        if authority == "explicit-policy":
            _require_string(identity, f"fabric_identity.{field}")
    return fabric_identity


def validate_srt_adapter_context(data: Any) -> None:
    root = _require_object(data, "SRT adapter context")
    _require_exact_fields(
        root,
        {
            "schema_version",
            "event_namespace",
            "route_epoch",
            "clock",
            "fabric_identity",
            "source_identifiers_pseudonymous",
            "telemetry_revision",
        },
        "SRT adapter context",
    )
    if root.get("schema_version") != 1:
        raise ContractError("SRT adapter context schema_version must be 1")
    event_namespace = _require_string(root.get("event_namespace"), "event_namespace")
    if not UUID_RE.fullmatch(event_namespace):
        raise ContractError("event_namespace must be a canonical lowercase UUID")
    _require_nonnegative_integer(root.get("route_epoch"), "route_epoch")
    _validate_observation_clock(root.get("clock"))
    _validate_fabric_identity(root.get("fabric_identity"))
    if root.get("source_identifiers_pseudonymous") is not True:
        raise ContractError("source_identifiers_pseudonymous must be true")
    telemetry_revision = _require_string(root.get("telemetry_revision"), "telemetry_revision")
    if not COMMIT_RE.fullmatch(telemetry_revision):
        raise ContractError("telemetry_revision must be a full lowercase Git commit")


def validate_correlation_envelope(data: Any) -> None:
    root = _require_object(data, "correlation envelope")
    required = {
        "schema_version",
        "event_id",
        "source",
        "observed_at",
        "monotonic_ns",
        "route_epoch",
        "clock",
        "quality",
        "payload",
    }
    allowed = required | {"tenant_id", "device_id", "stream_id"}
    missing = required - set(root)
    unexpected = set(root) - allowed
    if missing:
        raise ContractError(f"correlation envelope is missing fields: {', '.join(sorted(missing))}")
    if unexpected:
        raise ContractError(
            f"correlation envelope has unexpected fields: {', '.join(sorted(unexpected))}"
        )
    if _require_nonnegative_integer(root.get("schema_version"), "schema_version") != 1:
        raise ContractError("correlation envelope schema_version must be 1")
    event_id = _require_string(root.get("event_id"), "event_id")
    if not UUID_RE.fullmatch(event_id):
        raise ContractError("event_id must be a canonical lowercase UUID")
    if root.get("source") not in {"fips", "os", "media-validator", "fabric"}:
        raise ContractError("correlation envelope source is invalid")
    observed_at = _require_string(root.get("observed_at"), "observed_at")
    rfc3339_to_unix_nano(observed_at, "observed_at")
    _require_nonnegative_integer(root.get("monotonic_ns"), "monotonic_ns")
    _require_nonnegative_integer(root.get("route_epoch"), "route_epoch")
    _validate_observation_clock(root.get("clock"))
    for field in ("tenant_id", "device_id", "stream_id"):
        identity = root.get(field)
        if identity is not None:
            _require_string(identity, field)

    quality = _require_object(root.get("quality"), "quality")
    _require_exact_fields(quality, {"availability", "confidence", "reason"}, "quality")
    availability = quality.get("availability")
    if availability not in {"available", "partial", "unavailable"}:
        raise ContractError("quality.availability is invalid")
    confidence = quality.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise ContractError("quality.confidence must be a finite number in [0, 1]")
    reason = quality.get("reason")
    if availability == "available" and reason is not None:
        raise ContractError("available quality requires a null reason")
    if availability != "available":
        _require_string(reason, "quality.reason")
    payload = _require_object(root.get("payload"), "payload")
    _require_finite_json_numbers(payload, "payload")
    metric_namespace = _require_string(payload.get("metric_namespace"), "payload.metric_namespace")
    _require_string(payload.get("metric_semantics"), "payload.metric_semantics")
    namespace_prefix = {
        "fips": "fips.",
        "os": "os.",
        "media-validator": "media.",
        "fabric": "fabric.",
    }[root["source"]]
    if not metric_namespace.startswith(namespace_prefix):
        raise ContractError(
            f"payload.metric_namespace must begin with {namespace_prefix!r} for source {root['source']}"
        )


def validate_srt_telemetry_observation(data: Any) -> None:
    root = _require_object(data, "SRT telemetry observation")
    _require_exact_fields(
        root,
        {
            "schema_version",
            "event_id",
            "source",
            "observed_at_unix_nano",
            "monotonic_ns",
            "route_epoch",
            "clock",
            "fabric_identity",
            "source_identity",
            "provenance",
            "quality",
            "payload",
        },
        "SRT telemetry observation",
    )
    if root.get("schema_version") != 1 or root.get("source") != "srt":
        raise ContractError("SRT telemetry observation schema_version/source is invalid")
    event_id = _require_string(root.get("event_id"), "event_id")
    if not UUID_RE.fullmatch(event_id):
        raise ContractError("event_id must be a canonical lowercase UUID")
    observed_at = _require_nonnegative_integer(
        root.get("observed_at_unix_nano"), "observed_at_unix_nano"
    )
    monotonic_ns = _require_nonnegative_integer(root.get("monotonic_ns"), "monotonic_ns")
    _require_nonnegative_integer(root.get("route_epoch"), "route_epoch")

    _validate_observation_clock(root.get("clock"))
    _validate_fabric_identity(root.get("fabric_identity"))

    source_identity = _require_object(root.get("source_identity"), "source_identity")
    _require_exact_fields(
        source_identity,
        {"stream_id", "flow_id", "role", "sample_index", "identifiers_pseudonymous"},
        "source_identity",
    )
    source_stream_id = _require_string(source_identity.get("stream_id"), "source_identity.stream_id")
    source_flow_id = _require_string(source_identity.get("flow_id"), "source_identity.flow_id")
    if source_identity.get("role") not in {"sender", "receiver"}:
        raise ContractError("source_identity.role is invalid")
    sample_index = _require_nonnegative_integer(
        source_identity.get("sample_index"), "source_identity.sample_index"
    )
    if source_identity.get("identifiers_pseudonymous") is not True:
        raise ContractError("source_identity.identifiers_pseudonymous must be true")

    provenance = _require_object(root.get("provenance"), "provenance")
    _require_exact_fields(
        provenance,
        {
            "provider",
            "provider_version",
            "provider_revision",
            "build_profile",
            "telemetry_version",
            "telemetry_revision",
            "source_schema_id",
            "source_schema_sha256",
            "adapter_contract",
        },
        "provenance",
    )
    if provenance.get("provider") not in {"robotweax-srt", "haivision-srt"}:
        raise ContractError("provenance.provider is invalid")
    for field in ("provider_version", "build_profile"):
        _require_string(provenance.get(field), f"provenance.{field}")
    for field in ("provider_revision", "telemetry_revision"):
        commit = _require_string(provenance.get(field), f"provenance.{field}")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"provenance.{field} must be a full lowercase Git commit")
    if provenance.get("telemetry_version") != SRT_TELEMETRY_VERSION:
        raise ContractError("provenance.telemetry_version is not the pinned contract version")
    if provenance.get("source_schema_id") != SRT_TELEMETRY_SCHEMA_ID:
        raise ContractError("provenance.source_schema_id is invalid")
    if provenance.get("source_schema_sha256") != SRT_TELEMETRY_SCHEMA_SHA256:
        raise ContractError("provenance.source_schema_sha256 is invalid")
    if provenance.get("adapter_contract") != SRT_ADAPTER_CONTRACT:
        raise ContractError("provenance.adapter_contract is invalid")

    quality = _require_object(root.get("quality"), "quality")
    _require_exact_fields(
        quality,
        {
            "availability",
            "reason",
            "source_available_fields",
            "source_quality_flags",
            "source_available_delta_fields",
            "source_counter_reset_fields",
            "source_available_rates",
        },
        "quality",
    )
    availability = quality.get("availability")
    if availability not in {"available", "partial", "unavailable"}:
        raise ContractError("quality.availability is invalid")
    available_fields = _require_nonnegative_integer(
        quality.get("source_available_fields"), "quality.source_available_fields"
    )
    for field in (
        "source_quality_flags",
        "source_available_delta_fields",
        "source_counter_reset_fields",
        "source_available_rates",
    ):
        _require_nonnegative_integer(quality.get(field), f"quality.{field}")
    reason = quality.get("reason")
    if availability == "available":
        if available_fields == 0 or reason is not None:
            raise ContractError("available quality requires fields and a null reason")
    elif availability == "partial":
        if available_fields == 0:
            raise ContractError("partial quality requires at least one available source field")
        _require_string(reason, "quality.reason")
    else:
        if available_fields != 0:
            raise ContractError("unavailable quality requires a zero source field mask")
        _require_string(reason, "quality.reason")

    payload = _require_object(root.get("payload"), "payload")
    _require_exact_fields(payload, {"recording", "sample"}, "payload")
    recording = _require_object(payload.get("recording"), "payload.recording")
    recording_fields = {
        "schemaVersion",
        "kind",
        "streamId",
        "flowId",
        "role",
        "configuredProvider",
        "providerVersion",
        "providerRevision",
        "buildProfile",
        "telemetryVersion",
        "recordCount",
        "capacity",
        "overwrittenCount",
    }
    _require_exact_fields(recording, recording_fields, "payload.recording")
    if (
        recording.get("schemaVersion") != "1alpha1"
        or recording.get("kind") != "robotweax-srt-telemetry-recording"
    ):
        raise ContractError("payload.recording is not an SRT telemetry v1alpha1 header")
    for field in ("recordCount", "capacity", "overwrittenCount"):
        _require_nonnegative_integer(recording.get(field), f"payload.recording.{field}")
    if recording["capacity"] < 1 or recording["capacity"] > 1_000_000:
        raise ContractError("payload.recording.capacity is outside the source contract")
    if recording["recordCount"] > recording["capacity"]:
        raise ContractError("payload.recording.recordCount exceeds its fixed capacity")

    sample = _require_object(payload.get("sample"), "payload.sample")
    _require_exact_fields(
        sample, {"schemaVersion", "kind", "streamId", "sampleIndex", "raw", "delta"}, "payload.sample"
    )
    if (
        sample.get("schemaVersion") != "1alpha1"
        or sample.get("kind") != "robotweax-srt-telemetry-sample"
    ):
        raise ContractError("payload.sample is not an SRT telemetry v1alpha1 sample")
    raw = _require_object(sample.get("raw"), "payload.sample.raw")
    delta = _require_object(sample.get("delta"), "payload.sample.delta")
    for field in ("provider", "available_fields", "observed_at_unix_nano", "sample_monotonic_nano"):
        if field not in raw:
            raise ContractError(f"payload.sample.raw is missing field: {field}")
    if raw.get("provider") not in {"robotweax-srt", "haivision-srt"}:
        raise ContractError("payload.sample.raw.provider is invalid")
    for field in ("available_fields", "observed_at_unix_nano", "sample_monotonic_nano"):
        _require_nonnegative_integer(raw.get(field), f"payload.sample.raw.{field}")
    for field in (
        "quality_flags",
        "available_delta_fields",
        "counter_reset_fields",
        "available_rates",
    ):
        if field not in delta:
            raise ContractError(f"payload.sample.delta is missing field: {field}")
        _require_nonnegative_integer(delta.get(field), f"payload.sample.delta.{field}")
    _require_nonnegative_integer(sample.get("sampleIndex"), "payload.sample.sampleIndex")

    expected_equalities = (
        (recording.get("streamId"), source_stream_id, "recording stream identity"),
        (recording.get("flowId"), source_flow_id, "recording flow identity"),
        (recording.get("role"), source_identity["role"], "recording role"),
        (recording.get("configuredProvider"), provenance["provider"], "configured provider"),
        (recording.get("providerVersion"), provenance["provider_version"], "provider version"),
        (recording.get("providerRevision"), provenance["provider_revision"], "provider revision"),
        (recording.get("buildProfile"), provenance["build_profile"], "build profile"),
        (recording.get("telemetryVersion"), provenance["telemetry_version"], "telemetry version"),
        (sample.get("streamId"), source_stream_id, "sample stream identity"),
        (sample.get("sampleIndex"), sample_index, "sample index"),
        (raw.get("provider"), provenance["provider"], "sample provider"),
        (raw.get("observed_at_unix_nano"), observed_at, "wall timestamp"),
        (raw.get("sample_monotonic_nano"), monotonic_ns, "monotonic timestamp"),
        (raw.get("available_fields"), available_fields, "available field mask"),
        (delta.get("quality_flags"), quality["source_quality_flags"], "quality flag mask"),
        (
            delta.get("available_delta_fields"),
            quality["source_available_delta_fields"],
            "available delta mask",
        ),
        (
            delta.get("counter_reset_fields"),
            quality["source_counter_reset_fields"],
            "counter reset mask",
        ),
        (delta.get("available_rates"), quality["source_available_rates"], "available rate mask"),
    )
    for actual, expected, label in expected_equalities:
        if actual != expected:
            raise ContractError(f"{label} must be preserved without reinterpretation")


def validate_srt_adapter_golden_case(directory: Path) -> None:
    directory = directory.resolve()
    manifest = _require_object(load_json(directory / "manifest.json"), "SRT adapter manifest")
    _require_exact_fields(
        manifest,
        {
            "schema_version",
            "case_id",
            "classification",
            "gate_ids",
            "adapter_contract",
            "source_contract",
            "files",
            "expected",
            "supported_claims",
            "non_claims",
        },
        "SRT adapter manifest",
    )
    if manifest.get("schema_version") != 1:
        raise ContractError("SRT adapter manifest schema_version must be 1")
    case_id = _require_string(manifest.get("case_id"), "SRT adapter manifest.case_id")
    if not SCENARIO_ID_RE.fullmatch(case_id):
        raise ContractError("SRT adapter manifest.case_id is invalid")
    if manifest.get("classification") != "harness-only" or manifest.get("gate_ids") != ["G4"]:
        raise ContractError("SRT adapter manifest must be harness-only G4 material")
    if manifest.get("adapter_contract") != SRT_ADAPTER_CONTRACT:
        raise ContractError("SRT adapter manifest adapter_contract is invalid")

    source_contract = _require_object(manifest.get("source_contract"), "source_contract")
    _require_exact_fields(
        source_contract,
        {"schema_id", "schema_sha256", "telemetry_revision", "provider_revision"},
        "source_contract",
    )
    if (
        source_contract.get("schema_id") != SRT_TELEMETRY_SCHEMA_ID
        or source_contract.get("schema_sha256") != SRT_TELEMETRY_SCHEMA_SHA256
    ):
        raise ContractError("SRT adapter manifest source schema pin is invalid")
    for field in ("telemetry_revision", "provider_revision"):
        revision = _require_string(source_contract.get(field), f"source_contract.{field}")
        if not COMMIT_RE.fullmatch(revision):
            raise ContractError(f"source_contract.{field} must be a full lowercase Git commit")

    files = _require_object(manifest.get("files"), "SRT adapter manifest.files")
    expected_files = {"source.jsonl", "context.json", "expected-observations.jsonl"}
    _require_exact_fields(files, expected_files, "SRT adapter manifest.files")
    for name in sorted(expected_files):
        digest = _require_string(files.get(name), f"SRT adapter manifest.files.{name}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"SRT adapter manifest.files.{name} is not a SHA-256 digest")
        path = directory / name
        try:
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ContractError(f"cannot read SRT adapter golden file {path}: {exc}") from exc
        if actual_digest != digest:
            raise ContractError(f"SRT adapter golden file hash mismatch: {name}")

    expected = _require_object(manifest.get("expected"), "SRT adapter manifest.expected")
    _require_exact_fields(
        expected,
        {
            "sample_count",
            "event_id",
            "route_epoch",
            "availability",
            "reason",
            "source_quality_flags",
        },
        "SRT adapter manifest.expected",
    )
    sample_count = _require_nonnegative_integer(expected.get("sample_count"), "expected.sample_count")
    event_id = _require_string(expected.get("event_id"), "expected.event_id")
    if not UUID_RE.fullmatch(event_id):
        raise ContractError("expected.event_id must be a canonical lowercase UUID")
    _require_nonnegative_integer(expected.get("route_epoch"), "expected.route_epoch")
    _require_nonnegative_integer(
        expected.get("source_quality_flags"), "expected.source_quality_flags"
    )
    if expected.get("availability") not in {"available", "partial", "unavailable"}:
        raise ContractError("expected.availability is invalid")
    if expected.get("reason") is not None:
        _require_string(expected.get("reason"), "expected.reason")

    observations_path = directory / "expected-observations.jsonl"
    try:
        lines = observations_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read {observations_path}: {exc}") from exc
    if len(lines) != sample_count:
        raise ContractError("SRT adapter golden observation count is invalid")
    observations: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        try:
            observation = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"SRT adapter golden observation {index} is invalid JSON") from exc
        validate_srt_telemetry_observation(observation)
        observations.append(observation)
    if sample_count:
        first = observations[0]
        if (
            first["event_id"] != expected["event_id"]
            or first["route_epoch"] != expected["route_epoch"]
            or first["quality"]["availability"] != expected["availability"]
            or first["quality"]["reason"] != expected["reason"]
            or first["quality"]["source_quality_flags"] != expected["source_quality_flags"]
        ):
            raise ContractError("SRT adapter golden first observation differs from manifest")

    for field in ("supported_claims", "non_claims"):
        claims = manifest.get(field)
        if not isinstance(claims, list) or not claims or any(
            not isinstance(claim, str) or not claim for claim in claims
        ):
            raise ContractError(f"SRT adapter manifest.{field} must be a non-empty string array")


def validate_g4_ordering_assessment(data: Any) -> None:
    root = _require_object(data, "G4 ordering assessment")
    _require_exact_fields(
        root,
        {
            "schema_version",
            "analysis_id",
            "analysis_scope",
            "inputs",
            "clock_assessment",
            "outcome",
            "ordering",
            "reason",
            "metric_semantics_separate",
            "supported_claims",
            "non_claims",
        },
        "G4 ordering assessment",
    )
    if root.get("schema_version") != 1 or root.get("analysis_scope") != "ordering-only":
        raise ContractError("G4 ordering assessment schema/scope is invalid")
    analysis_id = _require_string(root.get("analysis_id"), "analysis_id")
    if not UUID_RE.fullmatch(analysis_id):
        raise ContractError("analysis_id must be a canonical lowercase UUID")

    inputs = _require_object(root.get("inputs"), "inputs")
    _require_exact_fields(inputs, {"srt", "peer"}, "inputs")
    for name in ("srt", "peer"):
        item = _require_object(inputs.get(name), f"inputs.{name}")
        expected_fields = {"event_id", "sha256", "route_epoch", "clock_domain"}
        if name == "peer":
            expected_fields.add("source")
        _require_exact_fields(item, expected_fields, f"inputs.{name}")
        event_id = _require_string(item.get("event_id"), f"inputs.{name}.event_id")
        if not UUID_RE.fullmatch(event_id):
            raise ContractError(f"inputs.{name}.event_id is invalid")
        digest = _require_string(item.get("sha256"), f"inputs.{name}.sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"inputs.{name}.sha256 is invalid")
        _require_nonnegative_integer(item.get("route_epoch"), f"inputs.{name}.route_epoch")
        _require_string(item.get("clock_domain"), f"inputs.{name}.clock_domain")
    if inputs["peer"].get("source") not in {"fips", "os", "media-validator", "fabric"}:
        raise ContractError("inputs.peer.source is invalid")

    clock = _require_object(root.get("clock_assessment"), "clock_assessment")
    _require_exact_fields(
        clock,
        {"same_domain", "ordering_authorized", "basis", "combined_max_error_ns"},
        "clock_assessment",
    )
    for field in ("same_domain", "ordering_authorized"):
        if not isinstance(clock.get(field), bool):
            raise ContractError(f"clock_assessment.{field} must be a boolean")
    if clock.get("basis") not in {"shared-monotonic-domain", "bounded-wall-clock", "none"}:
        raise ContractError("clock_assessment.basis is invalid")
    combined_error = clock.get("combined_max_error_ns")
    if clock["basis"] == "bounded-wall-clock":
        _require_nonnegative_integer(combined_error, "clock_assessment.combined_max_error_ns")
    elif combined_error is not None:
        raise ContractError("combined_max_error_ns is only valid for bounded wall-clock ordering")

    outcome = root.get("outcome")
    ordering = root.get("ordering")
    reason = root.get("reason")
    if outcome not in {"ordered", "insufficient-evidence"}:
        raise ContractError("G4 ordering assessment outcome is invalid")
    if ordering not in {"srt-before-peer", "peer-before-srt", "unknown"}:
        raise ContractError("G4 ordering assessment ordering is invalid")
    valid_reasons = {
        "shared-monotonic-order",
        "bounded-wall-clock-order",
        "route-epoch-mismatch",
        "source-quality-unavailable",
        "clock-domains-not-comparable",
        "clock-uncertainty-overlap",
        "clock-resolution-tie",
    }
    if reason not in valid_reasons:
        raise ContractError("G4 ordering assessment reason is invalid")
    if outcome == "ordered":
        if ordering == "unknown" or not clock["ordering_authorized"]:
            raise ContractError("ordered outcome requires an authorized concrete order")
        if reason not in {"shared-monotonic-order", "bounded-wall-clock-order"}:
            raise ContractError("ordered outcome has an invalid reason")
    elif ordering != "unknown":
        raise ContractError("insufficient-evidence outcome must keep ordering unknown")
    if root.get("metric_semantics_separate") is not True:
        raise ContractError("metric_semantics_separate must be true")
    for field in ("supported_claims", "non_claims"):
        claims = root.get(field)
        if not isinstance(claims, list) or not claims or any(
            not isinstance(claim, str) or not claim for claim in claims
        ):
            raise ContractError(f"G4 ordering assessment.{field} must be a string array")


def validate_g4_clock_domain_golden_case(directory: Path) -> None:
    directory = directory.resolve()
    manifest = _require_object(load_json(directory / "manifest.json"), "G4 golden manifest")
    _require_exact_fields(
        manifest,
        {
            "schema_version",
            "case_id",
            "classification",
            "gate_ids",
            "input_origin",
            "live_capture",
            "files",
            "expected",
            "supported_claims",
            "non_claims",
        },
        "G4 golden manifest",
    )
    if manifest.get("schema_version") != 1:
        raise ContractError("G4 golden manifest schema_version must be 1")
    case_id = _require_string(manifest.get("case_id"), "G4 golden manifest.case_id")
    if not SCENARIO_ID_RE.fullmatch(case_id):
        raise ContractError("G4 golden manifest.case_id is invalid")
    if manifest.get("classification") != "harness-only" or manifest.get("gate_ids") != ["G4"]:
        raise ContractError("G4 golden manifest must be harness-only G4 material")
    if (
        manifest.get("input_origin") != "synthetic-contract-fixture"
        or manifest.get("live_capture") is not False
    ):
        raise ContractError("G4 golden manifest must explicitly declare its synthetic origin")

    files = _require_object(manifest.get("files"), "G4 golden manifest.files")
    expected_files = {"srt-observation.json", "fips-observation.json", "expected-assessment.json"}
    _require_exact_fields(files, expected_files, "G4 golden manifest.files")
    actual_digests: dict[str, str] = {}
    for name in sorted(expected_files):
        digest = _require_string(files.get(name), f"G4 golden manifest.files.{name}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"G4 golden manifest.files.{name} is not a SHA-256 digest")
        try:
            actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        except OSError as exc:
            raise ContractError(f"cannot read G4 golden file {directory / name}: {exc}") from exc
        if actual != digest:
            raise ContractError(f"G4 golden file hash mismatch: {name}")
        actual_digests[name] = actual

    srt = load_json(directory / "srt-observation.json")
    peer = load_json(directory / "fips-observation.json")
    assessment = load_json(directory / "expected-assessment.json")
    validate_srt_telemetry_observation(srt)
    validate_correlation_envelope(peer)
    validate_g4_ordering_assessment(assessment)
    if assessment["inputs"]["srt"]["sha256"] != actual_digests["srt-observation.json"]:
        raise ContractError("G4 assessment SRT digest does not match its input")
    if assessment["inputs"]["peer"]["sha256"] != actual_digests["fips-observation.json"]:
        raise ContractError("G4 assessment peer digest does not match its input")

    expected = _require_object(manifest.get("expected"), "G4 golden manifest.expected")
    _require_exact_fields(
        expected,
        {
            "outcome",
            "ordering",
            "reason",
            "same_domain",
            "ordering_authorized",
            "metric_semantics_separate",
        },
        "G4 golden manifest.expected",
    )
    actual_expected = {
        "outcome": assessment["outcome"],
        "ordering": assessment["ordering"],
        "reason": assessment["reason"],
        "same_domain": assessment["clock_assessment"]["same_domain"],
        "ordering_authorized": assessment["clock_assessment"]["ordering_authorized"],
        "metric_semantics_separate": assessment["metric_semantics_separate"],
    }
    if actual_expected != expected:
        raise ContractError("G4 golden assessment differs from manifest expectations")
    for field in ("supported_claims", "non_claims"):
        claims = manifest.get(field)
        if not isinstance(claims, list) or not claims or any(
            not isinstance(claim, str) or not claim for claim in claims
        ):
            raise ContractError(f"G4 golden manifest.{field} must be a string array")


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


def validate_fips_g2_linux_direct_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux direct result")
    schema_version = root.get("schema_version")
    if schema_version not in {1, 2}:
        raise ContractError("FIPS G2 result schema_version must be 1 or 2")
    if root.get("evidence_type") != "fips-g2-linux-direct":
        raise ContractError("FIPS G2 result evidence_type is invalid")
    if root.get("status") != "passed" or root.get("classification") != "experiment":
        raise ContractError("FIPS G2 retained result must be a passed experiment")
    if root.get("gate_ids") != ["G2"]:
        raise ContractError("FIPS G2 result gate_ids must be exactly ['G2']")
    for field in ("run_id", "started_at", "finished_at"):
        _require_string(root.get(field), f"FIPS G2 result.{field}")

    provenance = _require_object(root.get("provenance"), "FIPS G2 result.provenance")
    for field in ("project_revision", "fips_commit"):
        commit = _require_string(provenance.get(field), f"provenance.{field}")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"provenance.{field} must be a full lowercase Git commit")
    if provenance.get("fips_source_tree_state") != "clean":
        raise ContractError("provenance.fips_source_tree_state must be clean")
    for field in (
        "cargo_lock_sha256",
        "rust_toolchain_sha256",
        "fips_binary_sha256",
        "fipsctl_binary_sha256",
    ):
        digest = _require_string(provenance.get(field), f"provenance.{field}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"provenance.{field} is invalid")
    repository = _require_string(provenance.get("fips_repository"), "provenance.fips_repository")
    if repository != "https://github.com/jmcorgan/fips.git":
        raise ContractError("provenance.fips_repository is invalid")
    _require_string(provenance.get("reported_version"), "provenance.reported_version")

    platform_data = _require_object(root.get("platform"), "FIPS G2 result.platform")
    if platform_data.get("system") != "Linux":
        raise ContractError("FIPS G2 retained result must come from Linux")
    for field in ("release", "machine", "python"):
        _require_string(platform_data.get(field), f"platform.{field}")

    topology = _require_object(root.get("topology"), "FIPS G2 result.topology")
    expected_topology = {
        "node_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "direct-veth-ipv4-udp",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
    }
    if set(topology) != set(expected_topology):
        raise ContractError("FIPS G2 result.topology contains unexpected fields")
    for field, expected in expected_topology.items():
        if topology.get(field) != expected:
            raise ContractError(f"topology.{field} must be {expected!r}")

    observations = _require_object(root.get("observations"), "FIPS G2 result.observations")
    nodes = observations.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 2:
        raise ContractError("observations.nodes must contain exactly two nodes")
    if {node.get("node") for node in nodes if isinstance(node, dict)} != {"a", "b"}:
        raise ContractError("observations.nodes must identify node a and node b")
    for index, raw_node in enumerate(nodes):
        node = _require_object(raw_node, f"observations.nodes[{index}]")
        expected_node = {
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": 1203,
        }
        for field, expected in expected_node.items():
            if node.get(field) != expected:
                raise ContractError(f"observations.nodes[{index}].{field} is invalid")

    connection = _require_object(observations.get("connection"), "observations.connection")
    expected_connection = {
        "control_acknowledged": True,
        "authenticated_peers_per_node": 1,
        "links_per_node": 1,
        "estimated_mesh_size": 2,
        "transport": "udp",
    }
    for field, expected in expected_connection.items():
        if connection.get(field) != expected:
            raise ContractError(f"observations.connection.{field} is invalid")

    mmp = observations.get("mmp")
    if not isinstance(mmp, list) or len(mmp) != 2:
        raise ContractError("observations.mmp must contain exactly two nodes")
    for index, raw_mmp in enumerate(mmp):
        item = _require_object(raw_mmp, f"observations.mmp[{index}]")
        if item.get("mode") != "full" or item.get("srtt_ms_observed") is not True:
            raise ContractError(f"observations.mmp[{index}] is incomplete")
        for field in ("loss_rate", "etx"):
            value = item.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ContractError(f"observations.mmp[{index}].{field} is invalid")

    icmpv6 = _require_object(observations.get("icmpv6"), "observations.icmpv6")
    if (
        icmpv6.get("passed") is not True
        or icmpv6.get("small_payload_bytes") != 32
        or icmpv6.get("effective_mtu_boundary_payload_bytes") != 1155
        or icmpv6.get("echo_requests_per_size") != 2
    ):
        raise ContractError("observations.icmpv6 is invalid")

    above_mtu = observations.get("above_effective_mtu")
    if schema_version == 2 and above_mtu is None:
        raise ContractError("schema v2 requires observations.above_effective_mtu")
    if above_mtu is not None:
        above_mtu = _require_object(above_mtu, "observations.above_effective_mtu")
        if above_mtu != {
            "effective_ipv6_mtu": 1203,
            "boundary_icmp_payload_bytes": 1155,
            "above_boundary_icmp_payload_bytes": 1156,
            "above_boundary_ipv6_packet_bytes": 1204,
            "echo_reply_received": False,
            "icmpv6_type": 2,
            "icmpv6_code": 0,
            "reported_mtu": 1203,
            "post_ptb_boundary_probe_passed": True,
        }:
            raise ContractError("observations.above_effective_mtu is invalid")

    payload = _require_object(observations.get("payload_identity"), "observations.payload_identity")
    if payload.get("protocol") != "udp-over-ipv6-over-fips0":
        raise ContractError("observations.payload_identity.protocol is invalid")
    if payload.get("all_exact_echo") is not True:
        raise ContractError("observations.payload_identity must report exact echo")
    records = payload.get("records")
    if not isinstance(records, list) or [item.get("bytes") for item in records] != [1, 1024, 1155]:
        raise ContractError("observations.payload_identity.records has invalid sizes")
    for index, raw_record in enumerate(records):
        record = _require_object(raw_record, f"payload record {index}")
        digest = _require_string(record.get("sha256"), f"payload record {index}.sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or record.get("exact_echo") is not True:
            raise ContractError(f"payload record {index} is invalid")

    session_counts = observations.get("fsp_session_counts")
    if (
        not isinstance(session_counts, list)
        or len(session_counts) != 2
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in session_counts)
    ):
        raise ContractError("observations.fsp_session_counts is invalid")

    disconnect = _require_object(observations.get("disconnect"), "observations.disconnect")
    if disconnect != {
        "control_acknowledged": True,
        "peers_per_node_after": 0,
        "links_per_node_after": 0,
    }:
        raise ContractError("observations.disconnect is invalid")

    cleanup = _require_object(root.get("cleanup"), "FIPS G2 result.cleanup")
    for field in (
        "daemons_stopped",
        "namespaces_removed",
        "ephemeral_identity_directory_removed",
    ):
        if cleanup.get(field) is not True:
            raise ContractError(f"cleanup.{field} must be true")

    limitations = root.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise ContractError("FIPS G2 result limitations must be a non-empty string array")


def validate_fips_g2_linux_nat_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux NAT result")
    if root.get("evidence_type") != "fips-g2-linux-nat":
        raise ContractError("FIPS G2 NAT result evidence_type is invalid")

    topology = _require_object(root.get("topology"), "FIPS G2 NAT result.topology")
    expected_topology = {
        "node_count": 2,
        "namespace_count": 3,
        "isolation": "linux-network-namespaces",
        "underlay": "routed-two-segment-ipv4-udp",
        "nat": "one-sided-snat",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
    }
    if set(topology) != set(expected_topology):
        raise ContractError("FIPS G2 NAT result.topology contains unexpected fields")
    for field, expected in expected_topology.items():
        if topology.get(field) != expected:
            raise ContractError(f"topology.{field} must be {expected!r}")

    observations = _require_object(root.get("observations"), "FIPS G2 NAT result.observations")
    expected_observation_fields = {
        "directional_reachability",
        "nat",
        "nodes",
        "connection",
        "mmp",
        "icmpv6",
        "payload_identity",
        "fsp_session_counts",
        "disconnect",
    }
    if set(observations) != expected_observation_fields:
        raise ContractError("FIPS G2 NAT result.observations contains unexpected fields")
    directional = _require_object(
        observations.get("directional_reachability"),
        "observations.directional_reachability",
    )
    if directional != {
        "node_a_to_node_b_new_flow_blocked": True,
        "node_b_to_node_a_new_flow_allowed": True,
        "stateful_return_path_only": True,
    }:
        raise ContractError("observations.directional_reachability is invalid")

    nat = _require_object(observations.get("nat"), "observations.nat")
    if nat != {
        "mode": "one-sided-snat",
        "private_initiator": "node-b",
        "public_node_observed_translated_source": True,
        "private_source_address_not_retained": True,
    }:
        raise ContractError("observations.nat is invalid")

    direct_shape = dict(root)
    direct_shape["evidence_type"] = "fips-g2-linux-direct"
    direct_shape["topology"] = {
        "node_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "direct-veth-ipv4-udp",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
    }
    direct_observations = dict(observations)
    direct_observations.pop("directional_reachability", None)
    direct_observations.pop("nat", None)
    direct_shape["observations"] = direct_observations
    validate_fips_g2_linux_direct_result(direct_shape)


def validate_fips_g2_linux_managed_transit_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux managed-transit result")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 managed-transit result schema_version must be 1")
    if root.get("evidence_type") != "fips-g2-linux-managed-transit":
        raise ContractError("FIPS G2 managed-transit result evidence_type is invalid")
    if root.get("status") != "passed" or root.get("classification") != "experiment":
        raise ContractError("FIPS G2 managed-transit retained result must be a passed experiment")
    if root.get("gate_ids") != ["G2"]:
        raise ContractError("FIPS G2 managed-transit result gate_ids must be exactly ['G2']")
    for field in ("run_id", "started_at", "finished_at"):
        _require_string(root.get(field), f"FIPS G2 managed-transit result.{field}")

    provenance = _require_object(root.get("provenance"), "managed-transit provenance")
    for field in ("project_revision", "fips_commit"):
        commit = _require_string(provenance.get(field), f"provenance.{field}")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"provenance.{field} must be a full lowercase Git commit")
    if provenance.get("fips_source_tree_state") != "clean":
        raise ContractError("provenance.fips_source_tree_state must be clean")
    for field in (
        "cargo_lock_sha256",
        "rust_toolchain_sha256",
        "fips_binary_sha256",
        "fipsctl_binary_sha256",
    ):
        digest = _require_string(provenance.get(field), f"provenance.{field}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"provenance.{field} is invalid")
    if provenance.get("fips_repository") != "https://github.com/jmcorgan/fips.git":
        raise ContractError("provenance.fips_repository is invalid")
    _require_string(provenance.get("reported_version"), "provenance.reported_version")

    platform_data = _require_object(root.get("platform"), "managed-transit platform")
    if platform_data.get("system") != "Linux":
        raise ContractError("managed-transit retained result must come from Linux")
    for field in ("release", "machine", "python"):
        _require_string(platform_data.get(field), f"platform.{field}")

    topology = _require_object(root.get("topology"), "managed-transit topology")
    expected_topology = {
        "node_count": 3,
        "namespace_count": 3,
        "authenticated_link_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "two-segment-line-ipv4-udp",
        "path_role": "managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
    }
    if topology != expected_topology:
        raise ContractError("FIPS G2 managed-transit topology is invalid")

    observations = _require_object(root.get("observations"), "managed-transit observations")
    if set(observations) != {
        "underlay_exclusion",
        "line_topology",
        "identity_resolution",
        "nodes",
        "mmp",
        "icmpv6",
        "payload_identity",
        "transit_forwarding",
        "disconnect",
    }:
        raise ContractError("managed-transit observations contain unexpected fields")
    if observations.get("underlay_exclusion") != {
        "endpoint_direct_ipv4_forwarding_disabled": True,
        "endpoint_direct_ipv4_probe_blocked": True,
    }:
        raise ContractError("observations.underlay_exclusion is invalid")
    if observations.get("line_topology") != {
        "control_connects_acknowledged": 2,
        "authenticated_peer_counts": [1, 2, 1],
        "authenticated_link_counts": [1, 2, 1],
        "estimated_mesh_size": 3,
        "endpoint_direct_peer_absent": True,
        "transport": "udp",
    }:
        raise ContractError("observations.line_topology is invalid")
    if observations.get("identity_resolution") != {
        "mechanism": "local-fips-dns-npub",
        "endpoint_remote_identities_registered": True,
        "public_discovery_used": False,
    }:
        raise ContractError("observations.identity_resolution is invalid")

    nodes = observations.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 3:
        raise ContractError("observations.nodes must contain exactly three nodes")
    expected_nodes = (("a", "endpoint"), ("r", "managed-transit"), ("b", "endpoint"))
    for index, (raw_node, (node_name, role)) in enumerate(zip(nodes, expected_nodes)):
        node = _require_object(raw_node, f"observations.nodes[{index}]")
        if node != {
            "node": node_name,
            "role": role,
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": 1203,
        }:
            raise ContractError(f"observations.nodes[{index}] is invalid")

    mmp = observations.get("mmp")
    if not isinstance(mmp, list) or len(mmp) != 4:
        raise ContractError("observations.mmp must contain four direct-link views")
    if [(item.get("node"), item.get("link_ordinal")) for item in mmp if isinstance(item, dict)] != [
        ("a", 1),
        ("r", 1),
        ("r", 2),
        ("b", 1),
    ]:
        raise ContractError("observations.mmp node/link ordering is invalid")
    for index, raw_mmp in enumerate(mmp):
        item = _require_object(raw_mmp, f"observations.mmp[{index}]")
        if item.get("mode") != "full" or item.get("srtt_ms_observed") is not True:
            raise ContractError(f"observations.mmp[{index}] is incomplete")
        for field in ("loss_rate", "etx"):
            value = item.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ContractError(f"observations.mmp[{index}].{field} is invalid")

    if observations.get("icmpv6") != {
        "path": "endpoint-a-via-managed-transit-r-to-endpoint-b",
        "small_payload_bytes": 32,
        "effective_mtu_boundary_payload_bytes": 1155,
        "passed": True,
    }:
        raise ContractError("observations.icmpv6 is invalid")

    payload = _require_object(observations.get("payload_identity"), "payload identity")
    if (
        payload.get("protocol") != "udp-over-ipv6-over-fips0-multihop"
        or payload.get("all_exact_echo") is not True
    ):
        raise ContractError("observations.payload_identity is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or [item.get("bytes") for item in records] != [1, 1024, 1155]:
        raise ContractError("observations.payload_identity.records has invalid sizes")
    for index, raw_record in enumerate(records):
        record = _require_object(raw_record, f"payload record {index}")
        digest = _require_string(record.get("sha256"), f"payload record {index}.sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or record.get("exact_echo") is not True:
            raise ContractError(f"payload record {index} is invalid")

    transit = _require_object(observations.get("transit_forwarding"), "transit forwarding")
    for field in ("forwarded_packets", "forwarded_bytes"):
        value = transit.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ContractError(f"observations.transit_forwarding.{field} must be positive")
    session_counts = transit.get("endpoint_fsp_session_counts")
    if (
        not isinstance(session_counts, list)
        or len(session_counts) != 2
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in session_counts)
    ):
        raise ContractError("observations.transit_forwarding endpoint sessions are invalid")
    if (
        transit.get("transit_fsp_session_count") != 0
        or transit.get("payload_opaque_to_transit_by_protocol_contract") is not True
    ):
        raise ContractError("observations.transit_forwarding transit role is invalid")

    if observations.get("disconnect") != {
        "control_acknowledgements": 2,
        "peers_per_node_after": [0, 0, 0],
        "links_per_node_after": [0, 0, 0],
    }:
        raise ContractError("observations.disconnect is invalid")

    cleanup = _require_object(root.get("cleanup"), "managed-transit cleanup")
    if cleanup != {
        "daemons_stopped": True,
        "namespaces_removed": True,
        "ephemeral_identity_directory_removed": True,
    }:
        raise ContractError("managed-transit cleanup is incomplete")
    limitations = root.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise ContractError("managed-transit limitations must be a non-empty string array")


def validate_fips_g2_linux_multihop_mtu_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux multihop-MTU result")
    expected_root_fields = {
        "schema_version",
        "evidence_type",
        "run_id",
        "status",
        "classification",
        "gate_ids",
        "started_at",
        "finished_at",
        "provenance",
        "platform",
        "topology",
        "observations",
        "cleanup",
        "limitations",
    }
    if set(root) != expected_root_fields:
        raise ContractError("FIPS G2 multihop-MTU result contains unexpected fields")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 multihop-MTU result schema_version must be 1")
    if root.get("evidence_type") != "fips-g2-linux-multihop-mtu":
        raise ContractError("FIPS G2 multihop-MTU result evidence_type is invalid")

    topology = _require_object(root.get("topology"), "multihop-MTU topology")
    if topology != {
        "node_count": 3,
        "namespace_count": 3,
        "authenticated_link_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "two-segment-line-ipv4-udp",
        "path_role": "managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu_per_node": [1280, 1280, 1280],
        "configured_udp_mtu_per_node": [1280, 1000, 1280],
        "bottleneck_node": "r",
    }:
        raise ContractError("FIPS G2 multihop-MTU topology is invalid")

    observations = _require_object(root.get("observations"), "multihop-MTU observations")
    if set(observations) != {
        "underlay_exclusion",
        "line_topology",
        "identity_resolution",
        "nodes",
        "mmp",
        "icmpv6",
        "path_mtu",
        "payload_identity",
        "transit_forwarding",
        "disconnect",
    }:
        raise ContractError("multihop-MTU observations contain unexpected fields")

    nodes = observations.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 3:
        raise ContractError("multihop-MTU observations.nodes must contain exactly three nodes")
    expected_nodes = (
        ("a", "endpoint", 1203),
        ("r", "managed-transit", 923),
        ("b", "endpoint", 1203),
    )
    for index, (raw_node, (node_name, role, effective_mtu)) in enumerate(
        zip(nodes, expected_nodes)
    ):
        node = _require_object(raw_node, f"multihop-MTU observations.nodes[{index}]")
        if node != {
            "node": node_name,
            "role": role,
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": effective_mtu,
        }:
            raise ContractError(f"multihop-MTU observations.nodes[{index}] is invalid")

    if observations.get("icmpv6") != {
        "path": "endpoint-a-via-managed-transit-r-to-endpoint-b",
        "small_payload_bytes": 32,
        "effective_mtu_boundary_payload_bytes": 875,
        "passed": True,
    }:
        raise ContractError("multihop-MTU observations.icmpv6 is invalid")

    path_mtu = _require_object(observations.get("path_mtu"), "multihop path MTU")
    if path_mtu != {
        "endpoint_effective_ipv6_mtu": 1203,
        "transit_transport_mtu": 1000,
        "learned_transport_path_mtu": 1000,
        "endpoint_session_path_mtus": [1000, 1000],
        "effective_ipv6_path_mtu": 923,
        "boundary_icmp_payload_bytes": 875,
        "above_boundary_icmp_payload_bytes": 876,
        "above_boundary_ipv6_packet_bytes": 924,
        "echo_reply_received": False,
        "icmpv6_type": 2,
        "icmpv6_code": 0,
        "reported_mtu": 923,
        "post_ptb_boundary_probe_passed": True,
    }:
        raise ContractError("multihop-MTU observations.path_mtu is invalid")

    payload = _require_object(observations.get("payload_identity"), "multihop payload identity")
    records = payload.get("records")
    if (
        payload.get("protocol") != "udp-over-ipv6-over-fips0-multihop"
        or payload.get("all_exact_echo") is not True
        or not isinstance(records, list)
        or len(records) != 3
    ):
        raise ContractError("multihop-MTU observations.payload_identity is invalid")
    if [item.get("bytes") for item in records if isinstance(item, dict)] != [1, 512, 875]:
        raise ContractError("multihop-MTU payload record sizes are invalid")

    managed_shape = dict(root)
    managed_shape["evidence_type"] = "fips-g2-linux-managed-transit"
    managed_shape["topology"] = {
        "node_count": 3,
        "namespace_count": 3,
        "authenticated_link_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "two-segment-line-ipv4-udp",
        "path_role": "managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
    }
    managed_observations = dict(observations)
    managed_observations.pop("path_mtu")
    managed_observations["nodes"] = [
        {**node, "effective_ipv6_mtu": 1203} for node in nodes
    ]
    managed_observations["icmpv6"] = {
        **observations["icmpv6"],
        "effective_mtu_boundary_payload_bytes": 1155,
    }
    managed_observations["payload_identity"] = {
        **payload,
        "records": [
            {**record, "bytes": size}
            for record, size in zip(records, (1, 1024, 1155))
        ],
    }
    managed_shape["observations"] = managed_observations
    validate_fips_g2_linux_managed_transit_result(managed_shape)


def validate_fips_g2_linux_lifecycle_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux lifecycle result")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 lifecycle result schema_version must be 1")
    if root.get("evidence_type") != "fips-g2-linux-lifecycle":
        raise ContractError("FIPS G2 lifecycle result evidence_type is invalid")
    if root.get("status") != "passed" or root.get("classification") != "experiment":
        raise ContractError("FIPS G2 lifecycle retained result must be a passed experiment")
    if root.get("gate_ids") != ["G2"]:
        raise ContractError("FIPS G2 lifecycle result gate_ids must be exactly ['G2']")
    for field in ("run_id", "started_at", "finished_at"):
        _require_string(root.get(field), f"FIPS G2 lifecycle result.{field}")

    provenance = _require_object(root.get("provenance"), "lifecycle provenance")
    for field in ("project_revision", "fips_commit"):
        commit = _require_string(provenance.get(field), f"provenance.{field}")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"provenance.{field} must be a full lowercase Git commit")
    if provenance.get("fips_source_tree_state") != "clean":
        raise ContractError("provenance.fips_source_tree_state must be clean")
    for field in (
        "cargo_lock_sha256",
        "rust_toolchain_sha256",
        "fips_binary_sha256",
        "fipsctl_binary_sha256",
    ):
        digest = _require_string(provenance.get(field), f"provenance.{field}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"provenance.{field} is invalid")
    if provenance.get("fips_repository") != "https://github.com/jmcorgan/fips.git":
        raise ContractError("provenance.fips_repository is invalid")
    _require_string(provenance.get("reported_version"), "provenance.reported_version")

    platform_data = _require_object(root.get("platform"), "lifecycle platform")
    if platform_data.get("system") != "Linux":
        raise ContractError("lifecycle retained result must come from Linux")
    for field in ("release", "machine", "python"):
        _require_string(platform_data.get(field), f"platform.{field}")

    expected_topology = {
        "node_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "direct-veth-ipv4-udp",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
        "identity_storage": "temporary-config-adjacent-key-files",
        "restarted_node": "b",
    }
    if root.get("topology") != expected_topology:
        raise ContractError("FIPS G2 lifecycle topology is invalid")

    observations = _require_object(root.get("observations"), "lifecycle observations")
    expected_observation_fields = {
        "nodes_before_failure",
        "initial_connection",
        "initial_mmp",
        "initial_payload_identity",
        "initial_fsp_session_counts",
        "failure_injection",
        "link_dead_detection",
        "identity_continuity",
        "automatic_reconnect",
        "nodes_after_restart",
        "post_restart_mmp",
        "post_restart_icmpv6",
        "post_restart_payload_identity",
        "post_restart_fsp_session_counts",
        "disconnect",
    }
    if set(observations) != expected_observation_fields:
        raise ContractError("lifecycle observations contain unexpected fields")

    def validate_nodes(value: Any, context: str) -> None:
        if not isinstance(value, list) or len(value) != 2:
            raise ContractError(f"{context} must contain exactly two nodes")
        expected = [
            {
                "node": node,
                "tun_state": "active",
                "tun_name": "fips0",
                "kernel_tun_mtu": 1280,
                "effective_ipv6_mtu": 1203,
                "persistent_identity": True,
            }
            for node in ("a", "b")
        ]
        if value != expected:
            raise ContractError(f"{context} is invalid")

    validate_nodes(observations.get("nodes_before_failure"), "nodes_before_failure")
    validate_nodes(observations.get("nodes_after_restart"), "nodes_after_restart")

    if observations.get("initial_connection") != {
        "configured_auto_connect_peers": 1,
        "manual_connect_commands": 0,
        "authenticated_peers_per_node": 1,
        "links_per_node": 1,
        "estimated_mesh_size": 2,
        "transport": "udp",
    }:
        raise ContractError("observations.initial_connection is invalid")

    def validate_mmp(value: Any, context: str) -> None:
        if not isinstance(value, list) or len(value) != 2:
            raise ContractError(f"{context} must contain exactly two node views")
        if [item.get("node") for item in value if isinstance(item, dict)] != ["a", "b"]:
            raise ContractError(f"{context} node ordering is invalid")
        for index, raw_item in enumerate(value):
            item = _require_object(raw_item, f"{context}[{index}]")
            if item.get("mode") != "full" or item.get("srtt_ms_observed") is not True:
                raise ContractError(f"{context}[{index}] is incomplete")
            for field in ("loss_rate", "etx"):
                metric = item.get(field)
                if (
                    not isinstance(metric, (int, float))
                    or isinstance(metric, bool)
                    or metric < 0
                ):
                    raise ContractError(f"{context}[{index}].{field} is invalid")

    validate_mmp(observations.get("initial_mmp"), "initial_mmp")
    validate_mmp(observations.get("post_restart_mmp"), "post_restart_mmp")

    def validate_payload(value: Any, context: str) -> None:
        payload = _require_object(value, context)
        if (
            payload.get("protocol") != "udp-over-ipv6-over-fips0"
            or payload.get("all_exact_echo") is not True
        ):
            raise ContractError(f"{context} is invalid")
        records = payload.get("records")
        if (
            not isinstance(records, list)
            or [item.get("bytes") for item in records if isinstance(item, dict)]
            != [1, 1024, 1155]
        ):
            raise ContractError(f"{context}.records has invalid sizes")
        for index, raw_record in enumerate(records):
            record = _require_object(raw_record, f"{context}.records[{index}]")
            digest = _require_string(
                record.get("sha256"), f"{context}.records[{index}].sha256"
            )
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or record.get("exact_echo") is not True:
                raise ContractError(f"{context}.records[{index}] is invalid")

    validate_payload(
        observations.get("initial_payload_identity"), "initial_payload_identity"
    )
    validate_payload(
        observations.get("post_restart_payload_identity"),
        "post_restart_payload_identity",
    )

    def validate_session_counts(value: Any, context: str) -> None:
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item < 1
                for item in value
            )
        ):
            raise ContractError(f"{context} is invalid")

    validate_session_counts(
        observations.get("initial_fsp_session_counts"), "initial_fsp_session_counts"
    )
    validate_session_counts(
        observations.get("post_restart_fsp_session_counts"),
        "post_restart_fsp_session_counts",
    )

    if observations.get("failure_injection") != {
        "failed_node": "b",
        "signal": "SIGKILL",
        "graceful_disconnect_sent": False,
        "process_exit_observed": True,
    }:
        raise ContractError("observations.failure_injection is invalid")

    link_dead = _require_object(
        observations.get("link_dead_detection"), "link_dead_detection"
    )
    detection_elapsed_ms = link_dead.get("detection_elapsed_ms")
    expected_link_dead = {
        "tick_interval_secs": 1,
        "heartbeat_interval_secs": 10,
        "link_dead_timeout_secs": 30,
        "detection_budget_secs": 60,
        "observer": "node-a",
        "peers_after": 0,
        "links_after": 0,
        "fsp_sessions_after": 0,
        "outage_probe_blocked": True,
    }
    if any(link_dead.get(field) != expected for field, expected in expected_link_dead.items()):
        raise ContractError("observations.link_dead_detection is invalid")
    if (
        not isinstance(detection_elapsed_ms, int)
        or isinstance(detection_elapsed_ms, bool)
        or not 0 < detection_elapsed_ms <= 60_000
    ):
        raise ContractError("link_dead_detection.detection_elapsed_ms is invalid")

    if observations.get("identity_continuity") != {
        "persistent_identity_configured_per_node": [True, True],
        "private_key_file_mode": "0600",
        "public_key_file_mode": "0644",
        "restarted_node": "b",
        "public_identity_unchanged": True,
        "mesh_address_unchanged": True,
        "daemon_pid_changed": True,
        "identity_values_retained": False,
    }:
        raise ContractError("observations.identity_continuity is invalid")

    reconnect = _require_object(
        observations.get("automatic_reconnect"), "automatic_reconnect"
    )
    reconnect_elapsed_ms = reconnect.get("reconnect_elapsed_ms")
    expected_reconnect = {
        "configured": True,
        "retry_base_interval_secs": 5,
        "retry_max_backoff_secs": 300,
        "manual_reconnect_commands": 0,
        "reconnect_budget_secs": 90,
        "authenticated_peers_per_node": 1,
        "links_per_node": 1,
        "estimated_mesh_size": 2,
    }
    if any(reconnect.get(field) != expected for field, expected in expected_reconnect.items()):
        raise ContractError("observations.automatic_reconnect is invalid")
    if (
        not isinstance(reconnect_elapsed_ms, int)
        or isinstance(reconnect_elapsed_ms, bool)
        or not 0 < reconnect_elapsed_ms <= 90_000
    ):
        raise ContractError("automatic_reconnect.reconnect_elapsed_ms is invalid")

    if observations.get("post_restart_icmpv6") != {
        "effective_mtu_boundary_payload_bytes": 1155,
        "echo_requests": 2,
        "passed": True,
    }:
        raise ContractError("observations.post_restart_icmpv6 is invalid")
    if observations.get("disconnect") != {
        "control_acknowledged": True,
        "peers_per_node_after": 0,
        "links_per_node_after": 0,
        "fsp_sessions_per_node_after": 0,
    }:
        raise ContractError("observations.disconnect is invalid")

    if root.get("cleanup") != {
        "daemons_stopped": True,
        "faulted_daemon_reaped": True,
        "namespaces_removed": True,
        "persistent_identity_directory_removed": True,
    }:
        raise ContractError("lifecycle cleanup is incomplete")
    limitations = root.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise ContractError("lifecycle limitations must be a non-empty string array")


def validate_fips_g2_linux_delay_mmp_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux delay/MMP result")
    if set(root) != {
        "schema_version",
        "evidence_type",
        "run_id",
        "status",
        "classification",
        "gate_ids",
        "started_at",
        "finished_at",
        "provenance",
        "platform",
        "topology",
        "observations",
        "cleanup",
        "limitations",
    }:
        raise ContractError("FIPS G2 delay/MMP result contains unexpected fields")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 delay/MMP result schema_version must be 1")
    if root.get("evidence_type") != "fips-g2-linux-delay-mmp":
        raise ContractError("FIPS G2 delay/MMP result evidence_type is invalid")
    if root.get("status") != "passed" or root.get("classification") != "experiment":
        raise ContractError("FIPS G2 delay/MMP retained result must be a passed experiment")
    if root.get("gate_ids") != ["G2"]:
        raise ContractError("FIPS G2 delay/MMP result gate_ids must be exactly ['G2']")
    for field in ("run_id", "started_at", "finished_at"):
        _require_string(root.get(field), f"FIPS G2 delay/MMP result.{field}")

    provenance = _require_object(root.get("provenance"), "delay/MMP provenance")
    for field in ("project_revision", "fips_commit"):
        commit = _require_string(provenance.get(field), f"provenance.{field}")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"provenance.{field} must be a full lowercase Git commit")
    if provenance.get("fips_repository") != "https://github.com/jmcorgan/fips.git":
        raise ContractError("provenance.fips_repository is invalid")
    if provenance.get("fips_source_tree_state") != "clean":
        raise ContractError("provenance.fips_source_tree_state must be clean")
    for field in (
        "cargo_lock_sha256",
        "rust_toolchain_sha256",
        "fips_binary_sha256",
        "fipsctl_binary_sha256",
    ):
        digest = _require_string(provenance.get(field), f"provenance.{field}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"provenance.{field} is invalid")
    _require_string(provenance.get("reported_version"), "provenance.reported_version")

    platform_data = _require_object(root.get("platform"), "delay/MMP platform")
    if platform_data.get("system") != "Linux":
        raise ContractError("delay/MMP retained result must come from Linux")
    for field in ("release", "machine", "python"):
        _require_string(platform_data.get(field), f"platform.{field}")

    topology = _require_object(root.get("topology"), "delay/MMP topology")
    if topology != {
        "node_count": 2,
        "namespace_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "direct-veth-ipv4-udp",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
        "heartbeat_interval_secs": 1,
    }:
        raise ContractError("FIPS G2 delay/MMP topology is invalid")

    observations = _require_object(root.get("observations"), "delay/MMP observations")
    if set(observations) != {
        "nodes",
        "connection",
        "baseline_mmp",
        "delay_injection",
        "degraded_mmp",
        "session_continuity",
        "impaired_icmpv6",
        "impaired_payload_identity",
        "recovery_mmp",
        "disconnect",
    }:
        raise ContractError("delay/MMP observations contain unexpected fields")

    nodes = observations.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 2:
        raise ContractError("observations.nodes must contain exactly two nodes")
    expected_nodes = [
        {
            "node": node,
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": 1203,
        }
        for node in ("a", "b")
    ]
    if nodes != expected_nodes:
        raise ContractError("observations.nodes is invalid")

    if observations.get("connection") != {
        "control_acknowledged": True,
        "authenticated_peers_per_node": 1,
        "links_per_node": 1,
        "estimated_mesh_size": 2,
        "transport": "udp",
    }:
        raise ContractError("observations.connection is invalid")

    def metric_values(raw: Any, context: str, minimum: float, maximum: float) -> list[float]:
        if not isinstance(raw, list) or len(raw) != 2:
            raise ContractError(f"{context} must contain two values")
        values: list[float] = []
        for index, value in enumerate(raw):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not minimum <= value <= maximum
            ):
                raise ContractError(f"{context}[{index}] is outside the frozen bound")
            values.append(float(value))
        return values

    baseline = _require_object(observations.get("baseline_mmp"), "baseline_mmp")
    if set(baseline) != {"mode", "srtt_ms_per_node", "maximum_srtt_ms"}:
        raise ContractError("observations.baseline_mmp contains unexpected fields")
    if baseline.get("mode") != "full" or baseline.get("maximum_srtt_ms") != 25.0:
        raise ContractError("observations.baseline_mmp controls are invalid")
    baseline_values = metric_values(baseline.get("srtt_ms_per_node"), "baseline SRTT", 0, 25)

    if observations.get("delay_injection") != {
        "mechanism": "linux-tc-netem",
        "configured_one_way_delay_ms": 40,
        "configured_loss_percent": 0,
        "impaired_underlay_directions": 2,
        "verified_netem_qdiscs": 2,
    }:
        raise ContractError("observations.delay_injection is invalid")

    degraded = _require_object(observations.get("degraded_mmp"), "degraded_mmp")
    if set(degraded) != {
        "srtt_ms_per_node",
        "minimum_srtt_ms",
        "maximum_srtt_ms",
        "minimum_increase_ms",
        "convergence_budget_secs",
        "convergence_elapsed_ms",
    }:
        raise ContractError("observations.degraded_mmp contains unexpected fields")
    if any(
        degraded.get(field) != expected
        for field, expected in {
            "minimum_srtt_ms": 55.0,
            "maximum_srtt_ms": 200.0,
            "minimum_increase_ms": 30.0,
            "convergence_budget_secs": 60,
        }.items()
    ):
        raise ContractError("observations.degraded_mmp controls are invalid")
    degraded_values = metric_values(
        degraded.get("srtt_ms_per_node"), "degraded SRTT", 55, 200
    )
    if any(after - before < 30 for before, after in zip(baseline_values, degraded_values)):
        raise ContractError("degraded SRTT did not increase by the frozen minimum")
    degraded_elapsed = degraded.get("convergence_elapsed_ms")
    if (
        not isinstance(degraded_elapsed, int)
        or isinstance(degraded_elapsed, bool)
        or not 0 < degraded_elapsed <= 60_000
    ):
        raise ContractError("degraded MMP convergence time is invalid")

    if observations.get("session_continuity") != {
        "session_start_unchanged_during_delay": [True, True],
        "session_start_unchanged_after_recovery": [True, True],
        "peer_counts_during_delay": [1, 1],
        "link_counts_during_delay": [1, 1],
        "fsp_session_counts_during_delay": [1, 1],
    }:
        raise ContractError("observations.session_continuity is invalid")
    if observations.get("impaired_icmpv6") != {
        "effective_mtu_boundary_payload_bytes": 1155,
        "echo_requests": 2,
        "passed": True,
    }:
        raise ContractError("observations.impaired_icmpv6 is invalid")

    payload = _require_object(
        observations.get("impaired_payload_identity"), "impaired_payload_identity"
    )
    if (
        payload.get("protocol") != "udp-over-ipv6-over-fips0"
        or payload.get("all_exact_echo") is not True
        or set(payload) != {"protocol", "records", "all_exact_echo"}
    ):
        raise ContractError("observations.impaired_payload_identity is invalid")
    records = payload.get("records")
    if (
        not isinstance(records, list)
        or [record.get("bytes") for record in records if isinstance(record, dict)]
        != [1, 1024, 1155]
    ):
        raise ContractError("impaired payload records have invalid sizes")
    for index, raw_record in enumerate(records):
        record = _require_object(raw_record, f"impaired payload record {index}")
        digest = _require_string(record.get("sha256"), f"payload record {index}.sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or record.get("exact_echo") is not True:
            raise ContractError(f"impaired payload record {index} is invalid")

    recovery = _require_object(observations.get("recovery_mmp"), "recovery_mmp")
    if set(recovery) != {
        "netem_removed_per_direction",
        "srtt_ms_per_node",
        "maximum_srtt_ms",
        "convergence_budget_secs",
        "convergence_elapsed_ms",
    }:
        raise ContractError("observations.recovery_mmp contains unexpected fields")
    if (
        recovery.get("netem_removed_per_direction") != [True, True]
        or recovery.get("maximum_srtt_ms") != 25.0
        or recovery.get("convergence_budget_secs") != 60
    ):
        raise ContractError("observations.recovery_mmp controls are invalid")
    metric_values(recovery.get("srtt_ms_per_node"), "recovered SRTT", 0, 25)
    recovery_elapsed = recovery.get("convergence_elapsed_ms")
    if (
        not isinstance(recovery_elapsed, int)
        or isinstance(recovery_elapsed, bool)
        or not 0 < recovery_elapsed <= 60_000
    ):
        raise ContractError("recovery MMP convergence time is invalid")

    if observations.get("disconnect") != {
        "control_acknowledged": True,
        "peers_per_node_after": 0,
        "links_per_node_after": 0,
        "fsp_sessions_per_node_after": 0,
    }:
        raise ContractError("observations.disconnect is invalid")
    if root.get("cleanup") != {
        "netem_removed": True,
        "daemons_stopped": True,
        "namespaces_removed": True,
        "ephemeral_identity_directory_removed": True,
    }:
        raise ContractError("delay/MMP cleanup is incomplete")
    limitations = root.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise ContractError("delay/MMP limitations must be a non-empty string array")


def validate_fips_g2_linux_loss_mmp_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux loss/MMP result")
    if set(root) != {
        "schema_version",
        "evidence_type",
        "run_id",
        "status",
        "classification",
        "gate_ids",
        "started_at",
        "finished_at",
        "provenance",
        "platform",
        "topology",
        "observations",
        "cleanup",
        "limitations",
    }:
        raise ContractError("FIPS G2 loss/MMP result contains unexpected fields")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 loss/MMP result schema_version must be 1")
    if root.get("evidence_type") != "fips-g2-linux-loss-mmp":
        raise ContractError("FIPS G2 loss/MMP result evidence_type is invalid")
    if root.get("status") != "passed" or root.get("classification") != "experiment":
        raise ContractError("FIPS G2 loss/MMP retained result must be a passed experiment")
    if root.get("gate_ids") != ["G2"]:
        raise ContractError("FIPS G2 loss/MMP result gate_ids must be exactly ['G2']")
    for field in ("run_id", "started_at", "finished_at"):
        _require_string(root.get(field), f"FIPS G2 loss/MMP result.{field}")

    provenance = _require_object(root.get("provenance"), "loss/MMP provenance")
    for field in ("project_revision", "fips_commit"):
        commit = _require_string(provenance.get(field), f"provenance.{field}")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"provenance.{field} must be a full lowercase Git commit")
    if provenance.get("fips_repository") != "https://github.com/jmcorgan/fips.git":
        raise ContractError("provenance.fips_repository is invalid")
    if provenance.get("fips_source_tree_state") != "clean":
        raise ContractError("provenance.fips_source_tree_state must be clean")
    for field in (
        "cargo_lock_sha256",
        "rust_toolchain_sha256",
        "fips_binary_sha256",
        "fipsctl_binary_sha256",
    ):
        digest = _require_string(provenance.get(field), f"provenance.{field}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"provenance.{field} is invalid")
    _require_string(provenance.get("reported_version"), "provenance.reported_version")

    platform_data = _require_object(root.get("platform"), "loss/MMP platform")
    if platform_data.get("system") != "Linux":
        raise ContractError("loss/MMP retained result must come from Linux")
    for field in ("release", "machine", "python"):
        _require_string(platform_data.get(field), f"platform.{field}")

    topology = _require_object(root.get("topology"), "loss/MMP topology")
    if topology != {
        "node_count": 2,
        "namespace_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "direct-veth-ipv4-udp",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
        "heartbeat_interval_secs": 1,
    }:
        raise ContractError("FIPS G2 loss/MMP topology is invalid")

    observations = _require_object(root.get("observations"), "loss/MMP observations")
    if set(observations) != {
        "nodes",
        "connection",
        "baseline_mmp",
        "loss_injection",
        "degraded_mmp",
        "impaired_probe",
        "session_continuity",
        "recovery_mmp",
        "recovered_icmpv6",
        "recovered_payload_identity",
        "disconnect",
    }:
        raise ContractError("loss/MMP observations contain unexpected fields")

    expected_nodes = [
        {
            "node": node,
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": 1203,
        }
        for node in ("a", "b")
    ]
    if observations.get("nodes") != expected_nodes:
        raise ContractError("observations.nodes is invalid")
    if observations.get("connection") != {
        "control_acknowledged": True,
        "authenticated_peers_per_node": 1,
        "links_per_node": 1,
        "estimated_mesh_size": 2,
        "transport": "udp",
    }:
        raise ContractError("observations.connection is invalid")

    def metric_values(raw: Any, context: str, minimum: float, maximum: float) -> list[float]:
        if not isinstance(raw, list) or len(raw) != 2:
            raise ContractError(f"{context} must contain two values")
        values: list[float] = []
        for index, value in enumerate(raw):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not minimum <= value <= maximum
            ):
                raise ContractError(f"{context}[{index}] is outside the frozen bound")
            values.append(float(value))
        return values

    def smoothed_values(raw: Any, context: str) -> None:
        if not isinstance(raw, list) or len(raw) != 2:
            raise ContractError(f"{context} must contain two values")
        for index, value in enumerate(raw):
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 1
            ):
                raise ContractError(f"{context}[{index}] is invalid")

    baseline = _require_object(observations.get("baseline_mmp"), "baseline_mmp")
    if set(baseline) != {"mode", "loss_rate_per_node", "maximum_loss_rate"}:
        raise ContractError("observations.baseline_mmp contains unexpected fields")
    if baseline.get("mode") != "full" or baseline.get("maximum_loss_rate") != 0.01:
        raise ContractError("observations.baseline_mmp controls are invalid")
    baseline_values = metric_values(
        baseline.get("loss_rate_per_node"), "baseline MMP loss", 0, 0.01
    )

    if observations.get("loss_injection") != {
        "mechanism": "linux-tc-netem",
        "loss_model": "independent-random",
        "configured_loss_percent_per_direction": 20.0,
        "impaired_underlay_directions": 2,
        "verified_netem_qdiscs": 2,
    }:
        raise ContractError("observations.loss_injection is invalid")

    degraded = _require_object(observations.get("degraded_mmp"), "degraded_mmp")
    if set(degraded) != {
        "loss_rate_per_node",
        "smoothed_loss_per_node",
        "minimum_loss_rate",
        "maximum_loss_rate",
        "minimum_increase",
        "convergence_budget_secs",
        "convergence_elapsed_ms",
    }:
        raise ContractError("observations.degraded_mmp contains unexpected fields")
    if any(
        degraded.get(field) != expected
        for field, expected in {
            "minimum_loss_rate": 0.05,
            "maximum_loss_rate": 0.60,
            "minimum_increase": 0.04,
            "convergence_budget_secs": 60,
        }.items()
    ):
        raise ContractError("observations.degraded_mmp controls are invalid")
    degraded_values = metric_values(
        degraded.get("loss_rate_per_node"), "degraded MMP loss", 0.05, 0.60
    )
    if any(after - before < 0.04 for before, after in zip(baseline_values, degraded_values)):
        raise ContractError("degraded MMP loss did not increase by the frozen minimum")
    smoothed_values(degraded.get("smoothed_loss_per_node"), "degraded smoothed MMP loss")
    degraded_elapsed = degraded.get("convergence_elapsed_ms")
    if (
        not isinstance(degraded_elapsed, int)
        or isinstance(degraded_elapsed, bool)
        or not 0 < degraded_elapsed <= 60_000
    ):
        raise ContractError("degraded MMP convergence time is invalid")

    probe = _require_object(observations.get("impaired_probe"), "impaired_probe")
    if set(probe) != {
        "protocol",
        "requests",
        "interval_ms",
        "observed_loss_percent",
        "minimum_loss_percent",
        "maximum_loss_percent",
    }:
        raise ContractError("observations.impaired_probe contains unexpected fields")
    if any(
        probe.get(field) != expected
        for field, expected in {
            "protocol": "icmpv6-over-fips0",
            "requests": 600,
            "interval_ms": 20,
            "minimum_loss_percent": 10.0,
            "maximum_loss_percent": 70.0,
        }.items()
    ):
        raise ContractError("observations.impaired_probe controls are invalid")
    observed_loss = probe.get("observed_loss_percent")
    if (
        not isinstance(observed_loss, (int, float))
        or isinstance(observed_loss, bool)
        or not 10 <= observed_loss <= 70
    ):
        raise ContractError("observations.impaired_probe observed loss is invalid")

    if observations.get("session_continuity") != {
        "session_start_unchanged_during_loss": [True, True],
        "session_start_unchanged_after_recovery": [True, True],
        "peer_counts_during_loss": [1, 1],
        "link_counts_during_loss": [1, 1],
        "fsp_session_counts_during_loss": [1, 1],
    }:
        raise ContractError("observations.session_continuity is invalid")

    recovery = _require_object(observations.get("recovery_mmp"), "recovery_mmp")
    if set(recovery) != {
        "netem_removed_per_direction",
        "loss_rate_per_node",
        "smoothed_loss_per_node",
        "maximum_loss_rate",
        "convergence_budget_secs",
        "convergence_elapsed_ms",
    }:
        raise ContractError("observations.recovery_mmp contains unexpected fields")
    if (
        recovery.get("netem_removed_per_direction") != [True, True]
        or recovery.get("maximum_loss_rate") != 0.01
        or recovery.get("convergence_budget_secs") != 60
    ):
        raise ContractError("observations.recovery_mmp controls are invalid")
    metric_values(recovery.get("loss_rate_per_node"), "recovered MMP loss", 0, 0.01)
    smoothed_values(recovery.get("smoothed_loss_per_node"), "recovered smoothed MMP loss")
    recovery_elapsed = recovery.get("convergence_elapsed_ms")
    if (
        not isinstance(recovery_elapsed, int)
        or isinstance(recovery_elapsed, bool)
        or not 0 < recovery_elapsed <= 60_000
    ):
        raise ContractError("recovery MMP convergence time is invalid")

    if observations.get("recovered_icmpv6") != {
        "effective_mtu_boundary_payload_bytes": 1155,
        "echo_requests": 2,
        "passed": True,
    }:
        raise ContractError("observations.recovered_icmpv6 is invalid")
    payload = _require_object(
        observations.get("recovered_payload_identity"), "recovered_payload_identity"
    )
    if (
        set(payload) != {"protocol", "records", "all_exact_echo"}
        or payload.get("protocol") != "udp-over-ipv6-over-fips0"
        or payload.get("all_exact_echo") is not True
    ):
        raise ContractError("observations.recovered_payload_identity is invalid")
    records = payload.get("records")
    if (
        not isinstance(records, list)
        or [record.get("bytes") for record in records if isinstance(record, dict)]
        != [1, 1024, 1155]
    ):
        raise ContractError("recovered payload records have invalid sizes")
    for index, raw_record in enumerate(records):
        record = _require_object(raw_record, f"recovered payload record {index}")
        digest = _require_string(record.get("sha256"), f"payload record {index}.sha256")
        if (
            set(record) != {"bytes", "sha256", "exact_echo"}
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or record.get("exact_echo") is not True
        ):
            raise ContractError(f"recovered payload record {index} is invalid")

    if observations.get("disconnect") != {
        "control_acknowledged": True,
        "peers_per_node_after": 0,
        "links_per_node_after": 0,
        "fsp_sessions_per_node_after": 0,
    }:
        raise ContractError("observations.disconnect is invalid")
    if root.get("cleanup") != {
        "netem_removed": True,
        "stimulus_process_stopped": True,
        "daemons_stopped": True,
        "namespaces_removed": True,
        "ephemeral_identity_directory_removed": True,
    }:
        raise ContractError("loss/MMP cleanup is incomplete")
    limitations = root.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise ContractError("loss/MMP limitations must be a non-empty string array")


def validate_fips_g2_linux_alternate_route_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux alternate-route result")
    if set(root) != {
        "schema_version",
        "evidence_type",
        "run_id",
        "status",
        "classification",
        "gate_ids",
        "started_at",
        "finished_at",
        "provenance",
        "platform",
        "topology",
        "observations",
        "cleanup",
        "limitations",
    }:
        raise ContractError("FIPS G2 alternate-route result contains unexpected fields")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 alternate-route result schema_version must be 1")
    if root.get("evidence_type") != "fips-g2-linux-alternate-route":
        raise ContractError("FIPS G2 alternate-route result evidence_type is invalid")
    if root.get("status") != "passed" or root.get("classification") != "experiment":
        raise ContractError("FIPS G2 alternate-route retained result must be a passed experiment")
    if root.get("gate_ids") != ["G2"]:
        raise ContractError("FIPS G2 alternate-route result gate_ids must be exactly ['G2']")
    for field in ("run_id", "started_at", "finished_at"):
        _require_string(root.get(field), f"FIPS G2 alternate-route result.{field}")

    provenance = _require_object(root.get("provenance"), "alternate-route provenance")
    for field in ("project_revision", "fips_commit"):
        commit = _require_string(provenance.get(field), f"provenance.{field}")
        if not COMMIT_RE.fullmatch(commit):
            raise ContractError(f"provenance.{field} must be a full lowercase Git commit")
    if provenance.get("fips_repository") != "https://github.com/jmcorgan/fips.git":
        raise ContractError("provenance.fips_repository is invalid")
    if provenance.get("fips_source_tree_state") != "clean":
        raise ContractError("provenance.fips_source_tree_state must be clean")
    for field in (
        "cargo_lock_sha256",
        "rust_toolchain_sha256",
        "fips_binary_sha256",
        "fipsctl_binary_sha256",
    ):
        digest = _require_string(provenance.get(field), f"provenance.{field}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"provenance.{field} is invalid")
    _require_string(provenance.get("reported_version"), "provenance.reported_version")

    platform_data = _require_object(root.get("platform"), "alternate-route platform")
    if platform_data.get("system") != "Linux":
        raise ContractError("alternate-route retained result must come from Linux")
    for field in ("release", "machine", "python"):
        _require_string(platform_data.get(field), f"platform.{field}")

    topology = _require_object(root.get("topology"), "alternate-route topology")
    if topology != {
        "node_count": 4,
        "namespace_count": 4,
        "authenticated_link_count": 4,
        "isolation": "linux-network-namespaces",
        "underlay": "four-segment-diamond-ipv4-udp",
        "path_role": "redundant-managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
        "identity_storage": "temporary-config-adjacent-key-files",
        "root_assignment": "lowest-derived-node-address-to-endpoint-a",
        "path_cost_bias": "r2-b-20ms-one-way-netem-delay",
    }:
        raise ContractError("FIPS G2 alternate-route topology is invalid")

    observations = _require_object(root.get("observations"), "alternate-route observations")
    if set(observations) != {
        "underlay_exclusion",
        "nodes",
        "initial_topology",
        "identity_resolution",
        "initial_payload_identity",
        "initial_path_selection",
        "failure_injection",
        "automatic_reparenting",
        "fsp_session_recovery",
        "post_failure_icmpv6",
        "post_failure_payload_identity",
        "post_failure_path",
    }:
        raise ContractError("alternate-route observations contain unexpected fields")
    if observations.get("underlay_exclusion") != {
        "transit_ipv4_forwarding_disabled": [True, True],
        "endpoint_direct_ipv4_probe_blocked": True,
        "direct_endpoint_underlay_link_absent": True,
    }:
        raise ContractError("observations.underlay_exclusion is invalid")

    nodes = observations.get("nodes")
    expected_nodes = (
        ("a", "endpoint-root"),
        ("r1", "managed-transit"),
        ("r2", "managed-transit"),
        ("b", "endpoint-leaf"),
    )
    if not isinstance(nodes, list) or len(nodes) != 4:
        raise ContractError("observations.nodes must contain exactly four nodes")
    for index, (raw_node, (node_name, role)) in enumerate(zip(nodes, expected_nodes)):
        node = _require_object(raw_node, f"observations.nodes[{index}]")
        if node != {
            "node": node_name,
            "role": role,
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": 1203,
            "persistent_identity": True,
        }:
            raise ContractError(f"observations.nodes[{index}] is invalid")

    initial_path = _require_object(
        observations.get("initial_path_selection"), "initial path selection"
    )
    active = initial_path.get("active_transit")
    alternate = initial_path.get("alternate_transit")
    if (active, alternate) not in (("r1", "r2"), ("r2", "r1")):
        raise ContractError("observations.initial_path_selection transit roles are invalid")
    if set(initial_path) != {
        "active_transit",
        "alternate_transit",
        "endpoint_b_parent_was_active_transit",
        "active_forwarded_packets_delta",
        "active_forwarded_bytes_delta",
        "alternate_forwarded_packets_delta",
        "alternate_forwarded_bytes_delta",
        "transit_fsp_session_counts",
    }:
        raise ContractError("observations.initial_path_selection contains unexpected fields")
    for field in ("active_forwarded_packets_delta", "active_forwarded_bytes_delta"):
        value = initial_path.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ContractError(f"observations.initial_path_selection.{field} must be positive")
    for field in (
        "alternate_forwarded_packets_delta",
        "alternate_forwarded_bytes_delta",
    ):
        value = initial_path.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContractError(
                f"observations.initial_path_selection.{field} must be non-negative"
            )
    if (
        initial_path.get("endpoint_b_parent_was_active_transit") is not True
        or initial_path.get("transit_fsp_session_counts") != [0, 0]
    ):
        raise ContractError("observations.initial_path_selection path proof is invalid")

    initial_topology = observations.get("initial_topology")
    if initial_topology != {
        "configured_auto_connect_peers": 4,
        "manual_connect_commands": 0,
        "authenticated_peer_counts": [2, 2, 2, 2],
        "authenticated_link_counts": [2, 2, 2, 2],
        "root_role": "a",
        "tree_depths": [0, 1, 1, 2],
        "endpoint_b_parent_role": active,
        "alternate_transit_authenticated": True,
        "alternate_path_one_way_delay_ms": 20,
        "full_mmp_link_views": 8,
        "transport": "udp",
    }:
        raise ContractError("observations.initial_topology is invalid")
    if observations.get("identity_resolution") != {
        "mechanism": "local-fips-dns-npub",
        "endpoint_remote_identities_registered": True,
        "public_discovery_used": False,
    }:
        raise ContractError("observations.identity_resolution is invalid")

    def validate_payload(raw_payload: Any, context: str) -> None:
        payload = _require_object(raw_payload, context)
        if (
            payload.get("protocol") != "udp-over-ipv6-over-fips0-multihop"
            or payload.get("all_exact_echo") is not True
            or set(payload) != {"protocol", "records", "all_exact_echo"}
        ):
            raise ContractError(f"{context} is invalid")
        records = payload.get("records")
        if (
            not isinstance(records, list)
            or [item.get("bytes") for item in records if isinstance(item, dict)]
            != [1, 1024, 1155]
        ):
            raise ContractError(f"{context}.records has invalid sizes")
        for index, raw_record in enumerate(records):
            record = _require_object(raw_record, f"{context}.records[{index}]")
            digest = _require_string(record.get("sha256"), f"{context}.records[{index}].sha256")
            if (
                set(record) != {"bytes", "sha256", "exact_echo"}
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or record.get("exact_echo") is not True
            ):
                raise ContractError(f"{context}.records[{index}] is invalid")

    validate_payload(observations.get("initial_payload_identity"), "initial payload identity")

    failure = observations.get("failure_injection")
    if failure != {
        "failed_role": active,
        "signal": "SIGKILL",
        "graceful_disconnect_sent": False,
        "process_exit_observed": True,
        "underlay_interfaces_left_up": True,
        "outage_probe_blocked": True,
    }:
        raise ContractError("observations.failure_injection is invalid")

    reparenting = _require_object(
        observations.get("automatic_reparenting"), "automatic reparenting"
    )
    reparent_elapsed = reparenting.get("reparent_elapsed_ms")
    if (
        not isinstance(reparent_elapsed, int)
        or isinstance(reparent_elapsed, bool)
        or not 0 < reparent_elapsed <= 60_000
    ):
        raise ContractError("observations.automatic_reparenting timing is invalid")
    expected_reparenting = {
        "tick_interval_secs": 1,
        "heartbeat_interval_secs": 10,
        "link_dead_timeout_secs": 30,
        "reparent_budget_secs": 60,
        "reparent_elapsed_ms": reparent_elapsed,
        "old_parent_role": active,
        "new_parent_role": alternate,
        "root_unchanged": True,
        "tree_depth_unchanged": True,
        "declaration_sequence_increased": True,
        "parent_loss_counter_increased": True,
        "manual_route_or_connect_commands": 0,
        "remaining_peer_counts": {"a": 1, "alternate": 2, "b": 1},
        "remaining_link_counts": {"a": 1, "alternate": 2, "b": 1},
    }
    if reparenting != expected_reparenting:
        raise ContractError("observations.automatic_reparenting is invalid")

    session_recovery = _require_object(
        observations.get("fsp_session_recovery"),
        "FSP session recovery",
    )
    poll_count = session_recovery.get("control_poll_count")
    if not isinstance(poll_count, int) or isinstance(poll_count, bool) or poll_count < 1:
        raise ContractError("FSP session recovery control_poll_count is invalid")
    if session_recovery != {
        "target_control_poll_interval_ms": 250,
        "control_poll_count": poll_count,
        "established_through_reparent_control_polls": True,
        "original_session_start_unchanged_through_reparent": [True, True],
        "idle_timeout_secs": 90,
        "manual_session_reset_commands": 0,
        "automatic_session_reestablishment_observed": True,
        "session_start_changed_per_endpoint": [True, True],
        "endpoint_session_counts_after_recovery": [1, 1],
        "alternate_transit_fsp_session_count": 0,
        "identity_values_retained": False,
    }:
        raise ContractError("observations.fsp_session_recovery is invalid")

    if observations.get("post_failure_icmpv6") != {
        "effective_mtu_boundary_payload_bytes": 1155,
        "echo_requests": 2,
        "passed": True,
    }:
        raise ContractError("observations.post_failure_icmpv6 is invalid")
    validate_payload(
        observations.get("post_failure_payload_identity"), "post-failure payload identity"
    )

    post_path = _require_object(observations.get("post_failure_path"), "post-failure path")
    recovery_elapsed = post_path.get("payload_recovery_elapsed_ms")
    if (
        not isinstance(recovery_elapsed, int)
        or isinstance(recovery_elapsed, bool)
        or not reparent_elapsed <= recovery_elapsed <= 180_000
    ):
        raise ContractError("observations.post_failure_path recovery timing is invalid")
    for field in ("forwarded_packets_delta", "forwarded_bytes_delta"):
        value = post_path.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ContractError(f"observations.post_failure_path.{field} must be positive")
    if (
        set(post_path)
        != {
            "forwarding_transit",
            "forwarded_packets_delta",
            "forwarded_bytes_delta",
            "failed_transit_unavailable",
            "payload_recovery_budget_secs",
            "payload_recovery_elapsed_ms",
        }
        or post_path.get("forwarding_transit") != alternate
        or post_path.get("failed_transit_unavailable") is not True
        or post_path.get("payload_recovery_budget_secs") != 180
    ):
        raise ContractError("observations.post_failure_path is invalid")

    cleanup = _require_object(root.get("cleanup"), "alternate-route cleanup")
    if cleanup != {
        "daemons_stopped": True,
        "faulted_daemon_reaped": True,
        "namespaces_removed": True,
        "persistent_identity_directory_removed": True,
    }:
        raise ContractError("alternate-route cleanup is incomplete")
    limitations = root.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(
        not isinstance(item, str) or not item for item in limitations
    ):
        raise ContractError("alternate-route limitations must be a non-empty string array")


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
            elif retained.get("evidence_type") == "fips-g2-linux-direct":
                validate_fips_g2_linux_direct_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-nat":
                validate_fips_g2_linux_nat_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-managed-transit":
                validate_fips_g2_linux_managed_transit_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-multihop-mtu":
                validate_fips_g2_linux_multihop_mtu_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-lifecycle":
                validate_fips_g2_linux_lifecycle_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-alternate-route":
                validate_fips_g2_linux_alternate_route_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-delay-mmp":
                validate_fips_g2_linux_delay_mmp_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-loss-mmp":
                validate_fips_g2_linux_loss_mmp_result(retained)
            else:
                errors.append(f"{path.relative_to(root)}: unknown retained evidence_type")
        except ContractError as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")

    retained_bundles = root / "qualification/retained-bundles"
    if retained_bundles.is_dir():
        from .g4_srt_over_fips import validate_g4_live_capture_bundle

        for bundle in sorted(retained_bundles.iterdir()):
            if not bundle.is_dir():
                continue
            try:
                validate_g4_live_capture_bundle(bundle)
            except (ContractError, OSError, ValueError) as exc:
                errors.append(f"{bundle.relative_to(root)}: {exc}")

    srt_observation_fixture = (
        root / "qualification/fixtures/srt-telemetry-observation-v1.json"
    )
    try:
        validate_srt_telemetry_observation(load_json(srt_observation_fixture))
    except ContractError as exc:
        errors.append(f"{srt_observation_fixture.relative_to(root)}: {exc}")
    try:
        validate_srt_adapter_golden_case(
            root / "qualification/golden-cases/srt-adapter-v1"
        )
    except ContractError as exc:
        errors.append(f"qualification/golden-cases/srt-adapter-v1: {exc}")
    try:
        validate_g4_clock_domain_golden_case(
            root / "qualification/golden-cases/g4-clock-domain-boundary-v1"
        )
    except ContractError as exc:
        errors.append(f"qualification/golden-cases/g4-clock-domain-boundary-v1: {exc}")

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
