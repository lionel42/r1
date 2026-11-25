"""Outputs of the propagation: ``calc/calc.<gas>``, ``plot/plot.<gas>`` and
``results/R1.standards``."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from gcwerks.io.standards import write_standards
from gcwerks.io.text import pad, yymmdd_to_datetime
from r1.calc import MAX_PASS, CalcResults, GasResult
from r1.paths import R1Paths

logger = logging.getLogger(__name__)

PLOT_COLUMNS = [
    "tank",
    "std",
    "date",
    "site",
    "flags",
    "R1std",
    "R1ratio",
    "pstdev",
    "n",
    "tank_mean",
    "tank_stdev",
    "tank_n",
]

_CALC_HEADER = (
    "#                                                   Std        ----------- used -----------"
    "       ----------- area -----------      ----------- height ---------\n"
    "#Tank        Std           Flag Site     Date       R1         R1       R       %s        n"
    "       R1       R        %s       n      R1       R        %s       n\n"
)


def tank_status(tank: str, row: pd.Series) -> str:
    """Return the status line of a tank in the calc file."""
    if np.isfinite(row["fixed"]):
        return f"Tank {tank}  Fixed = {row['fixed']:.4f}"
    status = f"Tank {tank}  Pass {int(row['pass_done'])}"
    if row["std_skip_count"]:
        status += f"  ({int(row['std_skip_count'])} std skipped)"
    return status


def _calc_line(c: pd.Series) -> str:
    return (
        f"{pad(c['tank'], 12)} {pad(c['std'], 12)}  {c['flags']} {pad(c['site'], 8)} "
        f"{c['date']}    {c['R1std']:8.5f}   "
        f"{c['R1_used']:8.5f} {c['r_used']:8.5f} {c['pstdev_used']:7.4f} {int(c['n_used']):3d}      "
        f"{c['R1_a']:8.5f} {c['r_a']:8.5f} {c['pstdev_a']:7.4f} {int(c['n_a']):3d}     "
        f"{c['R1_ht']:8.5f} {c['r_ht']:8.5f} {c['pstdev_ht']:7.4f} {int(c['n_ht']):3d}\n"
    )


def _mean_block(row: pd.Series) -> str:
    kinds = ["used", "area", "height"]
    means = "".join(f"Mean = {row[f'{k}_mean']:8.5f}".rjust(35) for k in kinds)
    pstdevs = "".join(f"%s = {row[f'{k}_pstdev']:7.4f}".rjust(35) for k in kinds)
    counts = "".join(
        f"N = {int(row[f'{k}_count_used']):2d} (of {int(row[f'{k}_count']):2d})".rjust(
            35
        )
        for k in kinds
    )
    return f"{means}\n{pstdevs}\n{counts}\n\n"


def format_calc(result: GasResult, sort_by_tank: bool = False) -> str:
    """Format the calc report of one gas.

    :param result: The propagation result.
    :param sort_by_tank: Order the tanks by name instead of by pass.
    :return: The content of ``calc/calc.<gas>``.
    """
    tanks = result.tanks
    if not sort_by_tank:
        order = tanks["pass_done"].where(tanks["pass_done"] >= 0, MAX_PASS)
        tanks = tanks.assign(order=order).sort_values("order", kind="stable")

    groups = result.comparisons.groupby("tank")
    text = [f"# {result.gas} (reftank {result.reftank})\n"]
    for tank, row in tanks.iterrows():
        text.append(f"\n#{tank_status(tank, row)}\n")
        if np.isfinite(row["fixed"]):
            continue
        text.append(_CALC_HEADER)
        text.extend(_calc_line(c) for _, c in groups.get_group(tank).iterrows())
        text.append(_mean_block(row))
    return "".join(text)


def plot_table(result: GasResult) -> pd.DataFrame:
    """Return the ``plot/plot.<gas>`` table of one gas (columns :data:`PLOT_COLUMNS`)."""
    c = result.comparisons
    tanks = result.tanks
    return pd.DataFrame(
        {
            "tank": c["tank"],
            "std": c["std"],
            "date": c["date"],
            "site": c["site"],
            "flags": c["flags"],
            "R1std": c["R1std"],
            "R1ratio": c["R1_used"],
            "pstdev": c["pstdev_used"],
            "n": c["n_used"],
            "tank_mean": c["tank"].map(tanks["used_mean"]),
            "tank_stdev": c["tank"].map(tanks["used_stdev"]),
            "tank_n": c["tank"].map(tanks["used_count_used"]),
        }
    )


def format_plot(result: GasResult) -> str:
    """Format the ``plot/plot.<gas>`` file of one gas."""
    header = (
        f"# {result.gas}\n"
        "# Tank            Std           Date    Site      FLAG    R1std      R1ratio    %s"
        "         N   tank_mean  tank_stdev  tank_N\n"
    )
    lines = [
        f"{pad(r.tank, 16)}  {pad(r.std, 12)}  {r.date}   {pad(r.site, 8)}  {r.flags}  "
        f"{r.R1std:9.6f}  {r.R1ratio:9.6f}  {r.pstdev:9.6f}  {r.n:3d}  "
        f"{r.tank_mean:9.6f}  {r.tank_stdev:9.6f}  {r.tank_n:3d}\n"
        for r in plot_table(result).itertuples()
    ]
    return header + "".join(lines)


def read_plot_file(path: Path) -> pd.DataFrame:
    """Read a ``plot/plot.<gas>`` file.

    :param path: The plot file.
    :return: Columns :data:`PLOT_COLUMNS` plus ``time``.
    """
    table = pd.read_csv(
        path,
        sep=r"\s+",
        comment="#",
        header=None,
        names=PLOT_COLUMNS,
        dtype={"tank": str, "std": str, "date": str, "site": str, "flags": str},
    )
    table["time"] = yymmdd_to_datetime(table["date"])
    return table


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    logger.info(f"wrote {path}")


def write_results(
    results: CalcResults,
    paths: R1Paths,
    gases: list[str],
    sort_by_tank: bool = False,
    write_standards_file: bool = True,
    start_tank: str = "",
) -> None:
    """Write the calc and plot files of each gas, and ``R1.standards``.

    :param results: Output of :func:`r1.calc.calculate`.
    :param paths: Locations in the R1 directory.
    :param gases: All gases of the peak list (columns of ``R1.standards``).
    :param sort_by_tank: See :func:`format_calc`.
    :param write_standards_file: Also write ``results/R1.standards``.
    :param start_tank: Leave tanks sorting before it out of ``R1.standards``.
    """
    for gas, result in results.gases.items():
        _write(paths.calc_file(gas), format_calc(result, sort_by_tank))
        _write(paths.plot_file(gas), format_plot(result))

    if write_standards_file:
        write_standards(
            results.standards.values,
            paths.r1_standards,
            gases,
            exclude=results.exclude,
            start_tank=start_tank,
        )
