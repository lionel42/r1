import numpy as np
import pytest

from gcwerks.io.standards import read_standards
from r1.calc import calculate
from r1.io.outputs import read_plot_file, write_results


@pytest.fixture
def written(config):
    results = calculate(config)
    write_results(results, config.paths, config.gases)
    return config.paths


def test_files_written(written):
    for gas in ["CFC-12", "N2O"]:
        assert written.calc_file(gas).is_file()
        assert written.plot_file(gas).is_file()
    assert written.r1_standards.is_file()


def test_calc_file(written):
    text = written.calc_file("CFC-12").read_text()
    assert text.startswith("# CFC-12 (reftank H-001)")
    assert "#Tank E-003  Pass 3  (1 std skipped)" in text
    # tanks ordered by pass
    assert text.index("Tank J-101  Pass 1") < text.index("Tank E-001  Pass 2")


def test_plot_file_roundtrip(written):
    table = read_plot_file(written.plot_file("CFC-12"))
    assert len(table) == 20
    j101 = table[table["tank"] == "J-101"]
    assert j101["tank_mean"].iloc[0] == pytest.approx(1.0002, abs=1e-6)
    assert j101["tank_n"].iloc[0] == 5
    assert np.isnan(table.loc[table["std"] == "X-999", "R1ratio"]).all()


def test_r1_standards(written):
    values = read_standards(written.r1_standards)
    assert "E-007" not in values.index  # excluded
    assert values.loc["J-101", "N2O"] == pytest.approx(1.021)
    assert list(values.index) == sorted(values.index)


def test_start_tank(config):
    write_results(calculate(config), config.paths, config.gases, start_tank="G")
    values = read_standards(config.paths.r1_standards)
    assert values.index.min() >= "G"
