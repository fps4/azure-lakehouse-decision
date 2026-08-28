"""Command line: ``decide``, ``explain``, ``simulate``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import load_catalog
from .report import console_summary, explain, write_all
from .rules import build_plan


def cmd_decide(args: argparse.Namespace) -> int:
    cat = load_catalog(args.config)
    plan = build_plan(cat)
    print(console_summary(plan))
    if not args.no_report:
        written = write_all(plan, args.reports)
        print("\n" + "\n".join(f"wrote {p}" for p in written))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    cat = load_catalog(args.config)
    plan = build_plan(cat)
    try:
        print(explain(plan, args.workload_id, cat))
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from .sim.run import run as sim_run

    sim_run(reports_dir=args.reports)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="azlake", description=__doc__)
    p.add_argument("--config", type=Path, default=None, help="override the config directory")
    p.add_argument("--reports", type=Path, default=None, help="override the reports directory")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("decide", help="place every workload and size the capacity")
    d.add_argument("--no-report", action="store_true", help="print only; write nothing")
    d.set_defaults(func=cmd_decide)

    e = sub.add_parser("explain", help="explain one workload in full")
    e.add_argument("workload_id")
    e.set_defaults(func=cmd_explain)

    s = sub.add_parser("simulate", help="execute both platform shapes on local data")
    s.set_defaults(func=cmd_simulate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
