"""Comparison flags.

Each comparison has a 4-character flag string, one position per flag
(``-`` when not set):

===  =====  =====================================================
Pos  Value  Meaning
===  =====  =====================================================
0    F      flagged by the user, excluded
0    N      fewer than 3 points
0    ``*``  rejected by the 2-sigma filter of the tank mean
0    x      std had no R1 value, comparison skipped
1    I      invert: swap tank and std and use 1/r
2    H      use peak height instead of area
3    L      last comparison included in the tank mean
===  =====  =====================================================

Flags come from ``flags/default_<instrument>_<yy>`` (or
``flags/default_<instrument>``), if any, then from
``flags/<tank>_<std>_<yymmdd>`` for the comparisons that have one. Their
lines are ``gas flag [comment]``, where ``gas`` may be ``all``. A ``U<flag>``
line (e.g. ``UF``) unsets that flag, and wins over any setting.
"""

import logging
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import pandas as pd

from gcwerks.species import resolve_alias
from gcwerks.io.text import read_table

logger = logging.getLogger(__name__)

NO_FLAGS = "----"
FLAG_POSITIONS = {"F": 0, "I": 1, "H": 2, "L": 3}
ALL_GASES = "all"


def flagged(flags: pd.Series) -> pd.Series:
    """True where the comparison is excluded (``F``, ``N``, ``x`` or ``*``)."""
    return flags.str[0] != "-"


def inverted(flags: pd.Series) -> pd.Series:
    """True where the ``I`` flag is set."""
    return flags.str[1] == "I"


def use_height(flags: pd.Series) -> pd.Series:
    """True where the ``H`` flag is set."""
    return flags.str[2] == "H"


def last(flags: pd.Series) -> pd.Series:
    """True where the ``L`` flag is set."""
    return flags.str[3] == "L"


def set_position(
    flags: pd.Series, mask: pd.Series, position: int, value: str
) -> pd.Series:
    """Return ``flags`` with ``value`` at ``position`` where ``mask`` is True."""
    updated = flags.str[:position] + value + flags.str[position + 1 :]
    return flags.where(~mask, updated)


@lru_cache(maxsize=None)
def _read_flag_file(path: Path) -> pd.DataFrame:
    return read_table(path, ["gas", "flag"])


def read_flag_file(path: Path, aliases: dict[str, str] | None = None) -> pd.DataFrame:
    """Read one flag file.

    :param path: The flag file.
    :param aliases: Gas aliases.
    :return: Columns ``gas`` and ``flag``.
    """
    table = _read_flag_file(path).copy()
    table["gas"] = resolve_alias(table["gas"], aliases or {})
    return table


def combine_flags(lines: pd.DataFrame, gas: str) -> str:
    """Combine the flag lines that apply to one comparison.

    :param lines: Rows from :func:`read_flag_file`, in the order read.
    :param gas: The gas of the comparison.
    :return: The 4-character flag string.
    """
    names = lines["gas"].str.lower()
    selected = set(lines.loc[names.isin([gas.lower(), ALL_GASES]), "flag"])

    flags = list(NO_FLAGS)
    for flag, position in FLAG_POSITIONS.items():
        if flag in selected and f"U{flag}" not in selected:
            flags[position] = flag
    return "".join(flags)


def default_flag_file(flags_dir: Path, instrument: str, date: str) -> Path:
    """Return the default flag file of an instrument for the year of ``date``."""
    yearly = flags_dir / f"default_{instrument}_{date[:2]}"
    return yearly if yearly.is_file() else flags_dir / f"default_{instrument}"


def comparison_flag_file(flags_dir: Path, tank: str, std: str, date: str) -> Path:
    """Return the flag file of one comparison (tank and std as exported)."""
    return flags_dir / f"{tank}_{std}_{date}"


def read_comparison_flags(
    comparisons: pd.DataFrame,
    flags_dir: Path,
    gas: str,
    aliases: dict[str, str] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> pd.Series:
    """Return the flags of each comparison, as exported (before inversion).

    :param comparisons: Rows with ``instrument``, ``tank``, ``std``, ``date``.
    :param flags_dir: The ``flags`` directory.
    :param gas: The gas.
    :param aliases: Gas aliases.
    :param progress: Called with (comparisons done, number of comparisons).
    :return: 4-character flag strings, aligned with ``comparisons``.
    """
    _read_flag_file.cache_clear()
    missing_defaults = set()

    done = 0

    def flags_of(row: pd.Series) -> str:
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, len(comparisons))
        files = []
        default = default_flag_file(flags_dir, row["instrument"], row["date"])
        if default.is_file():
            files.append(default)
        elif default not in missing_defaults:
            # as R1calc2: an instrument without default flag file has no defaults
            logger.warning(f"no default flag file {default}")
            missing_defaults.add(default)
        # only flagged comparisons have their own flag file
        own = comparison_flag_file(flags_dir, row["tank"], row["std"], row["date"])
        if own.is_file():
            files.append(own)
        if not files:
            return NO_FLAGS
        lines = pd.concat([read_flag_file(path, aliases) for path in files])
        return combine_flags(lines, gas)

    if comparisons.empty:
        return pd.Series(dtype=str)
    return comparisons.apply(flags_of, axis=1).astype(str)
