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


def validate_fips_g2_linux_reactive_mtu_result(data: Any) -> None:
    root = _require_object(data, "FIPS G2 Linux reactive-MTU result")
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
        raise ContractError("FIPS G2 reactive-MTU result contains unexpected fields")
    if root.get("schema_version") != 1:
        raise ContractError("FIPS G2 reactive-MTU result schema_version must be 1")
    if root.get("evidence_type") != "fips-g2-linux-reactive-mtu":
        raise ContractError("FIPS G2 reactive-MTU result evidence_type is invalid")

    topology = _require_object(root.get("topology"), "reactive-MTU topology")
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
        "initial_udp_mtu_per_node": [1280, 1280, 1280],
        "final_udp_mtu_per_node": [1280, 1000, 1280],
        "bottleneck_node": "r",
    }:
        raise ContractError("FIPS G2 reactive-MTU topology is invalid")

    observations = _require_object(root.get("observations"), "reactive-MTU observations")
    if set(observations) != {
        "underlay_exclusion",
        "line_topology",
        "identity_resolution",
        "nodes",
        "mmp",
        "icmpv6",
        "initial_path_mtu",
        "transit_restart",
        "reactive_mtu",
        "path_mtu",
        "payload_identity",
        "transit_forwarding",
        "disconnect",
    }:
        raise ContractError("reactive-MTU observations contain unexpected fields")

    nodes = observations.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 3:
        raise ContractError("reactive-MTU observations.nodes must contain exactly three nodes")
    for index, (raw_node, node_name, role) in enumerate(
        zip(nodes, ("a", "r", "b"), ("endpoint", "managed-transit", "endpoint"))
    ):
        node = _require_object(raw_node, f"reactive-MTU observations.nodes[{index}]")
        if node != {
            "node": node_name,
            "role": role,
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": 1203,
        }:
            raise ContractError(f"reactive-MTU observations.nodes[{index}] is invalid")

    if observations.get("initial_path_mtu") != {
        "configured_transport_path_mtu": 1280,
        "endpoint_session_path_mtus": [1280, 1280],
        "coordinate_cache_path_mtu": 1280,
    }:
        raise ContractError("reactive-MTU initial_path_mtu is invalid")

    restart = _require_object(observations.get("transit_restart"), "reactive transit restart")
    if set(restart) != {
        "configuration_application",
        "transport_config_hot_reload_supported",
        "endpoint_daemons_restarted",
        "transit_identity_preserved",
        "transit_process_restarted",
        "manual_link_reconnect_commands",
        "transport_mtu_before",
        "transport_mtu_after",
        "endpoint_session_start_ms_before",
        "endpoint_session_start_ms_after",
    }:
        raise ContractError("reactive-MTU transit_restart contains unexpected fields")
    starts_before = restart.get("endpoint_session_start_ms_before")
    starts_after = restart.get("endpoint_session_start_ms_after")
    if (
        restart.get("configuration_application")
        != "identity-preserving-process-restart"
        or restart.get("transport_config_hot_reload_supported") is not False
        or restart.get("endpoint_daemons_restarted") is not False
        or restart.get("transit_identity_preserved") is not True
        or restart.get("transit_process_restarted") is not True
        or restart.get("manual_link_reconnect_commands") != 2
        or restart.get("transport_mtu_before") != 1280
        or restart.get("transport_mtu_after") != 1000
        or not isinstance(starts_before, list)
        or len(starts_before) != 2
        or any(not isinstance(value, int) or isinstance(value, bool) for value in starts_before)
        or starts_after != starts_before
    ):
        raise ContractError("reactive-MTU transit_restart continuity is invalid")

    reactive = _require_object(observations.get("reactive_mtu"), "reactive MTU signal")
    if set(reactive) != {
        "trigger_ipv6_packet_bytes",
        "session_path_mtu_before",
        "session_path_mtu_after",
        "coordinate_cache_path_mtu_after",
        "endpoint_mtu_exceeded_delta",
        "endpoint_below_floor_delta",
        "endpoint_uncorroborated_delta",
        "transit_drop_packets_delta",
        "transit_drop_bytes_delta",
        "convergence_elapsed_ms",
        "convergence_budget_ms",
    }:
        raise ContractError("reactive-MTU signal observation contains unexpected fields")
    elapsed = reactive.get("convergence_elapsed_ms")
    if (
        reactive.get("trigger_ipv6_packet_bytes") != 1203
        or reactive.get("session_path_mtu_before") != 1280
        or reactive.get("session_path_mtu_after") != 1000
        or reactive.get("coordinate_cache_path_mtu_after") != 1000
        or not isinstance(reactive.get("endpoint_mtu_exceeded_delta"), int)
        or isinstance(reactive.get("endpoint_mtu_exceeded_delta"), bool)
        or reactive["endpoint_mtu_exceeded_delta"] < 1
        or reactive.get("endpoint_below_floor_delta") != 0
        or reactive.get("endpoint_uncorroborated_delta") != 0
        or not isinstance(reactive.get("transit_drop_packets_delta"), int)
        or isinstance(reactive.get("transit_drop_packets_delta"), bool)
        or reactive["transit_drop_packets_delta"] < 1
        or not isinstance(reactive.get("transit_drop_bytes_delta"), int)
        or isinstance(reactive.get("transit_drop_bytes_delta"), bool)
        or reactive["transit_drop_bytes_delta"] < 1
        or not isinstance(elapsed, int)
        or isinstance(elapsed, bool)
        or not 0 < elapsed <= 20_000
        or reactive.get("convergence_budget_ms") != 20_000
    ):
        raise ContractError("reactive-MTU signal convergence is invalid")

    multihop_shape = dict(root)
    multihop_shape["evidence_type"] = "fips-g2-linux-multihop-mtu"
    multihop_shape["topology"] = {
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
    }
    multihop_observations = dict(observations)
    for field in ("initial_path_mtu", "transit_restart", "reactive_mtu"):
        multihop_observations.pop(field)
    multihop_observations["nodes"] = [
        {**node, "effective_ipv6_mtu": 923 if index == 1 else 1203}
        for index, node in enumerate(nodes)
    ]
    multihop_shape["observations"] = multihop_observations
    validate_fips_g2_linux_multihop_mtu_result(multihop_shape)


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
    if (
        active != "r1"
        or alternate != "r2"
    ):
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
            elif retained.get("evidence_type") == "fips-g2-linux-reactive-mtu":
                validate_fips_g2_linux_reactive_mtu_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-lifecycle":
                validate_fips_g2_linux_lifecycle_result(retained)
            elif retained.get("evidence_type") == "fips-g2-linux-alternate-route":
                validate_fips_g2_linux_alternate_route_result(retained)
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
