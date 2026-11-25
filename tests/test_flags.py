import pandas as pd

from r1 import flags as fl


def lines(*rows):
    return pd.DataFrame(rows, columns=["gas", "flag"])


def test_combine_flags():
    assert fl.combine_flags(lines(("CFC-12", "F"), ("all", "H")), "CFC-12") == "F-H-"
    assert fl.combine_flags(lines(("N2O", "F")), "CFC-12") == "----"
    assert fl.combine_flags(lines(("cfc-12", "L")), "CFC-12") == "---L"


def test_unset_wins_in_any_order():
    assert fl.combine_flags(lines(("all", "H"), ("CFC-12", "UH")), "CFC-12") == "----"
    assert (
        fl.combine_flags(lines(("CFC-12", "UF"), ("CFC-12", "F")), "CFC-12") == "----"
    )


def test_set_position():
    flags = pd.Series(["----", "-I--"])
    result = fl.set_position(flags, pd.Series([False, True]), 0, "x")
    assert list(result) == ["----", "xI--"]


def test_default_file_per_year(tmp_path):
    (tmp_path / "default_sio-medusa").write_text("all H\n")
    assert (
        fl.default_flag_file(tmp_path, "sio-medusa", "240101").name
        == "default_sio-medusa"
    )
    (tmp_path / "default_sio-medusa_24").write_text("all F\n")
    assert (
        fl.default_flag_file(tmp_path, "sio-medusa", "240101").name
        == "default_sio-medusa_24"
    )
    assert (
        fl.default_flag_file(tmp_path, "sio-medusa", "230101").name
        == "default_sio-medusa"
    )


def test_read_comparison_flags(config):
    comparisons = pd.DataFrame(
        {
            "instrument": ["jfj-medusa", "jfj-medusa", "sio-medusa", "sio-medusa"],
            "tank": ["E-001", "E-002", "E-004", "J-101"],
            "std": ["J-101", "E-001", "J-101", "E-007"],
            "date": ["240901", "240915", "240301", "240301"],
        }
    )
    flags = fl.read_comparison_flags(
        comparisons, config.paths.flags_dir, "CFC-12", config.aliases
    )
    # UH unsets the default H, alias CFC12 sets F, I flag
    assert list(flags) == ["----", "--H-", "F---", "-I--"]


def test_missing_default_flag_file_is_skipped(config):
    (config.paths.flags_dir / "default_sio-medusa").unlink()
    comparisons = pd.DataFrame(
        {
            "instrument": ["sio-medusa"],
            "tank": ["E-004"],
            "std": ["J-101"],
            "date": ["240301"],
        }
    )
    flags = fl.read_comparison_flags(comparisons, config.paths.flags_dir, "CFC-12")
    assert list(flags) == ["----"]
