from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contracts import (
    ContractError,
    load_json,
    validate_fips_source_assessment,
    validate_repository,
    validate_result,
    validate_scenario,
)
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
        elif args.command == "run":
            result = run_scenario(args.scenario, args.output, args.root)
            print(f"run {result['run_id']}: {result['status']} ({result['classification']})")
            print(f"result: {args.output}")
            return 0 if result["status"] == "passed" else 1
        else:
            raise AssertionError(f"unhandled command: {args.command}")
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
