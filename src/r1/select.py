"""Selection of comparisons to look at: by tank, by site, or by name filters
(the options of ``R1plot``)."""

from typing import Literal

import numpy as np
import pandas as pd

from gcwerks.io.text import yymmdd_to_datetime
from r1.flags import flagged, last


def prefix_filter(names: pd.Series, patterns: list[str]) -> tuple[pd.Series, pd.Series]:
    """Match names against prefix patterns.

    A pattern ``-XYZ`` excludes the names starting with ``XYZ``, any other
    pattern includes the names starting with it. Exclusions always win,
    whatever the order of the patterns (in ``R1plot`` the first matching
    pattern decided).

    :param names: The names to match.
    :param patterns: The patterns.
    :return: ``(included, excluded)`` masks. ``included`` is all True when
        there is no including pattern.
    """
    include = [p for p in patterns if not p.startswith("-")]
    exclude = [p[1:] for p in patterns if p.startswith("-")]
    included = (
        names.str.startswith(tuple(include))
        if include
        else pd.Series(True, names.index)
    )
    excluded = (
        names.str.startswith(tuple(exclude))
        if exclude
        else pd.Series(False, names.index)
    )
    return included, excluded


def filter_comparisons(
    table: pd.DataFrame,
    tank_patterns: list[str] = (),
    std_patterns: list[str] = (),
    mode: Literal["and", "or"] = "and",
) -> pd.DataFrame:
    """Keep the comparisons whose tank and/or std match the patterns.

    :param table: Rows with ``tank`` and ``std``.
    :param tank_patterns: Patterns for the tank, see :func:`prefix_filter`.
    :param std_patterns: Patterns for the std.
    :param mode: How to combine the tank and std matches when both are given.
    :return: The matching rows.
    """
    tank_in, tank_out = prefix_filter(table["tank"], list(tank_patterns))
    std_in, std_out = prefix_filter(table["std"], list(std_patterns))
    has_tank = any(not p.startswith("-") for p in tank_patterns)
    has_std = any(not p.startswith("-") for p in std_patterns)

    if has_tank and has_std:
        matched = (tank_in & std_in) if mode == "and" else (tank_in | std_in)
    else:
        matched = tank_in & std_in
    return table[matched & ~tank_out & ~std_out]


def select_comparisons(
    table: pd.DataFrame,
    tank: str | None = None,
    site: str | None = None,
    r1tanks: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Keep the comparisons of one tank, or of the tanks used at one site.

    :param table: Rows with ``tank``.
    :param tank: Tank name.
    :param site: Site code, looked up in ``r1tanks``.
    :param r1tanks: See :func:`r1.io.config.read_r1tanks`.
    :return: The selected rows.
    """
    keep = pd.Series(True, index=table.index)
    if tank:
        keep &= table["tank"] == tank
    if site:
        if r1tanks is None:
            raise ValueError("selecting by site needs the R1tanks table")
        keep &= table["tank"].isin(r1tanks.loc[r1tanks["site"] == site, "tank"])
    return table[keep]


def used_stds(table: pd.DataFrame, tank: str) -> pd.DataFrame:
    """The stds the R1 value of ``tank`` was calculated from.

    These are the stds of its comparisons that are used in its mean: not
    flagged (``F``, ``N``, ``*`` or ``x``), not after its ``L`` comparison,
    and with an R1 value for the std and a ratio (as in
    :func:`r1.calc.prepare_comparisons`).
    Following them back from tank to std leads to the reference tank, or to a
    fixed or known value.

    :param table: Rows of a plot file (see :func:`r1.io.outputs.read_plot_file`).
    :param tank: The tank.
    :return: One row per std: ``std``, ``n`` (comparisons used), ``R1std``
        (mean R1 value of the std in them), ``first`` and ``last`` (dates),
        sorted by std.
    """
    rows = table[table["tank"] == tank]
    rows = rows.sort_values(["date", "std"], key=_date_key, kind="stable")
    after_last = last(rows["flags"]).cumsum().shift(fill_value=0) > 0
    rows = rows[
        ~after_last
        & ~flagged(rows["flags"])
        & np.isfinite(rows["R1std"])
        & np.isfinite(rows["R1ratio"])
    ]
    return (
        rows.groupby("std", sort=True)
        .agg(
            n=("std", "size"),
            R1std=("R1std", "mean"),
            first=("date", "first"),
            last=("date", "last"),
        )
        .reset_index()
    )


def _date_key(column: pd.Series) -> pd.Series:
    """Sort key putting ``yymmdd`` dates in time order."""
    if column.name != "date":
        return column
    return yymmdd_to_datetime(column)


def parent_tanks(table: pd.DataFrame, tank: str, stop: set[str] = frozenset()) -> list[str]:
    """All the tanks the R1 value of ``tank`` comes from, nearest first.

    Follows :func:`used_stds` from std to std (the calibration chain). The
    tanks in ``stop`` (e.g. the reference and fixed tanks) end a chain: they
    are listed but their own stds are not followed.

    :param table: Rows of a plot file.
    :param tank: The tank.
    :param stop: Tanks whose stds are not followed.
    :return: The parent tanks, without ``tank``, each once.
    """
    parents: list[str] = []
    queue = [tank]
    while queue:
        current = queue.pop(0)
        if current != tank and current in stop:
            continue
        for std in used_stds(table, current)["std"]:
            if std != tank and std not in parents:
                parents.append(std)
                queue.append(std)
    return parents
