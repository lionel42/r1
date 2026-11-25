"""Plot the R1 ratios of tanks over time (static version of ``R1plot``).

Each comparison is a marker with its standard deviation as error bar
(``+`` measured at SIO, ``o`` measured on site), labelled ``tank/std flags``.
The tank mean and its standard deviation are drawn as horizontal lines, and
the drift of the tank, if any, as a curve.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from gcwerks.standards import Standards

logger = logging.getLogger(__name__)

HOME_SITE = "SIO"
EXCLUDED_FROM_SCALE = ("F", "N")


def _pyplot():
    try:
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise ImportError(
            "plotting needs matplotlib: pip install 'r1[plot]' (or pip install matplotlib)"
        ) from error
    return plt


def _visible_flags(flags: pd.Series) -> pd.Series:
    return flags.str.replace("-", "", regex=False)


def plot_tank(
    ax, table: pd.DataFrame, tank: str, color: str, drift: pd.Series | None = None
) -> None:
    """Draw the comparisons of one tank.

    :param ax: Matplotlib axes.
    :param table: Rows of a plot file (see :func:`r1.io.outputs.read_plot_file`).
    :param tank: The tank to draw.
    :param color: Color of the tank.
    :param drift: Drift curve of the tank (see :meth:`Standards.drift_curve`).
    """
    rows = table[table["tank"] == tank]
    stdev = 0.01 * rows["pstdev"] * rows["R1ratio"]

    for marker, home in [("+", True), ("o", False)]:
        subset = rows["site"].eq(HOME_SITE) == home
        ax.errorbar(
            rows.loc[subset, "time"],
            rows.loc[subset, "R1ratio"],
            yerr=stdev[subset],
            fmt=marker,
            color=color,
            mfc="none",
        )
    labels = (
        rows["tank"] + "/" + rows["std"] + " " + _visible_flags(rows["flags"])
    ).str.strip()
    labels = labels.where(
        rows["site"].eq(HOME_SITE), labels + " (" + rows["site"] + ")"
    )
    for time, ratio, label in zip(rows["time"], rows["R1ratio"], labels):
        if np.isfinite(ratio):
            ax.annotate(
                label,
                (time, ratio),
                xytext=(4, 0),
                textcoords="offset points",
                fontsize="x-small",
                va="center",
                color=color,
            )

    good = rows[~rows["flags"].str[0].isin(["F", "*"])]
    mean, sd = rows["tank_mean"].iloc[0], rows["tank_stdev"].iloc[0]
    if len(good) and np.isfinite(mean) and mean:
        span = [good["time"].min(), good["time"].max()]
        ax.plot(span, [mean, mean], color=color, lw=1)
        for offset in (-sd, sd):
            ax.plot(span, [mean + offset] * 2, color=color, lw=0.5, ls="--")

    if drift is not None and not drift.empty:
        ax.plot(drift.index, drift.to_numpy(), color=color, lw=1, ls=":")


def _y_limits(
    table: pd.DataFrame, scale_percent: float, include_flagged: bool
) -> tuple:
    rows = table[np.isfinite(table["R1ratio"]) & (table["R1ratio"] != 0)]
    if not include_flagged or scale_percent:
        rows = rows[~rows["flags"].str[0].isin(EXCLUDED_FROM_SCALE)]
    stdev = 0.01 * rows["pstdev"].fillna(0) * rows["R1ratio"]
    low, high = (rows["R1ratio"] - stdev).min(), (rows["R1ratio"] + stdev).max()
    if scale_percent:
        mid = (low + high) / 2
        half = mid * 0.5 * scale_percent / 100
        return mid - half, mid + half
    margin = 0.1 * (high - low)
    return low - margin, high + margin


def draw_comparisons(
    ax,
    table: pd.DataFrame,
    gas: str,
    standards: Standards | None = None,
    scale_percent: float = 0,
    include_flagged: bool = True,
) -> None:
    """Draw the R1 ratio of every tank in ``table`` over time on ``ax``.

    :param ax: Matplotlib axes.
    :param table: Rows of a plot file, already selected (see :mod:`r1.select`).
    :param gas: The gas, for the drift curves and the title.
    :param standards: Standards whose drift is drawn.
    :param scale_percent: Full scale of the y axis in % of the value
        (0 = self-scaled).
    :param include_flagged: Include the flagged points in the self-scaling.
    """
    colors = _pyplot().rcParams["axes.prop_cycle"].by_key()["color"]
    for i, tank in enumerate(table["tank"].unique()):
        drift = standards.drift_curve(tank, gas) if standards is not None else None
        plot_tank(ax, table, tank, colors[i % len(colors)], drift)

    if len(table):
        ax.set_ylim(*_y_limits(table, scale_percent, include_flagged))
    scale = f"{scale_percent:g}% full scale" if scale_percent else "self-scaled"
    ax.set_title(f"{gas} ({scale})")


def plot_comparisons(
    table: pd.DataFrame,
    gas: str,
    standards: Standards | None = None,
    scale_percent: float = 0,
    include_flagged: bool = True,
    output: Path | None = None,
):
    """Plot the R1 ratio of every tank in ``table`` over time.

    See :func:`draw_comparisons` for the parameters.

    :param output: Save the figure there instead of returning it open.
    :return: The matplotlib figure.
    """
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(12, 7))
    draw_comparisons(ax, table, gas, standards, scale_percent, include_flagged)
    fig.autofmt_xdate()

    if output is not None:
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"saved {output}")
    return fig
