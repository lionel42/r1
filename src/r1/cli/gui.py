"""``r1 gui``: open the Qt viewer of the R1 plots."""

import argparse
from pathlib import Path

from gcwerks.cli import add_gas_argument
from r1.paths import R1Paths

DEFAULT_DIR = Path("/agage/R1/medusa2")


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``gui`` command."""
    parser = subparsers.add_parser(
        "gui",
        help="open the viewer of the R1 plots (needs PySide6)",
        description=(
            "Without -C, opens the current directory if it is an R1 directory, "
            f"else {DEFAULT_DIR}."
        ),
    )
    add_gas_argument(parser, help="gas shown first (default: the first of peak.list)")
    desktop = parser.add_mutually_exclusive_group()
    desktop.add_argument(
        "--install-desktop",
        action="store_true",
        help="add 'R1' to the Linux application menu, then exit",
    )
    desktop.add_argument(
        "--uninstall-desktop",
        action="store_true",
        help="remove it from the application menu, then exit",
    )
    parser.set_defaults(run=run)


def gui_dir(gcdir: Path) -> Path:
    """Return ``gcdir``, or :data:`DEFAULT_DIR` if ``gcdir`` is the current
    directory (the default of ``-C``) and not an R1 directory."""
    if gcdir == Path.cwd() and not R1Paths(gcdir).peak_list.is_file():
        return DEFAULT_DIR
    return gcdir


def run(args: argparse.Namespace) -> None:
    """Run the ``gui`` command."""
    if args.install_desktop or args.uninstall_desktop:
        from r1 import desktop

        if args.install_desktop:
            for path in desktop.install_desktop_entry():
                print(f"wrote {path}")
        else:
            for path in desktop.uninstall_desktop_entry():
                print(f"removed {path}")
        return

    from r1.gui import main

    main(gui_dir(args.gcdir), args.gas)
