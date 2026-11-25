"""Qt viewer of the R1 plots: pick a gas and a tank.

Reads ``plot/plot.<gas>`` (written by ``r1 calc``), draws it with
:func:`r1.plot.draw_comparisons` and lists the comparisons in a table.
Selecting a row circles its point and shows its flag file. In the plot,
the point nearest the mouse is marked, and clicking selects it in the table. The calibration
chain shows the stds the selected tank was calculated from, back to the
reference tank; double-click one to select it. Needs PySide6 and matplotlib:
``pip install 'r1[gui]'``.

PageUp/PageDown switch to the previous/next gas from anywhere in the window.
The plot follows the light or dark theme of the window.
"""

import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from PySide6.QtCore import QEvent, QObject, QThread, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPalette,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from matplotlib.colors import to_rgba
from matplotlib.dates import DateFormatter, date2num
from matplotlib.figure import Figure

from gcwerks.standards import Standards
from r1.calc import STAGES, calculate
from r1.desktop import APP_ID, APP_NAME, LOGO
from r1.flags import comparison_flag_file
from r1.io.config import R1Config, read_fixed
from r1.io.outputs import read_plot_file, write_results
from r1.plot import _visible_flags, draw_comparisons
from r1.select import parent_tanks, select_comparisons, used_stds

logger = logging.getLogger(__name__)

ALL = "(all)"
TABLE_COLUMNS = ["Tank", "Std", "Flags", "Site", "Date", "R1std", "R1ratio", "%s", "N"]
ROW_ROLE = Qt.UserRole
CHAIN_COLUMNS = ["Tank", "R1", "N", "Dates", ""]
TANK_ROLE = Qt.UserRole
PENDING = "pending"  # placeholder child of a chain item not expanded yet
AUTO_EXPAND_ITEMS = 200


def plot_rc(palette: QPalette) -> dict[str, str]:
    """Matplotlib rc parameters matching the colors of the Qt ``palette``."""
    window = palette.color(QPalette.Window).name()
    base = palette.color(QPalette.Base).name()
    text = palette.color(QPalette.WindowText).name()
    grid = palette.color(QPalette.Mid).name()
    return {
        "figure.facecolor": window,
        "figure.edgecolor": window,
        "axes.facecolor": base,
        "axes.edgecolor": text,
        "axes.labelcolor": text,
        "axes.titlecolor": text,
        "xtick.color": text,
        "ytick.color": text,
        "text.color": text,
        "grid.color": grid,
        "legend.facecolor": base,
        "legend.edgecolor": grid,
        "legend.labelcolor": text,
    }


