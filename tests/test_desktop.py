import configparser

from r1 import desktop
from r1.cli.main import main


def test_install_and_uninstall(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    main(["gui", "--install-desktop"])
    assert "wrote" in capsys.readouterr().out

    entry = configparser.ConfigParser(interpolation=None)
    entry.read(tmp_path / "applications" / "r1.desktop")
    section = entry["Desktop Entry"]
    assert section["Name"] == "R1"
    assert section["Exec"].endswith("-m r1 gui")
    assert section["Icon"] == desktop.APP_ID
    icon = tmp_path / "icons" / "hicolor" / "scalable" / "apps" / "r1.svg"
    assert icon.read_bytes() == desktop.LOGO.read_bytes()

    main(["gui", "--uninstall-desktop"])
    assert not icon.exists()
    assert not (tmp_path / "applications" / "r1.desktop").exists()


def test_install_removes_old_name(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    old = tmp_path / "applications" / "r1-viewer.desktop"
    old.parent.mkdir(parents=True)
    old.write_text("[Desktop Entry]\nName=R1 viewer\n")
    desktop.install_desktop_entry()
    assert not old.exists()
    assert (tmp_path / "applications" / "r1.desktop").exists()
