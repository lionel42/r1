"""Fill the drift end-points from the R1 results (``R1drift_update``).

In ``drift/standards.drift.input``, an end-point value written as ``-`` is
replaced by the R1 ratio of the tank on that date, from ``plot/plot.<gas>``.
The result is written to ``drift/standards.drift``.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from gcwerks.io.standards import read_drift_table
from gcwerks.io.text import is_number, pad
from r1.io.outputs import read_plot_file
from r1.paths import R1Paths

logger = logging.getLogger(__name__)

FROM_RESULTS = "-"


def _plot_ratios(paths: R1Paths, gases: list[str]) -> pd.DataFrame:
    """R1 ratio of the first comparison of each gas, tank and date."""
    tables = [read_plot_file(paths.plot_file(gas)).assign(gas=gas) for gas in gases]
    if not tables:
        return pd.DataFrame(columns=["gas", "tank", "date", "R1ratio"])
    ratios = pd.concat(tables, ignore_index=True)
    return ratios.drop_duplicates(["gas", "tank", "date"])[
        ["gas", "tank", "date", "R1ratio"]
    ]


def fill_drift(drift: pd.DataFrame, ratios: pd.DataFrame) -> pd.DataFrame:
    """Replace the ``-`` end-points of ``drift`` by the matching R1 ratios.

    :param drift: Output of :func:`gcwerks.io.standards.read_drift_table`.
    :param ratios: Columns ``gas``, ``tank``, ``date`` and ``R1ratio``.
    :return: ``drift`` with numeric ``r0`` and ``r1``, NaN where no ratio
        was found.
    :raises ValueError: If an end-point is neither ``-`` nor a number.
    """
    drift = drift.copy()
    lookup = ratios.set_index(["gas", "tank", "date"])["R1ratio"]
    for end in ["0", "1"]:
        value, date = drift[f"r{end}"], drift[f"date{end}"]
        keys = pd.MultiIndex.from_arrays([drift["gas"], drift["tank"], date])
        from_results = pd.Series(lookup.reindex(keys).to_numpy(), index=drift.index)
        placeholder = value.eq(FROM_RESULTS)
        missing = placeholder & from_results.isna()
        for row in drift[missing].itertuples():
            logger.warning(
                f"no R1 ratio for {row.gas} {row.tank} {getattr(row, f'date{end}')}"
            )
        invalid = ~placeholder & ~value.map(is_number)
        if invalid.any():
            bad = ", ".join(
                f"{r.tank} {r.gas} {getattr(r, f'r{end}')!r}"
                for r in drift[invalid].itertuples()
            )
            raise ValueError(f"r{end} must be '{FROM_RESULTS}' or a number: {bad}")
        numeric = value.mask(placeholder).astype(float)
        drift[f"r{end}"] = numeric.where(~placeholder, from_results)
    return drift


def format_drift(drift: pd.DataFrame) -> str:
    """Format a drift table like ``standards.drift``."""
    return "".join(
        f"{pad(r.tank, 16)} {pad(r.gas, 12)} {int(r.fit)}   "
        f"{r.date0} {r.r0:8.5f} {float(r.p0):4.0f}   {r.date1} {r.r1:8.5f} {float(r.p1):4.0f}\n"
        for r in drift.itertuples()
    )


def update_drift(
    paths: R1Paths,
    gases: list[str],
    aliases: dict[str, str] | None = None,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> pd.DataFrame:
    """Write the drift file with the ``-`` end-points filled from the plot files.

    :param paths: Locations in the R1 directory.
    :param gases: Gases whose plot files are read.
    :param aliases: Gas aliases.
    :param input_path: Default: ``drift/standards.drift.input``.
    :param output_path: Default: ``drift/standards.drift``.
    :return: The filled drift table.
    """
    input_path = input_path or paths.drift_input
    output_path = output_path or paths.drift_output
    drift = fill_drift(
        read_drift_table(input_path, aliases), _plot_ratios(paths, gases)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_drift(drift))
    logger.info(
        f"copied {input_path} to {output_path} ({np.isfinite(drift['r0']).sum()} rows)"
    )
    return drift
