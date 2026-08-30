from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contracts import (
    ContractError,
    load_json,
    validate_fips_g2_linux_alternate_route_result,
    validate_fips_g2_linux_direct_result,
    validate_fips_g2_linux_lifecycle_result,
    validate_fips_g2_linux_managed_transit_result,
    validate_fips_g2_linux_multihop_mtu_result,
    validate_fips_g2_linux_nat_result,
    validate_fips_source_assessment,
    validate_repository,
    validate_result,
    validate_scenario,
)
from .fips_g2_linux import QualificationError, run_fips_g2_linux_direct
from .fips_g2_linux_alternate_route import run_fips_g2_linux_alternate_route
from .fips_g2_linux_lifecycle import run_fips_g2_linux_lifecycle
from .fips_g2_linux_managed_transit import (
    run_fips_g2_linux_managed_transit,
    run_fips_g2_linux_multihop_mtu,
)
from .fips_g2_linux_nat import run_fips_g2_linux_nat
from .runner import run_scenario


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
