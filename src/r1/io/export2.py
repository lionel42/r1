"""The ``export2/`` comparison files.

Each tank/std comparison is one file
``export2/<instrument>/<gas>/<tank>_<std>_<yymmdd>`` with one line::

    r_ht  %stdev_ht  n_ht   r_a  %stdev_a  n_a  gcwerks_flag

where ``r = C_tank / C_std`` from peak height (``ht``) or area (``a``).
"""

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from gcwerks.io.conf import site_code
from gcwerks.io.text import is_number

logger = logging.getLogger(__name__)

RATIO_COLUMNS = ["r_ht", "pstdev_ht", "n_ht", "r_a", "pstdev_a", "n_a"]
EXPORT2_COLUMNS = [
    "instrument",
    "site",
    "tank",
    "std",
    "date",
    *RATIO_COLUMNS,
    "gcwerks_flag",
]


def _parse_export2_file(path: Path) -> dict | None:
    """Read one comparison file, or return None if it is malformed.

    A file is malformed if its name is not ``<tank>_<std>_<date>`` or if it
    has fewer than :data:`RATIO_COLUMNS` values or a non-numeric one.
    """
    name_parts = path.name.split("_")
    tokens = path.read_text().split()
    if len(name_parts) != 3:
        logger.warning(f"skipping export2 file not named tank_std_date: {path}")
        return None
    ratios = tokens[: len(RATIO_COLUMNS)]
    if len(ratios) < len(RATIO_COLUMNS):
        logger.warning(
            f"skipping export2 file with {len(ratios)} values instead of"
            f" {len(RATIO_COLUMNS)}: {path}"
        )
        return None
    invalid = [
        f"{column}={token!r}"
        for column, token in zip(RATIO_COLUMNS, ratios)
        if not is_number(token)
    ]
    if invalid:
        logger.warning(
            f"skipping export2 file with non-numeric {', '.join(invalid)}: {path}"
        )
        return None

    tank, std, date = name_parts
    record = dict(zip(RATIO_COLUMNS, ratios))
    record.update(tank=tank, std=std, date=date)
    record["gcwerks_flag"] = tokens[len(RATIO_COLUMNS)] if len(tokens) > 6 else ""
    return record


def read_export2(
    export2_dir: Path,
    gas: str,
    site_codes: pd.DataFrame,
    progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Read all comparisons of ``gas``, from every instrument.

    :param export2_dir: The ``export2`` directory.
    :param gas: The gas (directory name under each instrument).
    :param site_codes: See :func:`r1.io.config.read_site_codes`.
    :param progress: Called with (files read, number of files).
    :return: One row per comparison, columns :data:`EXPORT2_COLUMNS`. Ratios
        of 0 are replaced by NaN.
    """
    files = []
    for instrument_dir in sorted(export2_dir.iterdir()):
        gas_dir = instrument_dir / gas
        if not gas_dir.is_dir():
            continue
        instrument = instrument_dir.name
        site = site_code(instrument, site_codes)
        files += [(instrument, site, path) for path in sorted(gas_dir.iterdir())]

    records = []
    for i, (instrument, site, path) in enumerate(files):
        record = _parse_export2_file(path)
        if record is not None:
            records.append({"instrument": instrument, "site": site, **record})
        if progress is not None:
            progress(i + 1, len(files))

    comparisons = pd.DataFrame(records, columns=EXPORT2_COLUMNS)
    comparisons[RATIO_COLUMNS] = (
        comparisons[RATIO_COLUMNS].astype(float)
    )
    for kind in ["ht", "a"]:
        missing = comparisons[f"r_{kind}"].eq(0)
        comparisons.loc[missing, [f"r_{kind}", f"pstdev_{kind}"]] = np.nan
    comparisons[["n_ht", "n_a"]] = comparisons[["n_ht", "n_a"]].fillna(0).astype(int)

    logger.info(f"read {len(comparisons)} {gas} comparisons from {export2_dir}")
    return comparisons


def write_export2_file(
    export2_dir: Path,
    instrument: str,
    gas: str,
    tank: str,
    std: str,
    date: str,
    ratios: dict[str, float],
    gcwerks_flag: str = "-",
    comment: str = "",
) -> Path:
    """Write one comparison file.

    Underscores in tank names are replaced by ``-``, since ``_`` separates
    the parts of the file name.

    :param export2_dir: The ``export2`` directory.
    :param instrument: Instrument directory, e.g. ``sio-medusa``.
    :param gas: The gas.
    :param tank: The tank measured.
    :param std: The standard it was measured against.
    :param date: ``yymmdd`` of the first run.
    :param ratios: Values for the keys of :data:`RATIO_COLUMNS`.
    :param gcwerks_flag: ``A``, ``H``, ``-``, or ``c`` for converted data.
    :param comment: Written after ``#`` on the second line.
    :return: The file written.
    """
    tank, std = tank.replace("_", "-"), std.replace("_", "-")
    path = export2_dir / instrument / gas / f"{tank}_{std}_{date}"
    path.parent.mkdir(parents=True, exist_ok=True)

    r = ratios
    line = (
        f"{r['r_ht']:9.6f} {r['pstdev_ht']:8.5f} {int(r['n_ht']):3d}   "
        f"{r['r_a']:9.6f} {r['pstdev_a']:8.5f} {int(r['n_a']):3d}  {gcwerks_flag}\n"
    )
    path.write_text(line + (f"  # {comment}\n" if comment else "\n"))
    return path
