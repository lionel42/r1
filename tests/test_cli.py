import pytest

from r1.cli.main import main


def test_calc_and_diff(r1_dir, capsys):
    main(["-C", str(r1_dir), "calc", "--sort"])
    assert (r1_dir / "results" / "R1.standards").is_file()

    standards = r1_dir / "results" / "R1.standards"
    main(["-C", str(r1_dir), "diff", str(standards), str(standards)])
    assert capsys.readouterr().out == "no differences\n"


def test_calc_single_gas_keeps_standards(r1_dir):
    main(["-C", str(r1_dir), "calc", "--gas", "n2o"])
    assert (r1_dir / "calc" / "calc.N2O").is_file()
    assert not (r1_dir / "results" / "R1.standards").exists()


def test_drift_update(r1_dir):
    main(["-C", str(r1_dir), "calc"])
    main(["-C", str(r1_dir), "drift-update"])
    assert (r1_dir / "drift" / "standards.drift").is_file()


def test_plot(r1_dir):
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    main(["-C", str(r1_dir), "calc"])
    main(["-C", str(r1_dir), "plot", "--gas", "CFC-12", "--site", "JFJ"])
    assert (r1_dir / "plot" / "CFC-12.png").is_file()


def test_options_after_command(r1_dir):
    main(["calc", "--gas", "N2O", "-C", str(r1_dir), "-v"])
    assert (r1_dir / "calc" / "calc.N2O").is_file()


def test_relative_dir_and_output(r1_dir, monkeypatch, tmp_path):
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    monkeypatch.chdir(tmp_path)
    main(["calc", "-C", "medusa"])
    main(["plot", "-C", "medusa", "--gas", "N2O", "-o", "n2o.png"])
    assert (tmp_path / "n2o.png").is_file()  # relative to the current directory
