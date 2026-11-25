"""Compare two standards files (``R1diff``).

Differences are ``file2 - file1``, converted to concentrations with
``standards.factors``. Only tanks present in both files are compared (names
are matched case-insensitively).
"""

import pandas as pd

DEFAULT_THRESHOLD = 0.001  # concentration units (ppt)
DEFAULT_PTHRESHOLD = 0.01  # %

BOTH = "both"
ONLY_FILE1 = "in-file1"
ONLY_FILE2 = "in-file2"


def compare_standards(
    values1: pd.DataFrame, values2: pd.DataFrame, factors: pd.Series | None = None
) -> pd.DataFrame:
    """Compare two standards tables.

    :param values1: First table (tank index, one column per gas, NaN for no value).
    :param values2: Second table.
    :param factors: Factor per gas from R1 to concentration (default 1).
    :return: One row per tank and gas with a value in either file: ``tank``,
        ``gas``, ``conc1``, ``diff`` (NaN unless in both) and ``status``
        (:data:`BOTH`, :data:`ONLY_FILE1` or :data:`ONLY_FILE2`).
    """
    lower2 = pd.Series(values2.index, index=values2.index.str.lower())
    common = values1.index[values1.index.str.lower().isin(lower2.index)]
    table1 = values1.loc[common]
    table2 = values2.loc[lower2[common.str.lower()].to_numpy()].set_axis(common)

    gases = table1.columns.intersection(table2.columns, sort=False)
    factors = (factors if factors is not None else pd.Series(dtype=float)).reindex(
        gases
    )
    factors = factors.fillna(1.0)

    long1 = (table1[gases] * factors).stack(future_stack=True).rename("conc1")
    long2 = (table2[gases] * factors).stack(future_stack=True).rename("conc2")
    table = pd.concat([long1, long2], axis=1).dropna(how="all")
    table.index = table.index.set_names(["tank", "gas"])

    table["diff"] = table["conc2"] - table["conc1"]
    table["status"] = BOTH
    table.loc[table["conc2"].isna(), "status"] = ONLY_FILE1
    table.loc[table["conc1"].isna(), "status"] = ONLY_FILE2
    return table.reset_index()[["tank", "gas", "conc1", "diff", "status"]]


def summary(diff: pd.DataFrame, threshold: float = DEFAULT_THRESHOLD) -> pd.DataFrame:
    """Count the differences per gas.

    :param diff: Output of :func:`compare_standards`.
    :param threshold: Absolute difference threshold.
    :return: Per gas (with any count), ``n_above`` (abs diff > threshold),
        ``n_above_pct`` (of those, relative diff > 0.01 %), ``in_file1``
        and ``in_file2``.
    """
    above = diff["diff"].abs() > threshold
    counts = pd.DataFrame(
        {
            "gas": diff["gas"],
            "n_above": above,
            "n_above_pct": above & (100 * (diff["diff"] / diff["conc1"]).abs() > 0.01),
            "in_file1": diff["status"] == ONLY_FILE1,
            "in_file2": diff["status"] == ONLY_FILE2,
        }
    )
    counts = counts.groupby("gas", sort=False).sum()
    return counts[counts.any(axis=1)]


def gas_report(
    diff: pd.DataFrame,
    gas: str,
    threshold: float = DEFAULT_THRESHOLD,
    pthreshold: float = DEFAULT_PTHRESHOLD,
    common: bool = False,
) -> pd.DataFrame:
    """Return the tanks of ``gas`` that differ.

    :param diff: Output of :func:`compare_standards`.
    :param gas: The gas.
    :param threshold: Absolute threshold (0 shows all differences).
    :param pthreshold: Relative threshold in %.
    :param common: Leave out the tanks with a value in one file only.
    :return: Rows of ``diff`` with an added ``pct`` column.
    """
    rows = diff[diff["gas"] == gas].assign(pct=lambda d: 100 * d["diff"] / d["conc1"])
    differs = (rows["diff"].abs() > threshold) & (rows["pct"].abs() > pthreshold)
    if not threshold:
        differs = rows["diff"].notna()
    keep = (rows["status"] == BOTH) & differs
    if not common:
        keep |= rows["status"] != BOTH
    return rows[keep]
