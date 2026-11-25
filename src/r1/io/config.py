"""Configuration of an R1 directory: the GCwerks configuration plus the R1
files (fixed values, excluded tanks, R1tanks)."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pandas as pd

from gcwerks.config import GCWerksConfig
from gcwerks.species import resolve_alias
from gcwerks.io.text import is_number, read_table
from r1.paths import R1Paths

logger = logging.getLogger(__name__)

R1_STANDARDS_PATH_KEY = "R1-standards-path"


def read_fixed(path: Path, aliases: dict[str, str] | None = None) -> pd.DataFrame:
    """Read ``R1.standards.fixed``, R1 values imposed instead of calculated.

    :param path: File with lines ``tank gas value``.
    :param aliases: Gas aliases.
    :return: Columns ``tank``, ``gas`` and ``value``. Lines with a
        non-numeric value are left out.
    """
    fixed = read_table(path, ["tank", "gas", "value"])
    fixed["gas"] = resolve_alias(fixed["gas"], aliases or {})
    invalid = ~fixed["value"].map(is_number)
    for row in fixed[invalid].itertuples():
        logger.warning(
            f"{path}: fixed value {row.value!r} of {row.tank} {row.gas} is not"
            " a number, line skipped"
        )
    fixed = fixed[~invalid].copy()
    fixed["value"] = fixed["value"].astype(float)
    return fixed.dropna(subset=["value"]).reset_index(drop=True)


def read_exclude(path: Path) -> list[str]:
    """Read ``R1.standards.exclude``, tanks left out of ``R1.standards``.

    :param path: File with one tank per line.
    :return: The tank names.
    """
    return read_table(path, ["tank"])["tank"].tolist()


def read_r1tanks(path: Path) -> pd.DataFrame:
    """Read ``R1tanks``, the site where each tank is used.

    :param path: File with lines ``tank site [serial_no] [fill_date]``.
    :return: Columns ``tank``, ``site``, ``serial_no`` and ``fill_date``.
    """
    return read_table(path, ["tank", "site", "serial_no", "fill_date"], required=2)


@dataclass
class R1Config(GCWerksConfig):
    """The configuration of one R1 directory (see :class:`GCWerksConfig`)."""

    paths_class: ClassVar[type[R1Paths]] = R1Paths
    paths: R1Paths

    @property
    def r1_standards_path(self) -> Path | None:
        """The ``R1-standards-path`` directory, or None if not configured."""
        return self.conf_path(R1_STANDARDS_PATH_KEY)