class R1Viewer(QMainWindow):
    """Main window: controls on the left, the plot on the right."""

    def __init__(self, gcdir: Path | None = None, gas: str | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(LOGO)))
        self.resize(1400, 850)

        self.config: R1Config | None = None
        self.standards: Standards | None = None
        self.fixed: pd.DataFrame | None = None
        self.table: pd.DataFrame | None = None
        self.shown: pd.DataFrame | None = None
        self._highlight = None
        self._hover = None
        self._hover_index = None
        self._summary = ""

        self._build_widgets()
        if gcdir is not None:
            self.open_dir(Path(gcdir), gas)

    # --- layout -----------------------------------------------------------

    def _build_widgets(self) -> None:
        self.dir_label = QLabel("no R1 directory")
        self.dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_button = QPushButton("Open…")
        open_button.clicked.connect(self._choose_dir)
        reload_button = QPushButton("Reload")
        reload_button.setToolTip("Re-read the config and plot files")
        reload_button.clicked.connect(self.reload)
        self.calc_button = QPushButton("Run calc")
        self.calc_button.setToolTip(
            "Recalculate the selected gas (r1 calc --gas) and reload.\n"
            "results/R1.standards is not rewritten: use r1 calc for all gases."
        )
        self.calc_button.clicked.connect(self.run_calc)
        self.dir_buttons = [open_button, reload_button, self.calc_button]

        top = QHBoxLayout()
        top.addWidget(self.dir_label, 1)
        for button in self.dir_buttons:
            top.addWidget(button)

        self.progress_label = QLabel()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(250)
        for widget in (self.progress_label, self.progress_bar):
            self.statusBar().addPermanentWidget(widget)
            widget.hide()
        self.calc_worker: CalcWorker | None = None

        self.gas_box = searchable_box()
        self.gas_box.currentIndexChanged.connect(self._gas_changed)
        self.gas_box.lineEdit().editingFinished.connect(self._gas_typed)

        self.tank_box = searchable_box()
        self.tank_box.currentIndexChanged.connect(lambda _: self.redraw())
        self.tank_box.lineEdit().editingFinished.connect(self._tank_typed)

        form = QFormLayout()
        form.addRow("Gas", self.gas_box)
        form.addRow("Tank", self.tank_box)
        self.show_parents = QCheckBox("Show parents")
        self.show_parents.setToolTip(
            "Also show the tanks of the calibration chain of the selected tank"
        )
        self.show_parents.toggled.connect(self.redraw)
        form.addRow("", self.show_parents)

        self.comparisons = QTableWidget(0, len(TABLE_COLUMNS))
        self.comparisons.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.comparisons.verticalHeader().hide()
        self.comparisons.verticalHeader().setDefaultSectionSize(
            self.comparisons.fontMetrics().height() + 6
        )
        self.comparisons.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.comparisons.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.comparisons.setSelectionMode(QAbstractItemView.SingleSelection)
        self.comparisons.itemSelectionChanged.connect(self._comparison_selected)
        self.comparisons.setContextMenuPolicy(Qt.CustomContextMenu)
        self.comparisons.customContextMenuRequested.connect(self._table_menu)
        copy = QShortcut(QKeySequence.Copy, self.comparisons, self.copy_selected_row)
        copy.setContext(Qt.WidgetShortcut)

        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.flag_label = QLabel()
        self.flag_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.flag_text = QPlainTextEdit()
        self.flag_text.setReadOnly(True)
        self.flag_text.setFont(fixed_font)
        flag_panel = QWidget()
        flag_layout = QVBoxLayout(flag_panel)
        flag_layout.setContentsMargins(0, 0, 0, 0)
        flag_layout.addWidget(self.flag_label)
        flag_layout.addWidget(self.flag_text, 1)

        self.chain = QTreeWidget()
        self.chain.setHeaderLabels(CHAIN_COLUMNS)
        self.chain.setToolTip(
            "Stds the tank was calculated from, back to the reference tank.\n"
            "N: comparisons used. Double-click a tank to select it."
        )
        self.chain.itemExpanded.connect(self._expand_chain_item)
        self.chain.itemDoubleClicked.connect(self._chain_item_chosen)
        chain_panel = QWidget()
        chain_layout = QVBoxLayout(chain_panel)
        chain_layout.setContentsMargins(0, 0, 0, 0)
        chain_layout.addWidget(QLabel("Calibration chain"))
        chain_layout.addWidget(self.chain, 1)

        lists = QSplitter(Qt.Vertical)
        lists.addWidget(self.comparisons)
        lists.addWidget(chain_panel)
        lists.addWidget(flag_panel)
        lists.setStretchFactor(0, 1)
        lists.setSizes([400, 220, 120])

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(form)
        left_layout.addWidget(lists, 1)

        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas, 1)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("figure_leave_event", lambda _: self._set_hover(None))
        self.canvas.mpl_connect("button_press_event", self._on_click)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 840])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

        QShortcut(QKeySequence(Qt.Key_PageUp), self, lambda: self._step_gas(-1))
        QShortcut(QKeySequence(Qt.Key_PageDown), self, lambda: self._step_gas(1))

    # --- loading ----------------------------------------------------------

    def _choose_dir(self) -> None:
        start = str(self.config.paths.root) if self.config else str(Path.cwd())
        path = QFileDialog.getExistingDirectory(self, "R1 directory", start)
        if path:
            self.open_dir(Path(path))

    def open_dir(self, gcdir: Path, gas: str | None = None) -> None:
        """Load the R1 directory ``gcdir`` and show ``gas`` (default: the first)."""
        try:
            config = R1Config.from_dir(gcdir)
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Cannot read {gcdir}:\n{error}")
            return
        if self.config is None or config.paths.root != self.config.paths.root:
            # new directory: no tank chosen yet, so the first tank is shown
            self.tank_box.blockSignals(True)
            self.tank_box.clear()
            self.tank_box.blockSignals(False)
        self.config = config
        self.dir_label.setText(str(gcdir))
        self._load_standards()

        self.gas_box.blockSignals(True)
        self.gas_box.clear()
        self.gas_box.addItems(config.gases)
        self.gas_box.setCurrentIndex(-1)
        self.gas_box.blockSignals(False)
        gas = config.resolve_gas(gas) if gas else None
        row = config.gases.index(gas) if gas in config.gases else 0
        self.gas_box.setCurrentIndex(row)

    def _load_standards(self) -> None:
        paths = self.config.paths
        try:
            self.standards = Standards.from_files(
                paths.standards,
                [paths.standards_drift, paths.r1_standards_drift],
                self.config.aliases,
            )
        except Exception as error:
            logger.warning(f"no drift curves: {error}")
            self.standards = None
        try:
            self.fixed = read_fixed(paths.standards_fixed, self.config.aliases)
        except Exception as error:
            logger.warning(f"no fixed tanks: {error}")
            self.fixed = None

    def reload(self) -> None:
        """Re-read the R1 directory, keeping the current gas and selection."""
        if self.config is not None:
            self.open_dir(self.config.paths.root, self.current_gas())

    def run_calc(self) -> None:
        """Recalculate the selected gas in the background, then reload.

        The progress bar in the status bar shows the stage and how far it is.
        """
        gas = self.current_gas()
        if self.config is None or not gas or self.calc_worker is not None:
            return
        for button in self.dir_buttons:
            button.setEnabled(False)
        self._show_progress(gas, "read", 0, 1)
        self.progress_label.show()
        self.progress_bar.show()

        worker = CalcWorker(self.config, gas, self)
        worker.progress.connect(lambda stage, done, total: self._show_progress(gas, stage, done, total))
        worker.succeeded.connect(lambda: self._calc_finished(gas, None))
        worker.failed.connect(lambda error: self._calc_finished(gas, error))
        self.calc_worker = worker
        worker.start()

    def _show_progress(self, gas: str, stage: str, done: int, total: int) -> None:
        start, end = CALC_STAGE_SPANS[stage]
        fraction = done / total if total else 1
        self.progress_bar.setValue(round(1000 * (start + (end - start) * fraction)))
        text = CALC_STAGE_TEXTS[stage]
        self.progress_label.setText(f"calc {gas}: {text} {done}/{total}" if total > 1 else f"calc {gas}: {text}")

    def _calc_finished(self, gas: str, error: str | None) -> None:
        self.calc_worker.wait()
        self.calc_worker = None
        self.progress_label.hide()
        self.progress_bar.hide()
        for button in self.dir_buttons:
            button.setEnabled(True)
        if error is not None:
            QMessageBox.critical(self, APP_NAME, f"calc {gas} failed:\n{error}")
            return
        self.statusBar().showMessage(f"calc {gas} done", 5000)
        self.reload()

    def closeEvent(self, event) -> None:
        """Let a running calc finish writing its files before closing."""
        if self.calc_worker is not None:
            self.calc_worker.wait()
        super().closeEvent(event)

    # --- gas and selection --------------------------------------------------

    def _step_gas(self, step: int) -> None:
        count = self.gas_box.count()
        if count:
            self.gas_box.setCurrentIndex((self.gas_box.currentIndex() + step) % count)

    def current_gas(self) -> str:
        """The selected gas (not the text being typed in the gas box)."""
        return self.gas_box.itemText(self.gas_box.currentIndex())

    def find_gas(self, text: str) -> str | None:
        """Return the gas matching ``text``: its name or an alias (any case),
        else the only gas containing ``text``."""
        text = text.strip()
        if not text or self.config is None:
            return None
        return find_item(self.config.gases, self.config.resolve_gas(text))

    def _gas_typed(self) -> None:
        """Select the gas typed in the gas box, or restore the selected one."""
        gas = self.find_gas(self.gas_box.currentText())
        if gas is not None and gas != self.current_gas():
            self.gas_box.setCurrentIndex(self.config.gases.index(gas))
        self.gas_box.setEditText(self.current_gas())

    def _tank_typed(self) -> None:
        """Select the tank typed in the tank box (none: all tanks), or restore
        the selected one."""
        text = self.tank_box.currentText().strip()
        tanks = [self.tank_box.itemText(i) for i in range(1, self.tank_box.count())]
        tank = find_item(tanks, text) if text else ALL
        if tank is not None:
            self.tank_box.setCurrentIndex(self.tank_box.findText(tank))
        self.tank_box.setEditText(self.tank_box.itemText(self.tank_box.currentIndex()))

    def _gas_changed(self, index: int) -> None:
        gas = self.gas_box.itemText(index)
        if not gas:
            return
        self.calc_button.setText(f"Run calc {gas}")
        path = self.config.paths.plot_file(gas)
        try:
            self.table = read_plot_file(path)
        except FileNotFoundError:
            self.table = None
        tanks = sorted(self.table["tank"].unique()) if self.table is not None else []
        self._set_items(self.tank_box, tanks)
        self.redraw()

    @staticmethod
    def _set_items(box: QComboBox, items: list[str]) -> None:
        """Fill ``box`` with ``(all)`` and ``items``, keeping the current choice.

        With no choice yet (empty box), the first item is chosen; if the
        current choice is not in ``items``, ``(all)``.
        """
        current = box.itemText(box.currentIndex())
        if current in items:
            index = items.index(current) + 1
        else:
            index = 1 if not current and items else 0
        box.blockSignals(True)
        box.clear()
        box.addItems([ALL, *items])
        box.setCurrentIndex(index)
        box.blockSignals(False)

    @staticmethod
    def _choice(box: QComboBox) -> str | None:
        text = box.itemText(box.currentIndex())
        return None if text in ("", ALL) else text

    def selected_table(self) -> pd.DataFrame:
        """The rows of the current gas matching the selection: the selected
        tank, then its parents nearest first if "Show parents" is checked."""
        tank = self._choice(self.tank_box)
        if tank is None or not self.show_parents.isChecked():
            return select_comparisons(self.table, tank)
        tanks = [tank, *parent_tanks(self.table, tank, self.chain_stops())]
        rows = self.table[self.table["tank"].isin(tanks)]
        order = pd.Categorical(rows["tank"], categories=tanks).codes
        return rows.iloc[np.argsort(order, kind="stable")]

    def chain_stops(self) -> set[str]:
        """Tanks that end a calibration chain: the reference and fixed tanks."""
        gas = self.current_gas()
        stops = {self.config.reference_tank(gas)}
        if self.fixed is not None:
            stops |= set(self.fixed.loc[self.fixed["gas"] == gas, "tank"])
        return stops

    # --- drawing ----------------------------------------------------------

    def changeEvent(self, event: QEvent) -> None:
        """Redraw when the light/dark theme (hence the palette) changes."""
        super().changeEvent(event)
        if event.type() in (QEvent.PaletteChange, QEvent.ThemeChange) and hasattr(
            self, "figure"
        ):
            self.redraw()

    def redraw(self) -> None:
        """Draw the current gas with the current selection, in the window colors."""
        rc = plot_rc(self.palette())
        self.figure.set_facecolor(rc["figure.facecolor"])
        self.figure.set_edgecolor(rc["figure.edgecolor"])
        with matplotlib.rc_context(rc):
            self._draw()
        self.canvas.draw_idle()

    def _draw(self) -> None:
        gas = self.current_gas()
        if self.config is None or not gas:
            return
        self.figure.clear()
        ax = self.figure.add_subplot()
        self._highlight = self._hover = self._hover_index = None
        self.show_parents.setEnabled(self._choice(self.tank_box) is not None)

        if self.table is None:
            message = f"no {self.config.paths.plot_file(gas).name}: run calc"
            ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
            ax.set_title(gas)
            self.statusBar().showMessage(message)
            self._fill_table(None)
            self._fill_chain()
        else:
            table = self.selected_table()
            draw_comparisons(ax, table, gas, self.standards)
            ax.set_title(gas)
            for label in ax.get_xticklabels():
                label.set_rotation(30)
                label.set_horizontalalignment("right")
            text_color = matplotlib.rcParams["text.color"]
            (self._highlight,) = ax.plot(
                [], [], "o", ms=14, mfc="none", mec=text_color, mew=1.5, zorder=5
            )
            (self._hover,) = ax.plot(
                [], [], "o", ms=12, color=text_color, alpha=0.3, zorder=4
            )
            ax.fmt_xdata = DateFormatter("%Y-%m-%d")
            ax.format_coord = self._coordinate_text(ax.format_coord)
            self._fill_table(table)
            self._fill_chain()
            self._summary = (
                f"{gas}: {len(table)} comparisons, {table['tank'].nunique()} tanks "
                f"(reference {self.config.reference_tank(gas)})"
            )
            self.statusBar().showMessage(self._summary)

    # --- mouse on the plot ------------------------------------------------

    def nearest_comparison(self, x: float, y: float):
        """Index (in :attr:`shown`) of the visible point nearest the pixel
        ``(x, y)`` of the canvas, or None."""
        if self.shown is None or self._hover is None:
            return None
        ax = self._hover.axes
        points = self.shown[np.isfinite(self.shown["R1ratio"])]
        if points.empty:
            return None
        xy = np.column_stack([date2num(points["time"]), points["R1ratio"]])
        pixels = ax.transData.transform(xy)
        x0, y0, x1, y1 = ax.bbox.extents
        visible = (
            (pixels[:, 0] >= x0) & (pixels[:, 0] <= x1)
            & (pixels[:, 1] >= y0) & (pixels[:, 1] <= y1)
        )
        if not visible.any():
            return None
        distance = np.hypot(pixels[:, 0] - x, pixels[:, 1] - y)
        distance[~visible] = np.inf
        return points.index[np.argmin(distance)]

    def _point_under_mouse(self, event):
        """The comparison nearest the mouse, or None when the mouse is out of
        the plot or the toolbar is zooming or panning."""
        if self._hover is None or event.inaxes is not self._hover.axes or self.toolbar.mode:
            return None
        return self.nearest_comparison(event.x, event.y)

    def _on_mouse_move(self, event) -> None:
        self._set_hover(self._point_under_mouse(event))

    def _set_hover(self, index) -> None:
        """Mark the comparison ``index`` (None: none) as hovered."""
        if self._hover is None or index == self._hover_index:
            return
        self._hover_index = index
        if index is None:
            self._hover.set_data([], [])
            self.statusBar().showMessage(self._summary)
        else:
            row = self.shown.loc[index]
            self._hover.set_data([row["time"]], [row["R1ratio"]])
            self.statusBar().showMessage(f"{_comparison_label(row)}  (click to select)")
        self.canvas.draw_idle()

    def _coordinate_text(self, format_coord):
        """Wrap the ``format_coord`` of the axes (the x/y text of the toolbar)
        to add the comparison nearest the mouse."""

        def text(x: float, y: float) -> str:
            coordinates = format_coord(x, y)
            ax = self._hover.axes if self._hover is not None else None
            if ax is None or self.toolbar.mode:
                return coordinates
            index = self.nearest_comparison(*ax.transData.transform((x, y)))
            if index is None:
                return coordinates
            return f"{coordinates}\n{_comparison_label(self.shown.loc[index])}"

        return text

    def _on_click(self, event) -> None:
        """Select the comparison nearest a left click in the table."""
        if event.button != 1:
            return
        index = self._point_under_mouse(event)
        if index is not None:
            self.select_comparison(index)

    def select_comparison(self, index) -> None:
        """Select the row of the comparison ``index`` in the table."""
        for row in range(self.comparisons.rowCount()):
            item = self.comparisons.item(row, 0)
            if item.data(ROW_ROLE) == index:
                self.comparisons.selectRow(row)
                self.comparisons.scrollToItem(item)
                return

    # --- comparison table -------------------------------------------------

    def _fill_table(self, table: pd.DataFrame | None) -> None:
        """List the comparisons of ``table``, with a mean row after each tank.

        The tanks come in plot order and the tank names in the plot colors.
        """
        self.shown = table
        self.comparisons.setRowCount(0)
        self._comparison_selected()
        if table is None:
            return
        colors = _prop_colors()
        for i, tank in enumerate(table["tank"].unique()):
            color = QColor.fromRgbF(*to_rgba(colors[i % len(colors)]))
            rows = table[table["tank"] == tank].sort_values("date")
            for index, row in rows.iterrows():
                self._add_row(_comparison_cells(row), index, color)
            self._add_row(_mean_cells(rows.iloc[0]), None, color)
        self.comparisons.resizeColumnsToContents()

    def _add_row(self, cells: list[str], index, color: QColor) -> None:
        row = self.comparisons.rowCount()
        self.comparisons.insertRow(row)
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if column >= TABLE_COLUMNS.index("R1std"):
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if index is None:
                item.setFlags(Qt.ItemIsEnabled)
                font = QFont()
                font.setItalic(True)
                item.setFont(font)
            else:
                item.setData(ROW_ROLE, index)
            if column == 0:
                item.setForeground(QBrush(color))
            self.comparisons.setItem(row, column, item)

    def selected_comparison(self) -> pd.Series | None:
        """The comparison selected in the table, or None."""
        items = self.comparisons.selectedItems()
        if not items or self.shown is None:
            return None
        index = items[0].data(ROW_ROLE)
        return None if index is None else self.shown.loc[index]

    def _comparison_selected(self) -> None:
        row = self.selected_comparison()
        if self._highlight is not None:
            if row is None or not np.isfinite(row["R1ratio"]):
                self._highlight.set_data([], [])
            else:
                self._highlight.set_data([row["time"]], [row["R1ratio"]])
            self.canvas.draw_idle()

        if row is None:
            self.flag_label.setText("")
            self.flag_text.setPlainText("")
            return
        path = self.flag_file(row)
        if path is None:
            name = f"{row['tank']}_{row['std']}_{row['date']}"
            self.flag_label.setText(f"{name}: no flag file")
            self.flag_text.setPlainText("")
        else:
            self.flag_label.setText(path.name)
            self.flag_text.setPlainText(path.read_text())

    def flag_file(self, row: pd.Series) -> Path | None:
        """The flag file of a comparison, or None. It is named after the
        export2 file, so tank and std are swapped for inverted comparisons."""
        flags_dir = self.config.paths.flags_dir
        for tank, std in [(row["tank"], row["std"]), (row["std"], row["tank"])]:
            path = comparison_flag_file(flags_dir, tank, std, row["date"])
            if path.is_file():
                return path
        return None


    # --- calibration chain ------------------------------------------------

    def _fill_chain(self) -> None:
        """Show the chain of the selected tank, expanded up to
        :data:`AUTO_EXPAND_ITEMS` items (deeper levels open on demand)."""
        self.chain.clear()
        tank = self._choice(self.tank_box)
        if self.table is None or tank is None:
            item = QTreeWidgetItem(["select a tank"])
            item.setFlags(Qt.ItemIsEnabled)
            self.chain.addTopLevelItem(item)
            return
        rows = self.table[self.table["tank"] == tank]
        value = rows["tank_mean"].iloc[0] if len(rows) else np.nan
        root = self._chain_item(tank, [tank, _number(value, ".5f"), "", ""])
        self.chain.addTopLevelItem(root)

        queue, count = [root], 1
        while queue and count < AUTO_EXPAND_ITEMS:
            item = queue.pop(0)
            item.setExpanded(True)  # adds its children
            count += item.childCount()
            queue.extend(item.child(i) for i in range(item.childCount()))
        for column in range(len(CHAIN_COLUMNS)):
            self.chain.resizeColumnToContents(column)

    def tank_origin(self, tank: str) -> str | None:
        """Why ``tank`` ends a chain, or None if it was calculated from stds."""
        gas = self.current_gas()
        if tank == self.config.reference_tank(gas):
            return "reference"
        fixed = self.fixed
        if fixed is not None and ((fixed["tank"] == tank) & (fixed["gas"] == gas)).any():
            return "fixed"
        if not (self.table["tank"] == tank).any():
            return "known value"
        if used_stds(self.table, tank).empty:
            return "no used comparison"
        return None

    def _chain_item(self, tank: str, cells: list[str]) -> QTreeWidgetItem:
        """An item for ``tank``, with a placeholder child if it has parents."""
        origin = self.tank_origin(tank)
        notes = [origin] if origin else []
        if self.standards is not None and not self.standards.drift_curve(
            tank, self.current_gas()
        ).empty:
            notes.append("drift")
        item = QTreeWidgetItem([*cells, ", ".join(notes)])
        item.setData(0, TANK_ROLE, tank)
        for column in (1, 2):
            item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
        if origin is None:
            item.addChild(QTreeWidgetItem([PENDING]))
        return item

    def _expand_chain_item(self, item: QTreeWidgetItem) -> None:
        """Add the stds of the tank of ``item`` when it is first expanded."""
        if item.childCount() != 1 or item.child(0).text(0) != PENDING:
            return
        item.takeChild(0)
        ancestors, parent = set(), item.parent()
        while parent is not None:
            ancestors.add(parent.data(0, TANK_ROLE))
            parent = parent.parent()

        for std in used_stds(self.table, item.data(0, TANK_ROLE)).itertuples():
            cells = [
                std.std,
                _number(std.R1std, ".5f"),
                str(std.n),
                std.first if std.first == std.last else f"{std.first}–{std.last}",
            ]
            if std.std in ancestors or std.std == item.data(0, TANK_ROLE):
                child = QTreeWidgetItem([*cells, "loop"])
            else:
                child = self._chain_item(std.std, cells)
            item.addChild(child)

    def _chain_item_chosen(self, item: QTreeWidgetItem) -> None:
        """Select the tank of a double-clicked chain item, if it has comparisons."""
        self.open_tank(item.data(0, TANK_ROLE) or "")

    def open_tank(self, tank: str) -> bool:
        """Select ``tank`` in the tank box; False if it has no comparisons."""
        index = self.tank_box.findText(tank)
        if index <= 0:
            return False
        self.tank_box.setCurrentIndex(index)
        return True

    def table_menu_tanks(self, row: int, column: int) -> list[str]:
        """The tanks offered by the right-click menu on a table cell: the
        name in a Tank or Std cell, else the tank and std of the row."""
        tank_column, std_column = TABLE_COLUMNS.index("Tank"), TABLE_COLUMNS.index("Std")
        columns = [column] if column in (tank_column, std_column) else [tank_column, std_column]
        names = [self.comparisons.item(row, c).text() for c in columns]
        current = self._choice(self.tank_box)
        return [name for name in dict.fromkeys(names) if name and name != current]

    def row_text(self, row: int) -> str:
        """The cells of a table row, tab-separated (pastes as columns)."""
        cells = [self.comparisons.item(row, c).text() for c in range(len(TABLE_COLUMNS))]
        return "\t".join(cells)

    def copy_selected_row(self) -> None:
        """Copy the selected comparison to the clipboard."""
        rows = {index.row() for index in self.comparisons.selectedIndexes()}
        if rows:
            QApplication.clipboard().setText(self.row_text(min(rows)))

    def _table_menu(self, position) -> None:
        item = self.comparisons.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        for tank in self.table_menu_tanks(item.row(), item.column()):
            action = menu.addAction(f"Open tank {tank}")
            if self.tank_box.findText(tank) <= 0:
                action.setEnabled(False)
                action.setText(f"Open tank {tank} (no comparisons)")
            action.triggered.connect(lambda _=False, tank=tank: self.open_tank(tank))
        if not menu.isEmpty():
            menu.addSeparator()

        clipboard = QApplication.clipboard()
        text, row = item.text(), item.row()
        if text:
            short = text if len(text) <= 20 else text[:19] + "…"
            menu.addAction(f'Copy "{short}"', lambda: clipboard.setText(text))
        menu.addAction("Copy row", lambda: clipboard.setText(self.row_text(row)))
        menu.exec(self.comparisons.viewport().mapToGlobal(position))


