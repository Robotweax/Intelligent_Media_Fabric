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


def validate_fips_g2_linux_direct_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux direct result")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 result schema_version must be 1")
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
