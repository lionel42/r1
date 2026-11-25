"""``r1 calc``: propagate the R1 values and write the results."""

import argparse

from gcwerks.cli import add_gas_argument
from r1.calc import MAX_PASS, calculate
from r1.io.config import R1Config
from r1.io.outputs import write_results


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``calc`` command."""
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "calc",
        help="propagate R1 values (R1calc2)",
        description="Write calc/calc.<gas>, plot/plot.<gas> and results/R1.standards.",
    )
    add_gas_argument(parser, help="only this gas (then R1.standards is not written)")
    parser.add_argument("--sort", action="store_true", help="order calc files by tank")
    parser.add_argument(
        "--start-tank", default="", help="leave earlier tanks out of R1.standards"
    )
    parser.add_argument("--max-pass", type=int, default=MAX_PASS)
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> None:
    """Run the ``calc`` command."""
    config = R1Config.from_dir(args.gcdir)
    gases = [config.resolve_gas(args.gas)] if args.gas else None
    results = calculate(config, gases, max_pass=args.max_pass)
    write_results(
        results,
        config.paths,
        config.gases,
        sort_by_tank=args.sort,
        write_standards_file=not args.gas,
        start_tank=args.start_tank,
    )
