import numpy as np
import pandas as pd
import pytest

from r1.calc import calculate, invert_comparisons, prepare_comparisons

J101 = 1.0002  # mean of the J-101 comparisons with the 1.08 outlier rejected
J102_JULY = 1.10 - 0.01 * 182 / 365  # J-102 drift on 2024-07-01


@pytest.fixture
def results(config):
    return calculate(config)


def comparison(result, tank, date):
    c = result.comparisons
    return c[(c["tank"] == tank) & (c["date"] == date)].iloc[0]


def test_cfc12_values(results):
    tanks = results.gases["CFC-12"].tanks["value"]
    expected = {
        "J-101": J101,
        "J-102": 1.0 / 0.9090909,  # H-001 vs J-102, inverted automatically
        "E-001": 0.951 * J101,  # mean of 0.950, 0.952 (SIO) and 0.951 (JFJ, area)
        "E-003": 1.03 * J101,  # X-999 skipped
        "E-004": 0.97 * J101,  # F before, excluded after L
        "E-005": 0.98 * 1.05,  # std G-001 fixed
        "E-006": 0.90 * J102_JULY,  # std J-102 drifting
        "E-007": J101 / 1.01,  # I flag
    }
    for tank, value in expected.items():
        assert tanks[tank] == pytest.approx(value, rel=1e-6), tank

    e001 = tanks["E-001"]
    assert tanks["E-002"] == pytest.approx(e001 * (1.02 + 1.019) / 2, rel=1e-6)


def test_passes(results):
    tanks = results.gases["CFC-12"].tanks
    assert tanks.loc[["J-101", "J-102", "E-005", "E-006"], "pass_done"].eq(1).all()
    assert tanks.loc[["E-001", "E-002", "E-004", "E-007"], "pass_done"].eq(2).all()
    assert tanks.loc["E-003", "pass_done"] == 3
    assert tanks.loc["E-003", "std_skip_count"] == 1


def test_flags_after_calc(results):
    result = results.gases["CFC-12"]
    assert comparison(result, "J-101", "240610")["flags"] == "*---"
    assert comparison(result, "E-003", "240402")["flags"] == "x---"
    assert comparison(result, "E-002", "240915")["flags"] == "--H-"
    assert not comparison(result, "E-004", "240601")["used"]


def test_too_few_points_dropped(results):
    assert "E-008" not in results.gases["CFC-12"].tanks.index


def test_n2o_uses_heights(results):
    tanks = results.gases["N2O"].tanks["value"]
    assert tanks["J-101"] == pytest.approx(1.021)
    assert tanks["E-001"] == pytest.approx(0.9905 * 1.021)


def test_standards_after_calc(results):
    values = results.standards.values
    assert values.loc["H-001", "CFC-12"] == 1.0
    assert values.loc["G-001", "CFC-12"] == 1.05
    assert np.isnan(values.loc["H-001", "N2O"])
    assert "X-999" not in values.index
    assert results.exclude == ["E-007"]


def test_single_gas(config):
    results = calculate(config, ["N2O"])
    assert list(results.gases) == ["N2O"]


def test_r1_standards_path_first(r1_dir, config):
    extra = r1_dir / "extra"
    extra.mkdir()
    (extra / "standards").write_text("tank CFC-12\nJ-101 2.0\n")
    (extra / "standards.drift").write_text("")
    config.conf["R1-standards-path"] = "extra"
    tanks = calculate(config, ["CFC-12"]).gases["CFC-12"].tanks["value"]
    assert tanks["J-101"] == pytest.approx(J101)  # J-101 itself is still calculated
    assert tanks["E-001"] == pytest.approx(0.951 * 2.0)  # but used with the path value


def test_invert():
    comparisons = pd.DataFrame(
        {
            "tank": ["REF", "A"],
            "std": ["B", "C"],
            "flags": ["----", "-I--"],
            "r_ht": [2.0, 4.0],
            "r_a": [2.0, 4.0],
            "r_used": [2.0, 4.0],
        }
    )
    inverted = invert_comparisons(comparisons, "REF")
    assert list(inverted["tank"]) == ["B", "C"]
    assert list(inverted["r_a"]) == [0.5, 0.25]


def test_last_flag_limits_mean():
    comparisons = pd.DataFrame(
        {
            "tank": ["A"] * 3 + ["B"],
            "std": ["S"] * 4,
            "date": ["240101", "240201", "240301", "240101"],
            "flags": ["----", "---L", "----", "----"],
            "r_ht": 1.0,
            "r_a": 1.0,
            "r_used": 1.0,
        }
    )
    prepared = prepare_comparisons(comparisons, "REF")
    assert list(prepared["in_mean"]) == [True, True, False, True]


def test_gas_without_comparisons(config):
    config.peaks.loc[len(config.peaks)] = ["SF6", "H-003"]
    result = calculate(config, ["SF6"]).gases["SF6"]
    assert result.comparisons.empty and result.tanks.empty
