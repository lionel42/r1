import numpy as np
import pytest

from r1.io.config import read_exclude, read_fixed, read_r1tanks
from r1.io.export2 import read_export2, write_export2_file


def test_config(config, r1_dir):
    assert config.gases == ["CFC-12", "N2O"]
    assert config.paths.r1_standards_drift == r1_dir / "config" / "R1.standards.drift"
    assert config.r1_standards_path is None
    config.conf["R1-standards-path"] = "extra"
    assert config.r1_standards_path == r1_dir / "extra"


def test_fixed_uses_aliases(config):
    fixed = read_fixed(config.paths.standards_fixed, config.aliases)
    assert fixed.to_dict("records") == [
        {"tank": "G-001", "gas": "CFC-12", "value": 1.05}
    ]


def test_missing_files_raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_exclude(tmp_path / "none")
    with pytest.raises(FileNotFoundError):
        read_r1tanks(tmp_path / "none")


def test_r1tanks_optional_columns(config):
    tanks = read_r1tanks(config.paths.r1tanks)
    assert len(tanks) == 4
    assert tanks.set_index("tank").loc["E-004", "serial_no"] is np.nan


def test_read_export2(config):
    comparisons = read_export2(config.paths.export2_dir, "CFC-12", config.site_codes)
    assert len(comparisons) == 21
    jfj = comparisons[comparisons["instrument"] == "jfj-medusa"]
    assert set(jfj["site"]) == {"JFJ"}
    assert comparisons["gcwerks_flag"].eq("A").all()


def test_export2_zero_ratio_is_nan(tmp_path, config):
    ratios = dict(r_ht=0.0, pstdev_ht=0.1, n_ht=5, r_a=1.01, pstdev_a=0.1, n_a=5)
    path = write_export2_file(
        tmp_path, "sio-medusa", "N2O", "T_1", "S-1", "240101", ratios
    )
    assert path.name == "T-1_S-1_240101"
    comparisons = read_export2(tmp_path, "N2O", config.site_codes)
    assert np.isnan(comparisons.loc[0, "r_ht"])
    assert np.isnan(comparisons.loc[0, "pstdev_ht"])
    assert comparisons.loc[0, "r_a"] == pytest.approx(1.01)
