"""Default locations of the files inside an R1 directory.

An R1 directory (e.g. ``/agage/R1/medusa``) is a GCwerks directory, with the
``config/`` files of :class:`gcwerks.paths.GCWerksPaths`, plus the R1 files
below. The C programs had to be started from it.
"""

from pathlib import Path

from gcwerks.paths import GCWerksPaths


class R1Paths(GCWerksPaths):
    """Resolve the file locations of one R1 directory.

    :param root: The R1 directory.
    """

    @property
    def r1_standards_drift(self) -> Path:
        return self.config_dir / "R1.standards.drift"

    @property
    def standards_fixed(self) -> Path:
        return self.root / "R1.standards.fixed"

    @property
    def standards_exclude(self) -> Path:
        return self.root / "R1.standards.exclude"

    @property
    def r1tanks(self) -> Path:
        return self.root / "R1tanks"

    @property
    def export2_dir(self) -> Path:
        return self.root / "export2"

    @property
    def flags_dir(self) -> Path:
        return self.root / "flags"

    @property
    def calc_dir(self) -> Path:
        return self.root / "calc"

    @property
    def plot_dir(self) -> Path:
        return self.root / "plot"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def drift_dir(self) -> Path:
        return self.root / "drift"

    @property
    def r1_standards(self) -> Path:
        return self.results_dir / "R1.standards"

    @property
    def drift_input(self) -> Path:
        return self.drift_dir / "standards.drift.input"

    @property
    def drift_output(self) -> Path:
        return self.drift_dir / "standards.drift"

    def calc_file(self, gas: str) -> Path:
        """Return the path of the ``calc/calc.<gas>`` report."""
        return self.calc_dir / f"calc.{gas}"

    def plot_file(self, gas: str) -> Path:
        """Return the path of the ``plot/plot.<gas>`` table."""
        return self.plot_dir / f"plot.{gas}"
