import pytest

from r1.cli.main import main


@pytest.fixture
def viewer(r1_dir, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    pytest.importorskip("matplotlib")
    from PySide6.QtWidgets import QApplication

    from r1.gui import R1Viewer

    app = QApplication.instance() or QApplication([])
    main(["-C", str(r1_dir), "calc"])
    window = R1Viewer(r1_dir, "CFC-12")
    yield window
    window.close()
    app.processEvents()


def test_switch_gas_and_select(viewer):
    assert viewer.current_gas() == "CFC-12"
    first_tank = sorted(viewer.table["tank"].unique())[0]
    assert set(viewer.selected_table()["tank"]) == {first_tank}

    viewer.reload()
    assert viewer.tank_box.currentText() == first_tank
    assert len(viewer.selected_table())

    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-001"))
    assert set(viewer.selected_table()["tank"]) == {"E-001"}

    viewer._step_gas(1)
    assert viewer.current_gas() != "CFC-12"
    assert viewer.tank_box.currentText() == "E-001"


def test_missing_plot_file(viewer, r1_dir):
    (r1_dir / "plot" / "plot.N2O").unlink()
    viewer.reload()
    viewer.gas_box.setCurrentIndex(viewer.config.gases.index("N2O"))
    assert viewer.table is None
    assert "run calc" in viewer.statusBar().currentMessage()


def test_gui_dir(r1_dir, tmp_path, monkeypatch):
    from r1.cli.gui import DEFAULT_DIR, gui_dir

    monkeypatch.chdir(tmp_path)
    assert gui_dir(tmp_path) == DEFAULT_DIR
    assert gui_dir(r1_dir) == r1_dir
    monkeypatch.chdir(r1_dir)
    assert gui_dir(r1_dir) == r1_dir


def test_find_gas(viewer):
    assert viewer.find_gas("n2o") == "N2O"
    assert viewer.find_gas("cfc") == "CFC-12"
    assert viewer.find_gas("xyz") is None

    viewer.gas_box.setEditText("n2")
    viewer._gas_typed()
    assert viewer.current_gas() == "N2O"
    assert viewer.table["tank"].notna().all()

    viewer.gas_box.setEditText("nothing")
    viewer._gas_typed()
    assert viewer.gas_box.currentText() == "N2O"


def _select(viewer, tank, std, date):
    table = viewer.comparisons
    for row in range(table.rowCount()):
        cells = [table.item(row, c).text() for c in (0, 1, 4)]
        if cells == [tank, std, date]:
            table.selectRow(row)
            return
    raise AssertionError(f"{tank}/{std} {date} not in the table")


def test_comparison_table(viewer):
    viewer.tank_box.setCurrentIndex(0)  # all tanks
    table = viewer.comparisons
    assert table.rowCount() == len(viewer.selected_table()) + viewer.selected_table()["tank"].nunique()
    assert any(table.item(row, 5).text() == "Mean =" for row in range(table.rowCount()))

    _select(viewer, "E-001", "J-101", "240901")
    assert viewer.flag_label.text() == "E-001_J-101_240901"
    assert "area is better here" in viewer.flag_text.toPlainText()
    assert len(viewer._highlight.get_xdata()) == 1

    # inverted comparison: the flag file keeps the export2 order
    _select(viewer, "E-007", "J-101", "240301")
    assert viewer.flag_label.text() == "J-101_E-007_240301"

    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-001"))
    assert viewer.selected_comparison() is None
    assert table.rowCount() == 4


def test_plot_follows_palette(viewer):
    from matplotlib.colors import to_hex
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette(QColor("#202020"))
    viewer.setPalette(palette)
    ax = viewer.figure.axes[0]
    assert to_hex(viewer.figure.get_facecolor()) == "#202020"
    assert ax.title.get_color() == palette.color(QPalette.WindowText).name()


def test_find_tank(viewer):
    viewer.tank_box.setEditText("e-005")
    viewer._tank_typed()
    assert set(viewer.selected_table()["tank"]) == {"E-005"}

    viewer.tank_box.setEditText("E-00")  # several tanks: keep E-005
    viewer._tank_typed()
    assert viewer.tank_box.currentText() == "E-005"

    viewer.tank_box.setEditText("")  # empty: all tanks
    viewer._tank_typed()
    assert viewer.tank_box.currentText() == "(all)"
    assert viewer.selected_table()["tank"].nunique() > 1


def _chain(item, depth=0):
    """The chain below ``item`` as (depth, tank, note) tuples."""
    rows = [(depth, item.text(0), item.text(4))]
    for i in range(item.childCount()):
        rows += _chain(item.child(i), depth + 1)
    return rows


def test_calibration_chain(viewer):
    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-004"))
    assert _chain(viewer.chain.topLevelItem(0)) == [
        (0, "E-004", ""),
        (1, "J-101", ""),
        (2, "H-001", "reference"),
    ]

    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-005"))
    assert _chain(viewer.chain.topLevelItem(0)) == [
        (0, "E-005", ""),
        (1, "G-001", "fixed"),
    ]

    # double-clicking a std selects it as the tank
    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-004"))
    j101 = viewer.chain.topLevelItem(0).child(0)
    viewer._chain_item_chosen(j101)
    assert viewer.tank_box.currentText() == "J-101"
    assert viewer.chain.topLevelItem(0).text(0) == "J-101"

    viewer.tank_box.setCurrentIndex(0)
    assert viewer.chain.topLevelItem(0).text(0) == "select a tank"


def _mouse(viewer, name, index, button=None, offset=(3, -2)):
    """Send a mouse event a few pixels from the point of comparison ``index``."""
    from matplotlib.backend_bases import MouseEvent
    from matplotlib.dates import date2num

    viewer.canvas.draw()
    row = viewer.shown.loc[index]
    ax = viewer._hover.axes
    x, y = ax.transData.transform((date2num(row["time"]), row["R1ratio"]))
    event = MouseEvent(name, viewer.canvas, x + offset[0], y + offset[1], button=button)
    viewer.canvas.callbacks.process(name, event)


def test_hover_and_click(viewer):
    viewer.tank_box.setCurrentIndex(0)  # all tanks
    shown = viewer.shown
    target = shown.index[(shown["tank"] == "E-005") & (shown["std"] == "G-001")][0]

    _mouse(viewer, "motion_notify_event", target)
    assert viewer._hover_index == target
    assert "E-005/G-001" in viewer.statusBar().currentMessage()
    assert "E-005/G-001" in viewer.toolbar.locLabel.text()

    _mouse(viewer, "button_press_event", target, button=1)
    selected = viewer.selected_comparison()
    assert (selected["tank"], selected["std"]) == ("E-005", "G-001")
    assert viewer.flag_label.text().endswith("no flag file")

    # no selection while the toolbar is zooming
    viewer.comparisons.clearSelection()
    viewer.toolbar.zoom()
    _mouse(viewer, "button_press_event", target, button=1)
    assert viewer.selected_comparison() is None
    viewer.toolbar.zoom()


def test_table_menu_open_tank(viewer):
    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-002"))
    table = viewer.comparisons
    assert viewer.table_menu_tanks(0, 0) == []  # Tank cell: already shown
    assert viewer.table_menu_tanks(0, 1) == ["E-001"]  # Std cell
    assert viewer.table_menu_tanks(0, 4) == ["E-001"]  # other cell

    viewer.tank_box.setCurrentIndex(0)  # all tanks: the tank is offered too
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == "E-002")
    assert viewer.table_menu_tanks(row, 4) == ["E-002", "E-001"]
    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-002"))
    mean_row = table.rowCount() - 1
    assert viewer.table_menu_tanks(mean_row, 0) == []

    assert viewer.open_tank("E-001")
    assert viewer.tank_box.currentText() == "E-001"
    assert not viewer.open_tank("H-001")  # reference: no comparisons
    assert viewer.tank_box.currentText() == "E-001"


