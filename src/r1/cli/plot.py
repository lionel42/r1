"""``r1 plot``: plot the R1 ratios of a tank, a site or a filtered selection."""

import argparse
from pathlib import Path

from gcwerks.cli import add_gas_argument
from gcwerks.standards import Standards
from r1.io.config import R1Config, read_r1tanks
from r1.io.outputs import read_plot_file
from r1.plot import plot_comparisons
from r1.select import filter_comparisons, select_comparisons


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``plot`` command."""
    parser = subparsers.add_parser(
        "plot",
        help="plot R1 ratios from plot/plot.<gas> (R1plot)",
        description="Select comparisons by tank, by site (R1tanks) or by name filters.",
    )
    add_gas_argument(parser, required=True)
    parser.add_argument("--tank")
    parser.add_argument("--site", help="site code of the tanks, from R1tanks")
    parser.add_argument(
        "--filter-tank", nargs="*", default=[], help="tank prefixes, -X excludes"
    )
    parser.add_argument(
        "--filter-std", nargs="*", default=[], help="std prefixes, -X excludes"
    )
    parser.add_argument("--mode", choices=["and", "or"], default="and")
    parser.add_argument(
        "--scale", type=float, default=0, help="full scale in %% (0: self-scale)"
    )
    parser.add_argument(
        "--exclude-flagged-from-scale",
        action="store_true",
        help="ignore F/N points in self-scale",
    )
    parser.add_argument("-o", "--output", help="image file (default: plot/<gas>.png)")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> None:
    """Run the ``plot`` command."""
    config = R1Config.from_dir(args.gcdir)
    gas = config.resolve_gas(args.gas)
    paths = config.paths

    table = read_plot_file(paths.plot_file(gas))
    r1tanks = read_r1tanks(paths.r1tanks) if args.site else None
    table = select_comparisons(table, args.tank, args.site, r1tanks)
    table = filter_comparisons(table, args.filter_tank, args.filter_std, args.mode)

    standards = Standards.from_files(
        paths.standards,
        [paths.standards_drift, paths.r1_standards_drift],
        config.aliases,
    )
    default_output = paths.plot_dir / f"{gas}.png"
    output = Path(args.output) if args.output else default_output
    plot_comparisons(
        table,
        gas,
        standards,
        scale_percent=args.scale,
        include_flagged=not args.exclude_flagged_from_scale,
        output=output,
    )