# share of the progress bar of each calc stage, and its text
CALC_STAGE_SPANS = {
    "read": (0.0, 0.45),
    "flags": (0.45, 0.65),
    "propagate": (0.65, 0.95),
    "write": (0.95, 1.0),
}
CALC_STAGE_TEXTS = {**STAGES, "write": "writing files"}


class CalcWorker(QThread):
    """Runs ``r1 calc --gas <gas>`` in the background.

    :attr:`progress` is emitted at most every 50 ms per stage, so a gas
    with many files doesn't flood the window with updates.
    """

    progress = Signal(str, int, int)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, config: R1Config, gas: str, parent=None):
        super().__init__(parent)
        self.config, self.gas = config, gas
        self._last = ("", 0.0)

    def _report(self, stage: str, done: int, total: int) -> None:
        now = time.monotonic()
        if stage != self._last[0] or done >= total or now - self._last[1] > 0.05:
            self._last = (stage, now)
            self.progress.emit(stage, done, total)

    def run(self) -> None:
        try:
            results = calculate(self.config, [self.gas], progress=self._report)
            self.progress.emit("write", 0, 1)
            write_results(
                results, self.config.paths, self.config.gases, write_standards_file=False
            )
            self.progress.emit("write", 1, 1)
        except Exception as error:
            logger.exception(f"calc {self.gas} failed")
            self.failed.emit(str(error))
        else:
            self.succeeded.emit()