def test_copy_row(viewer):
    from PySide6.QtWidgets import QApplication

    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-002"))
    viewer.comparisons.selectRow(0)
    viewer.copy_selected_row()
    cells = QApplication.clipboard().text().split("\t")
    assert cells[:2] == ["E-002", "E-001"]
    assert len(cells) == 9


def test_logo(viewer):
    from r1.gui import LOGO

    assert LOGO.is_file()
    assert not viewer.windowIcon().isNull()


def test_show_parents(viewer):
    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-002"))
    assert viewer.selected_table()["tank"].unique().tolist() == ["E-002"]

    viewer.show_parents.setChecked(True)
    # E-002 <- E-001 <- J-101 <- H-001 (reference, no comparisons of its own)
    assert viewer.selected_table()["tank"].unique().tolist() == ["E-002", "E-001", "J-101"]
    tanks_in_table = {viewer.comparisons.item(r, 0).text() for r in range(viewer.comparisons.rowCount())}
    assert tanks_in_table == {"E-002", "E-001", "J-101", ""}  # "" = mean rows

    # a fixed tank ends the chain
    viewer.tank_box.setCurrentIndex(viewer.tank_box.findText("E-005"))
    assert viewer.selected_table()["tank"].unique().tolist() == ["E-005"]

    viewer.tank_box.setCurrentIndex(0)
    assert not viewer.show_parents.isEnabled()


def test_run_calc_for_selected_gas(viewer, r1_dir):
    import time

    from PySide6.QtWidgets import QApplication

    plot_n2o = r1_dir / "plot" / "plot.N2O"
    standards = r1_dir / "results" / "R1.standards"
    before = {path: path.stat().st_mtime_ns for path in (plot_n2o, standards)}
    (r1_dir / "plot" / "plot.CFC-12").unlink()
    viewer.reload()
    assert viewer.table is None
    assert viewer.calc_button.text() == "Run calc CFC-12"

    stages = []
    viewer.run_calc()
    viewer.calc_worker.progress.connect(lambda stage, done, total: stages.append(stage))
    assert not viewer.calc_button.isEnabled()
    deadline = time.monotonic() + 30
    while viewer.calc_worker is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)

    assert viewer.calc_worker is None
    assert viewer.calc_button.isEnabled()
    assert not viewer.progress_bar.isVisible()
    assert viewer.table is not None  # plot.CFC-12 rewritten and reloaded
    assert viewer.current_gas() == "CFC-12"
    assert "write" in stages
    # only the selected gas is recalculated, R1.standards is left alone
    assert {path: path.stat().st_mtime_ns for path in before} == before


def test_right_click_opens_list(viewer):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    viewer.show()
    for box in (viewer.gas_box, viewer.tank_box):
        edit = box.lineEdit()
        QTest.mousePress(edit, Qt.RightButton, pos=QPoint(5, 5))
        assert not box.view().isVisible()  # not on the press...
        QTest.mouseRelease(edit, Qt.RightButton, pos=QPoint(5, 5))
        assert box.view().isVisible()  # ...but on the release, and it stays open
        box.hidePopup()
