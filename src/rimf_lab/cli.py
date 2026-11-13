from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contracts import (
    ContractError,
    load_json,
    validate_correlation_envelope,
    validate_fips_g2_linux_alternate_route_result,
    validate_fips_g2_linux_delay_mmp_result,
    validate_fips_g2_linux_direct_result,
    validate_fips_g2_linux_lifecycle_result,
    validate_fips_g2_linux_loss_mmp_result,
    validate_fips_g2_linux_managed_transit_result,
    validate_fips_g2_linux_multihop_mtu_result,
    validate_fips_g2_linux_nat_result,
    validate_fips_source_assessment,
    validate_g4_ordering_assessment,
    validate_repository,
    validate_result,
    validate_scenario,
    validate_srt_telemetry_observation,
)
from .cross_layer import assess_cross_layer_ordering
from .fips_g2_linux import QualificationError, run_fips_g2_linux_direct
from .fips_g2_linux_alternate_route import run_fips_g2_linux_alternate_route
from .fips_g2_linux_delay_mmp import run_fips_g2_linux_delay_mmp
from .fips_g2_linux_lifecycle import run_fips_g2_linux_lifecycle
from .fips_g2_linux_loss_mmp import run_fips_g2_linux_loss_mmp
from .fips_g2_linux_managed_transit import (
    run_fips_g2_linux_managed_transit,
    run_fips_g2_linux_multihop_mtu,
)
from .fips_g2_linux_nat import run_fips_g2_linux_nat
from .g4_srt_over_fips import (
    run_g4_srt_over_fips_live,
    validate_g4_live_capture_bundle,
)
from .g1_direct_srt import (
    DEFAULT_REPETITIONS,
    run_g1_direct_srt_baseline,
    validate_g1_direct_srt_bundle,
)
from .g4_faulted_diamond import run_g4_faulted_diamond, validate_g4_faulted_diamond_bundle
from .media_frames import write_media_frame_assessment
from .runner import run_scenario
from .srt_adapter import adapt_srt_telemetry_jsonl


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rimf-lab", description="RIMF evidence harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    repository_parser = subparsers.add_parser(
        "validate-repository", help="validate pins, schemas, scenarios, links, and secret patterns"
    )
    repository_parser.add_argument("--root", type=Path, default=Path.cwd())

    scenario_parser = subparsers.add_parser("validate-scenario", help="validate a scenario")
    scenario_parser.add_argument("path", type=Path)

    result_parser = subparsers.add_parser("validate-result", help="validate a generated result")
    result_parser.add_argument("path", type=Path)

    srt_observation_parser = subparsers.add_parser(
        "validate-srt-telemetry-observation",
        help="validate an SRT Telemetry to Fabric adapter observation",
    )
    srt_observation_parser.add_argument("path", type=Path)

    srt_adapter_parser = subparsers.add_parser(
        "adapt-srt-telemetry-jsonl",
        help="convert a pinned SRT Telemetry JSONL snapshot into Fabric observations",
    )
    srt_adapter_parser.add_argument("--source", type=Path, required=True)
    srt_adapter_parser.add_argument("--context", type=Path, required=True)
    srt_adapter_parser.add_argument("--output", type=Path, required=True)

    correlation_parser = subparsers.add_parser(
        "validate-correlation-envelope",
        help="validate a non-SRT Fabric correlation envelope",
    )
    correlation_parser.add_argument("path", type=Path)

    ordering_validation_parser = subparsers.add_parser(
        "validate-g4-ordering-assessment",
        help="validate a G4 ordering-only cross-layer assessment",
    )
    ordering_validation_parser.add_argument("path", type=Path)

    ordering_parser = subparsers.add_parser(
        "assess-cross-layer-ordering",
        help="assess whether an SRT and peer observation have an authorized temporal order",
    )
    ordering_parser.add_argument("--srt", type=Path, required=True)
    ordering_parser.add_argument("--peer", type=Path, required=True)
    ordering_parser.add_argument("--output", type=Path, required=True)

    g4_live_validation_parser = subparsers.add_parser(
        "validate-g4-srt-over-fips-live",
        help="validate a G4 live SRT-over-FIPS capture bundle",
    )
    g4_live_validation_parser.add_argument("directory", type=Path)

    media_frames_parser = subparsers.add_parser(
        "assess-media-framehash",
        help="compare independent FFmpeg SHA256 decoded-frame recordings",
    )
    media_frames_parser.add_argument("--reference", type=Path, required=True)
    media_frames_parser.add_argument("--observed", type=Path, required=True)
    media_frames_parser.add_argument("--output", type=Path, required=True)

    g4_live_run_parser = subparsers.add_parser(
        "run-g4-srt-over-fips-live",
        help="run the privileged Linux two-node SRT-over-FIPS live capture",
    )
    g4_live_run_parser.add_argument("--fips-source", type=Path, required=True)
    g4_live_run_parser.add_argument("--fips", type=Path, required=True)
    g4_live_run_parser.add_argument("--fipsctl", type=Path, required=True)
    g4_live_run_parser.add_argument("--srt-source", type=Path, required=True)
    g4_live_run_parser.add_argument("--srt-library", type=Path, required=True)
    g4_live_run_parser.add_argument("--telemetry-source", type=Path, required=True)
    g4_live_run_parser.add_argument("--incident-peer", type=Path, required=True)
    g4_live_run_parser.add_argument("--library-dir", type=Path, required=True)
    g4_live_run_parser.add_argument("--output-dir", type=Path, required=True)
    g4_live_run_parser.add_argument("--project-revision", required=True)

    diamond_run_parser = subparsers.add_parser(
        "run-g4-faulted-diamond",
        help="run the privileged Linux four-node faulted-diamond SRT media experiment",
    )
    for option in ("--fips-source", "--fips", "--fipsctl", "--srt-source", "--srt-library",
                   "--telemetry-source", "--incident-peer", "--library-dir", "--ffmpeg",
                   "--output-dir"):
        diamond_run_parser.add_argument(option, type=Path, required=True)
    diamond_run_parser.add_argument("--project-revision", required=True)
    diamond_run_parser.add_argument("--fips-timers", choices=("g2-alternate-route", "fast-detection"),
                                    default="g2-alternate-route")
    diamond_run_parser.add_argument("--srt-peer-idle", choices=("extended", "default"), default="extended")
    diamond_run_parser.add_argument("--srt-reconnect", choices=("none", "coordinator-restart"), default="none")
    diamond_run_parser.add_argument("--fault", choices=("transit-sigkill", "transit-blackhole"),
                                    default="transit-sigkill")

    diamond_bundle_parser = subparsers.add_parser(
        "validate-g4-faulted-diamond",
        help="validate a retained G4 faulted-diamond bundle directory",
    )
    diamond_bundle_parser.add_argument("directory", type=Path)

    g1_run_parser = subparsers.add_parser(
        "run-g1-direct-srt-baseline",
        help="run the privileged Linux two-node direct-SRT control baseline",
    )
    g1_run_parser.add_argument("--srt-source", type=Path, required=True)
    g1_run_parser.add_argument("--srt-library", type=Path, required=True)
    g1_run_parser.add_argument("--telemetry-source", type=Path, required=True)
    g1_run_parser.add_argument("--incident-peer", type=Path, required=True)
    g1_run_parser.add_argument("--library-dir", type=Path, required=True)
    g1_run_parser.add_argument("--output-dir", type=Path, required=True)
    g1_run_parser.add_argument("--project-revision", required=True)
    g1_run_parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)

    g1_bundle_parser = subparsers.add_parser(
        "validate-g1-direct-srt-baseline",
        help="validate a retained G1 direct-SRT baseline bundle directory",
    )
    g1_bundle_parser.add_argument("directory", type=Path)

    fips_parser = subparsers.add_parser(
        "validate-fips-assessment", help="validate a retained FIPS source/build assessment"
    )
    fips_parser.add_argument("path", type=Path)

    fips_g2_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-direct", help="validate a retained Linux direct FIPS result"
    )
    fips_g2_result_parser.add_argument("path", type=Path)

    fips_g2_nat_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-nat", help="validate a retained Linux NAT FIPS result"
    )
    fips_g2_nat_result_parser.add_argument("path", type=Path)

    fips_g2_transit_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-managed-transit",
        help="validate a retained Linux managed-transit FIPS result",
    )
    fips_g2_transit_result_parser.add_argument("path", type=Path)

    fips_g2_multihop_mtu_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-multihop-mtu",
        help="validate a retained Linux heterogeneous multihop-MTU FIPS result",
    )
    fips_g2_multihop_mtu_result_parser.add_argument("path", type=Path)

    fips_g2_lifecycle_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-lifecycle",
        help="validate a retained Linux FIPS lifecycle result",
    )
    fips_g2_lifecycle_result_parser.add_argument("path", type=Path)

    fips_g2_alternate_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-alternate-route",
        help="validate a retained Linux FIPS alternate-route result",
    )
    fips_g2_alternate_result_parser.add_argument("path", type=Path)

    fips_g2_delay_mmp_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-delay-mmp",
        help="validate a retained Linux FIPS fixed-delay MMP result",
    )
    fips_g2_delay_mmp_result_parser.add_argument("path", type=Path)

    fips_g2_loss_mmp_result_parser = subparsers.add_parser(
        "validate-fips-g2-linux-loss-mmp",
        help="validate a retained Linux FIPS fixed-loss MMP result",
    )
    fips_g2_loss_mmp_result_parser.add_argument("path", type=Path)

    fips_g2_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-direct", help="run the privileged Linux two-node FIPS qualification"
    )
    fips_g2_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_run_parser.add_argument("--project-revision", required=True)

    fips_g2_nat_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-nat", help="run the privileged Linux three-namespace NAT qualification"
    )
    fips_g2_nat_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_nat_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_nat_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_nat_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_nat_run_parser.add_argument("--project-revision", required=True)

    fips_g2_transit_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-managed-transit",
        help="run the privileged Linux three-node FIPS transit qualification",
    )
    fips_g2_transit_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_transit_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_transit_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_transit_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_transit_run_parser.add_argument("--project-revision", required=True)

    fips_g2_multihop_mtu_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-multihop-mtu",
        help="run the privileged Linux heterogeneous multihop-MTU FIPS qualification",
    )
    fips_g2_multihop_mtu_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_multihop_mtu_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_multihop_mtu_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_multihop_mtu_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_multihop_mtu_run_parser.add_argument("--project-revision", required=True)

    fips_g2_lifecycle_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-lifecycle",
        help="run the privileged Linux FIPS link-dead and restart qualification",
    )
    fips_g2_lifecycle_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_lifecycle_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_lifecycle_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_lifecycle_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_lifecycle_run_parser.add_argument("--project-revision", required=True)

    fips_g2_alternate_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-alternate-route",
        help="run the privileged Linux FIPS alternate-route qualification",
    )
    fips_g2_alternate_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_alternate_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_alternate_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_alternate_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_alternate_run_parser.add_argument("--project-revision", required=True)

    fips_g2_delay_mmp_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-delay-mmp",
        help="run the privileged Linux FIPS fixed-delay MMP qualification",
    )
    fips_g2_delay_mmp_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_delay_mmp_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_delay_mmp_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_delay_mmp_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_delay_mmp_run_parser.add_argument("--project-revision", required=True)

    fips_g2_loss_mmp_run_parser = subparsers.add_parser(
        "run-fips-g2-linux-loss-mmp",
        help="run the privileged Linux FIPS fixed-loss MMP qualification",
    )
    fips_g2_loss_mmp_run_parser.add_argument("--fips-source", type=Path, required=True)
    fips_g2_loss_mmp_run_parser.add_argument("--fips", type=Path, required=True)
    fips_g2_loss_mmp_run_parser.add_argument("--fipsctl", type=Path, required=True)
    fips_g2_loss_mmp_run_parser.add_argument("--output", type=Path, required=True)
    fips_g2_loss_mmp_run_parser.add_argument("--project-revision", required=True)

    run_parser = subparsers.add_parser("run", help="run an enabled, reviewed scenario")
    run_parser.add_argument("--scenario", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-repository":
            validate_repository(args.root)
            print("repository validation: OK")
        elif args.command == "validate-scenario":
            validate_scenario(load_json(args.path))
            print(f"scenario validation: OK ({args.path})")
        elif args.command == "validate-result":
            validate_result(load_json(args.path))
            print(f"result validation: OK ({args.path})")
        elif args.command == "validate-srt-telemetry-observation":
            validate_srt_telemetry_observation(load_json(args.path))
            print(f"SRT telemetry observation validation: OK ({args.path})")
        elif args.command == "adapt-srt-telemetry-jsonl":
            result = adapt_srt_telemetry_jsonl(args.source, args.context, args.output)
            print(
                "SRT telemetry adaptation: "
                f"{result['status']} ({result['sample_count']} samples, {args.output})"
            )
        elif args.command == "validate-correlation-envelope":
            validate_correlation_envelope(load_json(args.path))
            print(f"correlation envelope validation: OK ({args.path})")
        elif args.command == "validate-g4-ordering-assessment":
            validate_g4_ordering_assessment(load_json(args.path))
            print(f"G4 ordering assessment validation: OK ({args.path})")
        elif args.command == "assess-cross-layer-ordering":
            result = assess_cross_layer_ordering(args.srt, args.peer, args.output)
            print(
                "cross-layer ordering assessment: "
                f"{result['outcome']} ({result['reason']}, {args.output})"
            )
        elif args.command == "validate-g4-srt-over-fips-live":
            validate_g4_live_capture_bundle(args.directory)
            print(f"G4 SRT-over-FIPS live bundle validation: OK ({args.directory})")
        elif args.command == "assess-media-framehash":
            result = write_media_frame_assessment(
                args.reference, args.observed, args.output
            )
            print(
                f"decoded media frame comparison: {result['status']} "
                f"({result['observed_frames']}/{result['expected_frames']} frames, {args.output})"
            )
            return 0 if result["status"] == "exact" else 1
        elif args.command == "run-g4-srt-over-fips-live":
            result = run_g4_srt_over_fips_live(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                srt_source=args.srt_source,
                srt_library=args.srt_library,
                telemetry_source=args.telemetry_source,
                incident_peer=args.incident_peer,
                library_dir=args.library_dir,
                output_dir=args.output_dir,
                project_revision=args.project_revision,
            )
            print(f"G4 SRT-over-FIPS live capture: {result['status']} ({args.output_dir})")
        elif args.command == "run-g4-faulted-diamond":
            result = run_g4_faulted_diamond(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                srt_source=args.srt_source,
                srt_library=args.srt_library,
                telemetry_source=args.telemetry_source,
                incident_peer=args.incident_peer,
                library_dir=args.library_dir,
                ffmpeg=args.ffmpeg,
                output_dir=args.output_dir,
                project_revision=args.project_revision,
                fips_timers=args.fips_timers,
                srt_peer_idle=args.srt_peer_idle,
                srt_reconnect=args.srt_reconnect,
                fault=args.fault,
            )
            print(f"G4 faulted diamond: {result['status']} ({args.output_dir})")
        elif args.command == "validate-g4-faulted-diamond":
            validate_g4_faulted_diamond_bundle(args.directory)
            print(f"G4 faulted-diamond bundle validation: OK ({args.directory})")
        elif args.command == "run-g1-direct-srt-baseline":
            result = run_g1_direct_srt_baseline(
                srt_source=args.srt_source,
                srt_library=args.srt_library,
                telemetry_source=args.telemetry_source,
                incident_peer=args.incident_peer,
                library_dir=args.library_dir,
                output_dir=args.output_dir,
                project_revision=args.project_revision,
                repetitions=args.repetitions,
            )
            print(
                f"G1 direct-SRT baseline: {result['status']} "
                f"({result['summary']['repetition_count']} repetitions, {args.output_dir})"
            )
        elif args.command == "validate-g1-direct-srt-baseline":
            validate_g1_direct_srt_bundle(args.directory)
            print(f"G1 direct-SRT baseline bundle validation: OK ({args.directory})")
        elif args.command == "validate-fips-assessment":
            validate_fips_source_assessment(load_json(args.path))
            print(f"FIPS assessment validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-direct":
            validate_fips_g2_linux_direct_result(load_json(args.path))
            print(f"FIPS G2 Linux direct validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-nat":
            validate_fips_g2_linux_nat_result(load_json(args.path))
            print(f"FIPS G2 Linux NAT validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-managed-transit":
            validate_fips_g2_linux_managed_transit_result(load_json(args.path))
            print(f"FIPS G2 Linux managed-transit validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-multihop-mtu":
            validate_fips_g2_linux_multihop_mtu_result(load_json(args.path))
            print(f"FIPS G2 Linux multihop-MTU validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-lifecycle":
            validate_fips_g2_linux_lifecycle_result(load_json(args.path))
            print(f"FIPS G2 Linux lifecycle validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-alternate-route":
            validate_fips_g2_linux_alternate_route_result(load_json(args.path))
            print(f"FIPS G2 Linux alternate-route validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-delay-mmp":
            validate_fips_g2_linux_delay_mmp_result(load_json(args.path))
            print(f"FIPS G2 Linux delay/MMP validation: OK ({args.path})")
        elif args.command == "validate-fips-g2-linux-loss-mmp":
            validate_fips_g2_linux_loss_mmp_result(load_json(args.path))
            print(f"FIPS G2 Linux loss/MMP validation: OK ({args.path})")
        elif args.command == "run-fips-g2-linux-direct":
            result = run_fips_g2_linux_direct(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux direct: {result['status']} ({args.output})")
        elif args.command == "run-fips-g2-linux-nat":
            result = run_fips_g2_linux_nat(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux NAT: {result['status']} ({args.output})")
        elif args.command == "run-fips-g2-linux-managed-transit":
            result = run_fips_g2_linux_managed_transit(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux managed transit: {result['status']} ({args.output})")
        elif args.command == "run-fips-g2-linux-multihop-mtu":
            result = run_fips_g2_linux_multihop_mtu(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux multihop MTU: {result['status']} ({args.output})")
        elif args.command == "run-fips-g2-linux-lifecycle":
            result = run_fips_g2_linux_lifecycle(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux lifecycle: {result['status']} ({args.output})")
        elif args.command == "run-fips-g2-linux-alternate-route":
            result = run_fips_g2_linux_alternate_route(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux alternate route: {result['status']} ({args.output})")
        elif args.command == "run-fips-g2-linux-delay-mmp":
            result = run_fips_g2_linux_delay_mmp(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux delay/MMP: {result['status']} ({args.output})")
        elif args.command == "run-fips-g2-linux-loss-mmp":
            result = run_fips_g2_linux_loss_mmp(
                fips_source=args.fips_source,
                fips_binary=args.fips,
                fipsctl_binary=args.fipsctl,
                output=args.output,
                project_revision=args.project_revision,
            )
            print(f"FIPS G2 Linux loss/MMP: {result['status']} ({args.output})")
        elif args.command == "run":
            result = run_scenario(args.scenario, args.output, args.root)
            print(f"run {result['run_id']}: {result['status']} ({result['classification']})")
            print(f"result: {args.output}")
            return 0 if result["status"] == "passed" else 1
        else:
            raise AssertionError(f"unhandled command: {args.command}")
    except (ContractError, QualificationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
