"""``r1 drift-update``: fill the drift end-points from the R1 results."""

import argparse
from pathlib import Path

from r1.drift import update_drift
from r1.io.config import R1Config


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``drift-update`` command."""
    parser = subparsers.add_parser(
        "drift-update",
        help="fill drift end-points from plot files (R1drift_update)",
        description="Write drift/standards.drift from drift/standards.drift.input.",
    )
    parser.add_argument(
        "--input", type=Path, help="default: drift/standards.drift.input"
    )
    parser.add_argument("--output", type=Path, help="default: drift/standards.drift")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> None:
    """Run the ``drift-update`` command."""
    config = R1Config.from_dir(args.gcdir)
    update_drift(config.paths, config.gases, config.aliases, args.input, args.output)