def searchable_box() -> QComboBox:
    """A combobox whose items can be searched by typing part of their name.
    Right-clicking it opens its list."""
    box = QComboBox()
    box.setMaxVisibleItems(30)
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.NoInsert)
    box.lineEdit().setPlaceholderText("type to search")
    completer = box.completer()
    completer.setFilterMode(Qt.MatchContains)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    # right-click opens the list instead of the Cut/Copy/Paste menu
    opener = RightClickOpensList(box)
    for widget in (box, box.lineEdit()):
        widget.installEventFilter(opener)
    return box


class RightClickOpensList(QObject):
    """Event filter opening the list of a combobox on right-click.

    The list opens on the release of the button: opened on the press, the
    release would land on the list and close it again.
    """

    def __init__(self, box: QComboBox):
        super().__init__(box)
        self.box = box

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            return event.button() == Qt.RightButton
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.RightButton:
            self.box.showPopup()
            return True
        if kind == QEvent.ContextMenu:
            if event.reason() != QContextMenuEvent.Mouse:  # e.g. the Menu key
                self.box.showPopup()
            return True
        return False


def find_item(items: list[str], text: str) -> str | None:
    """Return the item named ``text`` (any case), else the only item
    containing ``text``, else None."""
    text = text.strip().lower()
    for item in items:
        if item.lower() == text:
            return item
    matches = [item for item in items if text in item.lower()]
    return matches[0] if len(matches) == 1 else None


