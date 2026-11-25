"""Propagation of calibration scales from reference tanks (R1)."""

from gcwerks.cli import run_commands
from r1.cli import calc, diff, drift, gui, plot

COMMANDS = [calc, diff, drift, plot, gui]
GCDIR_HELP = "R1 directory, e.g. /agage/R1/medusa (default: current directory)"


def main(argv: list[str] | None = None) -> None:
    """Parse the arguments and run the ``r1`` command."""
    run_commands("r1", __doc__, COMMANDS, argv, gcdir_help=GCDIR_HELP)


if __name__ == "__main__":
    main()
