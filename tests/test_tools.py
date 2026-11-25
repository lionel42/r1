"""Tests of drift update, diff and selection."""

import numpy as np
import pandas as pd
import pytest

from gcwerks.io.standards import read_standards_drift
from r1 import diff
from r1.calc import calculate
from r1.drift import update_drift
from r1.io.outputs import write_results
from r1.select import filter_comparisons, parent_tanks, select_comparisons, used_stds


def test_drift_update(config):
    write_results(calculate(config), config.paths, config.gases)
    drift = update_drift(config.paths, config.gases, config.aliases)
    j101 = drift.set_index("tank").loc["J-101"]
    assert j101["r0"] == pytest.approx(1.0)
    assert j101["r1"] == pytest.approx(1.001)

    written = read_standards_drift(config.paths.drift_output)
    assert written.set_index("tank").loc["J-102", "r1"] == pytest.approx(1.09)


def test_drift_update_missing_ratio(config):
    write_results(calculate(config), config.paths, config.gases)
    config.paths.drift_input.write_text("E-001 CFC-12 1 200101 - 0 240201 - 0\n")
    drift = update_drift(config.paths, config.gases)
    assert np.isnan(drift.loc[0, "r0"])
    assert drift.loc[0, "r1"] == pytest.approx(0.95 * 1.0002)


@pytest.fixture
def two_files():
    values1 = pd.DataFrame(
        {"A": [1.0, 2.0, np.nan, 5.0], "B": [1.0, 1.0, 1.0, np.nan]},
        index=pd.Index(["t-1", "T-2", "T-3", "T-4"], name="tank"),
    )
    values2 = pd.DataFrame(
        {"A": [1.001, 2.0, 3.0], "B": [1.0, np.nan, 1.0]},
        index=pd.Index(["T-1", "T-2", "T-3"], name="tank"),
    )
    return values1, values2


def test_compare_standards(two_files):
    table = diff.compare_standards(*two_files, pd.Series({"A": 100.0}))
    table = table.set_index(["tank", "gas"])
    assert ("T-4", "A") not in table.index  # not in file2
    assert table.loc[("t-1", "A"), "diff"] == pytest.approx(0.1)
    assert table.loc[("T-2", "B"), "status"] == diff.ONLY_FILE1
    assert table.loc[("T-3", "A"), "status"] == diff.ONLY_FILE2


def test_summary_and_report(two_files):
    table = diff.compare_standards(*two_files, pd.Series({"A": 100.0}))
    summary = diff.summary(table)
    assert summary.loc["A"].tolist() == [1, 1, 0, 1]
    assert summary.loc["B"].tolist() == [0, 0, 1, 0]

    report = diff.gas_report(table, "A")
    assert set(report["tank"]) == {"t-1", "T-3"}
    assert set(diff.gas_report(table, "A", common=True)["tank"]) == {"t-1"}


def test_filter_comparisons():
    table = pd.DataFrame(
        {
            "tank": ["G-001", "G-055", "E-001", "E-002"],
            "std": ["J-1", "J-2", "J-1", "K-1"],
        }
    )
    assert list(filter_comparisons(table, ["G-", "-G-055"])["tank"]) == ["G-001"]
    assert list(filter_comparisons(table, [], ["J-"])["tank"]) == [
        "G-001",
        "G-055",
        "E-001",
    ]
    both = filter_comparisons(table, ["E-"], ["J-"], mode="and")
    assert list(both["tank"]) == ["E-001"]
    either = filter_comparisons(table, ["E-"], ["J-"], mode="or")
    assert len(either) == 4


def test_select_by_site(config):
    table = pd.DataFrame({"tank": ["E-001", "E-003", "J-101"]})
    r1tanks = pd.DataFrame({"tank": ["E-001", "E-003"], "site": ["JFJ", "SIO"]})
    assert list(select_comparisons(table, site="JFJ", r1tanks=r1tanks)["tank"]) == [
        "E-001"
    ]
    assert list(select_comparisons(table, tank="J-101")["tank"]) == ["J-101"]


def test_used_stds():
    table = pd.DataFrame(
        {
            "tank": ["E-1", "E-1", "E-1", "E-1", "E-1", "E-1", "E-1", "J-1"],
            "std": ["J-1", "J-1", "J-2", "J-3", "X-9", "J-4", "J-5", "R1"],
            "date": [
                "240101", "240301", "240201", "240201", "240201", "240401", "990101",
                "231201",
            ],
            "flags": ["----", "-I-L", "F---", "*---", "x---", "----", "----", "----"],
            "R1std": [1.0, 1.2, 0.9, 0.9, np.nan, 1.0, 1.0, 1.0],
            "R1ratio": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        }
    )
    # J-4 is after the L comparison; J-5 (1999) is before it
    stds = used_stds(table, "E-1")
    assert stds["std"].tolist() == ["J-1", "J-5"]
    assert stds.iloc[0][["n", "R1std", "first", "last"]].tolist() == [2, 1.1, "240101", "240301"]
    assert used_stds(table, "J-1")["std"].tolist() == ["R1"]
    assert used_stds(table, "R1").empty


def test_parent_tanks():
    table = pd.DataFrame(
        {
            "tank": ["A", "A", "B", "C", "F", "D"],
            "std": ["B", "C", "R1", "B", "Z", "A"],
            "date": ["240101"] * 6,
            "flags": ["----"] * 6,
            "R1std": [1.0] * 6,
            "R1ratio": [1.0] * 6,
        }
    )
    assert parent_tanks(table, "A") == ["B", "C", "R1"]
    assert parent_tanks(table, "D") == ["A", "B", "C", "R1"]
    assert parent_tanks(table, "D", stop={"A"}) == ["A"]
    assert parent_tanks(table, "R1") == []