def _prop_colors() -> list[str]:
    from matplotlib import rcParams

    return rcParams["axes.prop_cycle"].by_key()["color"]


def _number(value: float, fmt: str) -> str:
    return format(value, fmt) if np.isfinite(value) else "nan"


def _comparison_label(row: pd.Series) -> str:
    """One line describing a comparison, e.g. ``E-005/G-001  240501  SIO  R1 1.02900  F``."""
    flags = _visible_flags(pd.Series([row["flags"]])).iloc[0]
    return (
        f"{row['tank']}/{row['std']}  {row['date']}  {row['site']}  "
        f"R1 {row['R1ratio']:.5f}  {flags}"
    ).rstrip()


def _comparison_cells(row: pd.Series) -> list[str]:
    flags = _visible_flags(pd.Series([row["flags"]])).iloc[0]
    return [
        row["tank"],
        row["std"],
        flags,
        row["site"],
        row["date"],
        _number(row["R1std"], ".5f"),
        _number(row["R1ratio"], ".5f"),
        _number(row["pstdev"], ".3f"),
        str(int(row["n"])),
    ]


def _mean_cells(row: pd.Series) -> list[str]:
    mean, sd = row["tank_mean"], row["tank_stdev"]
    pstdev = 100 * sd / mean if np.isfinite(mean) and mean else np.nan
    n = row["tank_n"]
    return ["", "", "", "", "", "Mean =", _number(mean, ".5f"), _number(pstdev, ".3f"),
            str(int(n)) if np.isfinite(n) else ""]

def main(gcdir: Path, gas: str | None = None) -> None:
    """Open the viewer on the R1 directory ``gcdir`` (see ``r1 gui``)."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)  # links the window to r1.desktop
    app.setWindowIcon(QIcon(str(LOGO)))
    window = R1Viewer(gcdir, gas)
    window.show()
    app.exec()
