"""``r1 diff``: compare two standards files."""

import argparse
import sys
from pathlib import Path

import pandas as pd

from gcwerks.cli import add_gas_argument
from gcwerks.io.standards import read_standards, read_standards_factors
from r1 import diff
from r1.io.config import R1Config


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``diff`` command."""
    parser = subparsers.add_parser(
        "diff",
        help="compare two standards files (R1diff)",
        description="Differences file2 - file1, in concentration units. "
        "Without --gas, prints a summary per gas.",
    )
    parser.add_argument("file1", type=Path)
    parser.add_argument("file2", type=Path)
    add_gas_argument(parser, help="detailed report for this gas")
    parser.add_argument(
        "--common", action="store_true", help="only tanks with values in both"
    )
    parser.add_argument("-t", "--threshold", type=float, default=diff.DEFAULT_THRESHOLD)
    parser.add_argument(
        "-p", "--pthreshold", type=float, default=diff.DEFAULT_PTHRESHOLD
    )
    parser.add_argument("--csv", help="also write all differences to this CSV file")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> None:
    """Run the ``diff`` command."""
    config = R1Config.from_dir(args.gcdir)
    factors = read_standards_factors(config.paths.standards_factors, config.aliases)
    table = diff.compare_standards(
        read_standards(args.file1, config.aliases),
        read_standards(args.file2, config.aliases),
        factors,
    )
    if args.csv:
        table.to_csv(args.csv, index=False)

    if args.gas:
        report = diff.gas_report(
            table,
            config.resolve_gas(args.gas),
            args.threshold,
            args.pthreshold,
            args.common,
        )
    else:
        report = diff.summary(table, args.threshold).reset_index()
    sys.stdout.write(format_report(report))


def format_report(report: pd.DataFrame) -> str:
    """Format a diff report for the terminal."""
    if report.empty:
        return "no differences\n"
    with pd.option_context("display.max_rows", None, "display.width", 200):
        return report.to_string(index=False, float_format="%.4f") + "\n"
