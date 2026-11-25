"""Propagation of R1 values from the reference tank to all tanks (``R1calc2``).

For one comparison of ``tank`` against ``std``, ``r = C_tank / C_std`` and::

    R1(tank) = r * R1(std)

The R1 value of a tank is the filtered mean over its comparisons. It can be
computed once the R1 of every std it was measured against is known. The
reference tank has R1 = 1, so each pass resolves the tanks one step further
from it. When a pass resolves nothing, tanks may be resolved with some of
their stds still unknown (see :data:`RELAXED_CRITERIA`).

Values are never iterated: once a tank is resolved its value is final.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from gcwerks.io.text import yymmdd_to_datetime
from gcwerks.standards import Standards
from gcwerks.stats import DEFAULT_NSTDEV, FilteredStats, filtered_stats
from r1 import flags as fl
from r1.io.config import R1Config, read_exclude, read_fixed
from r1.io.export2 import read_export2

logger = logging.getLogger(__name__)

MAX_PASS = 100
# progress(stage, done, total), called by calculate() for each gas while
# reading the export2 files, reading the flags and resolving the tanks
Progress = Callable[[str, int, int], None]
STAGES = {"read": "reading comparisons", "flags": "reading flags", "propagate": "resolving tanks"}
MIN_POINTS = 3
KINDS = {"used": "R1_used", "area": "R1_a", "height": "R1_ht"}

# (max_skip, min_std) tried in order until a pass resolves at least one tank:
# first no skipped std at all, then up to max_skip stds without R1 value as
# long as at least min_std stds have one.
RELAXED_CRITERIA = [(0, 0)] + [
    (max_skip, min_std)
    for min_std in range(8, 0, -1)
    for max_skip in range(1, max(min_std, 3) + 1)
]


def load_comparisons(
    config: R1Config, gas: str, min_points: int = MIN_POINTS, progress: Progress | None = None
) -> pd.DataFrame:
    """Read the comparisons of ``gas`` with their flags.

    Comparisons without a ratio or with fewer than ``min_points`` runs are
    dropped.

    :param config: The R1 configuration.
    :param gas: The gas.
    :param min_points: Minimum number of runs of a comparison.
    :param progress: See :data:`Progress` (stages ``read`` and ``flags``).
    :return: The comparisons, see :func:`r1.io.export2.read_export2`, plus
        ``flags``.
    """
    comparisons = read_export2(
        config.paths.export2_dir, gas, config.site_codes, _stage(progress, "read")
    )
    comparisons["flags"] = fl.read_comparison_flags(
        comparisons, config.paths.flags_dir, gas, config.aliases, _stage(progress, "flags")
    )
    comparisons = select_height_or_area(comparisons)
    enough = np.isfinite(comparisons["r_used"]) & (comparisons["n_used"] >= min_points)
    return comparisons[enough].reset_index(drop=True)


def select_height_or_area(comparisons: pd.DataFrame) -> pd.DataFrame:
    """Add the ``*_used`` columns: height where flagged ``H``, else area."""
    comparisons = comparisons.copy()
    height = fl.use_height(comparisons["flags"])
    for column in ["r", "pstdev", "n"]:
        comparisons[f"{column}_used"] = comparisons[f"{column}_ht"].where(
            height, comparisons[f"{column}_a"]
        )
    return comparisons


def invert_comparisons(comparisons: pd.DataFrame, reftank: str) -> pd.DataFrame:
    """Swap tank and std where flagged ``I`` or where the tank is ``reftank``.

    The ratios become their inverse.
    """
    comparisons = comparisons.copy()
    swap = fl.inverted(comparisons["flags"]) | (comparisons["tank"] == reftank)
    comparisons.loc[swap, ["tank", "std"]] = comparisons.loc[
        swap, ["std", "tank"]
    ].to_numpy()
    ratios = ["r_ht", "r_a", "r_used"]
    comparisons.loc[swap, ratios] = 1.0 / comparisons.loc[swap, ratios]
    return comparisons


def prepare_comparisons(comparisons: pd.DataFrame, reftank: str) -> pd.DataFrame:
    """Invert, sort by tank, date and std, and mark the used comparisons.

    ``in_mean`` is False for the comparisons after the ``L`` one of a tank,
    ``used`` is True for those entering the tank mean.
    """
    comparisons = invert_comparisons(comparisons, reftank)
    comparisons["time"] = yymmdd_to_datetime(comparisons["date"])
    comparisons = comparisons.sort_values(["tank", "time", "std"], kind="stable")
    comparisons = comparisons.reset_index(drop=True)

    after_last = (
        fl.last(comparisons["flags"])
        .groupby(comparisons["tank"])
        .transform(lambda is_last: is_last.cumsum().shift(fill_value=0) > 0)
    )
    comparisons["in_mean"] = ~after_last.astype(bool)
    comparisons["used"] = (
        comparisons["in_mean"]
        & np.isfinite(comparisons["r_used"])
        & ~fl.flagged(comparisons["flags"])
    )
    return comparisons


@dataclass
class GasResult:
    """Result of the propagation of one gas.

    :param gas: The gas.
    :param reftank: Its reference tank.
    :param comparisons: The comparisons, with ``R1std``, ``R1_ht``, ``R1_a``,
        ``R1_used`` and updated ``flags``.
    :param tanks: One row per tank: ``value`` (NaN if not resolved),
        ``fixed``, ``pass_done`` (-1 if not resolved, 0 if fixed),
        ``std_skip_count`` and the mean, stdev, percent stdev, count and
        used count of each of :data:`KINDS`.
    """

    gas: str
    reftank: str
    comparisons: pd.DataFrame
    tanks: pd.DataFrame


class Propagation:
    """Resolve the R1 values of the tanks of one gas.

    :param comparisons: Output of :func:`prepare_comparisons`.
    :param gas: The gas.
    :param reftank: Its reference tank.
    :param standards: Known R1 values, updated with the resolved tanks.
    :param path_standards: Values from ``R1-standards-path``, looked up first.
    :param fixed: Imposed values (``tank``, ``value``) for this gas.
    :param nstdev: Threshold of the tank mean filter.
    """

    def __init__(
        self,
        comparisons: pd.DataFrame,
        gas: str,
        reftank: str,
        standards: Standards,
        path_standards: Standards | None = None,
        fixed: pd.DataFrame | None = None,
        nstdev: float = DEFAULT_NSTDEV,
    ) -> None:
        self.comparisons = comparisons.copy()
        self.gas = gas
        self.reftank = reftank
        self.standards = standards
        self.path_standards = path_standards
        self.nstdev = nstdev

        self.rows = {
            tank: np.asarray(rows)
            for tank, rows in comparisons.groupby("tank").indices.items()
        }
        self.used = comparisons["used"].to_numpy()
        self.r1std = np.full(len(comparisons), np.nan)

        self.value = pd.Series(np.nan, index=list(self.rows), dtype=float)
        self.fixed = pd.Series(np.nan, index=self.value.index, dtype=float)
        self.pass_done = pd.Series(-1, index=self.value.index, dtype=int)
        self.skip_count = pd.Series(0, index=self.value.index, dtype=int)
        self.stats: dict[str, dict[str, FilteredStats]] = {}
        self.progress: Callable[[int, int], None] | None = None
        self._set_fixed(fixed)

    def _set_fixed(self, fixed: pd.DataFrame | None) -> None:
        """Put the fixed values in the standards and resolve those tanks."""
        if fixed is None:
            return
        for tank, value in zip(fixed["tank"], fixed["value"]):
            self.standards.set_value(tank, self.gas, value)
            if tank in self.value.index:
                self.value[tank] = self.fixed[tank] = value
                self.pass_done[tank] = 0
            logger.info(f"{self.gas}: fixed {tank} = {value}")

    def lookup_r1_std(self, rows: np.ndarray) -> np.ndarray:
        """Return the R1 value of the std of each comparison in ``rows``.

        The reference tank is 1. Otherwise ``R1-standards-path`` is looked up
        first, then the current standards (resolved, fixed and drifting
        tanks).
        """
        stds = self.comparisons["std"].to_numpy()[rows]
        times = self.comparisons["time"].to_numpy()[rows]

        values = np.full(len(rows), np.nan)
        if self.path_standards is not None:
            values = self.path_standards.get_values(stds, self.gas, times)
        missing = ~np.isfinite(values)
        values[missing] = self.standards.get_values(
            stds[missing], self.gas, times[missing]
        )
        values[stds == self.reftank] = 1.0
        return values

    def _check_stds(
        self, rows: np.ndarray, max_skip: int, min_std: int
    ) -> tuple[bool, int]:
        """Return whether the tank can be resolved, and its skipped std count."""
        used = self.used[rows]
        known = np.isfinite(self.r1std[rows])
        skipped = int((used & ~known).sum())
        known_count = int((used & known).sum())
        ok = skipped <= max_skip and not (skipped and known_count < min_std)
        return ok, skipped

    def _tank_mean(self, tank: str, rows: np.ndarray) -> float:
        """Compute and store the filtered means of the used comparisons."""
        used_rows = rows[self.used[rows]]
        r_ht = self.comparisons["r_ht"].to_numpy()[used_rows]
        r_a = self.comparisons["r_a"].to_numpy()[used_rows]
        r_used = self.comparisons["r_used"].to_numpy()[used_rows]
        r1std = self.r1std[used_rows]
        self.stats[tank] = {
            "used": filtered_stats(r_used * r1std, self.nstdev),
            "area": filtered_stats(r_a * r1std, self.nstdev),
            "height": filtered_stats(r_ht * r1std, self.nstdev),
        }
        return self.stats[tank]["used"].mean

    def run_pass(self, ipass: int, max_skip: int = 0, min_std: int = 0) -> int:
        """Try to resolve every unresolved tank once.

        Tanks are handled in name order and a resolved tank is immediately
        available as a std for the following ones.

        :param ipass: Pass number, stored for the resolved tanks.
        :param max_skip: Maximum number of used comparisons whose std has no
            R1 value yet.
        :param min_std: Minimum number of stds with a value when some are
            skipped.
        :return: Number of tanks resolved.
        """
        resolved = 0
        total_resolved = int(np.isfinite(self.value).sum())
        for tank in self.value.index[~np.isfinite(self.value)]:
            rows = self.rows[tank]
            unknown = rows[~np.isfinite(self.r1std[rows])]
            self.r1std[unknown] = self.lookup_r1_std(unknown)

            ok, skipped = self._check_stds(rows, max_skip, min_std)
            if not ok:
                continue
            mean = self._tank_mean(tank, rows)
            if not np.isfinite(mean):
                continue

            self.value[tank] = mean
            self.pass_done[tank] = ipass
            self.skip_count[tank] = skipped
            self.standards.set_value(tank, self.gas, mean)
            resolved += 1
            if self.progress is not None:
                self.progress(total_resolved + resolved, len(self.value))
        return resolved

    def run(
        self, max_pass: int = MAX_PASS, progress: Callable[[int, int], None] | None = None
    ) -> GasResult:
        """Run the passes until no more tank can be resolved.

        :param progress: Called with (tanks resolved, number of tanks).
        """
        self.progress = progress
        for ipass in range(1, max_pass):
            done, criteria = 0, (0, 0)
            for criteria in RELAXED_CRITERIA:
                done = self.run_pass(ipass, *criteria)
                if done:
                    break
            if not done:
                break
            logger.info(
                f"{self.gas} pass {ipass:2d}: {done} tanks (max_skip, min_std) {criteria}"
            )

        return GasResult(
            self.gas, self.reftank, self._comparisons_result(), self._tanks_result()
        )

    def _comparisons_result(self) -> pd.DataFrame:
        comparisons = self.comparisons
        comparisons["R1std"] = self.r1std
        comparisons["R1_ht"] = comparisons["r_ht"] * self.r1std
        comparisons["R1_a"] = comparisons["r_a"] * self.r1std
        comparisons["R1_used"] = comparisons["r_used"] * self.r1std

        resolved_tank = comparisons["tank"].map(np.isfinite(self.value))
        skipped = comparisons["used"] & resolved_tank & ~np.isfinite(self.r1std)
        comparisons["flags"] = fl.set_position(comparisons["flags"], skipped, 0, "x")

        lower = comparisons["tank"].map(lambda t: self._bound(t, "lower", -np.inf))
        upper = comparisons["tank"].map(lambda t: self._bound(t, "upper", np.inf))
        r1 = comparisons["R1_used"]
        rejected = comparisons["used"] & np.isfinite(r1) & ((r1 < lower) | (r1 > upper))
        comparisons["flags"] = fl.set_position(comparisons["flags"], rejected, 0, "*")
        return comparisons

    def _bound(self, tank: str, name: str, default: float) -> float:
        stats = self.stats.get(tank)
        return getattr(stats["used"], name) if stats else default

    def _tanks_result(self) -> pd.DataFrame:
        tanks = pd.DataFrame(
            {
                "value": self.value,
                "fixed": self.fixed,
                "pass_done": self.pass_done,
                "std_skip_count": self.skip_count,
            }
        )
        for kind in KINDS:
            stats = pd.Series(
                {
                    tank: self.stats.get(tank, {}).get(kind, FilteredStats())
                    for tank in tanks.index
                }
            )
            tanks[f"{kind}_mean"] = stats.map(lambda s: s.mean)
            tanks[f"{kind}_stdev"] = stats.map(lambda s: s.stdev)
            tanks[f"{kind}_pstdev"] = stats.map(lambda s: s.percent_stdev)
            tanks[f"{kind}_count"] = stats.map(lambda s: s.count)
            tanks[f"{kind}_count_used"] = stats.map(lambda s: s.count_used)
        tanks.index.name = "tank"
        return tanks


@dataclass
class CalcResults:
    """Results of :func:`calculate`.

    :param gases: Result per gas, in peak list order.
    :param standards: R1 values of all tanks (the future ``R1.standards``).
    :param exclude: Tanks to leave out of ``R1.standards``.
    """

    gases: dict[str, GasResult] = field(default_factory=dict)
    standards: Standards = field(default_factory=Standards)
    exclude: list[str] = field(default_factory=list)


def initial_standards(config: R1Config) -> Standards:
    """Standards known before propagation: the reference tanks and drifts."""
    values = pd.DataFrame(np.nan, index=pd.Index([], name="tank"), columns=config.gases)
    standards = Standards.from_files(
        drifts=[config.paths.standards_drift, config.paths.r1_standards_drift],
        aliases=config.aliases,
    )
    standards.values = values
    for gas, reftank in zip(config.peaks["name"], config.peaks["scale"]):
        standards.set_value(reftank, gas, 1.0)
    return standards


def path_standards(config: R1Config) -> Standards | None:
    """Standards from the ``R1-standards-path`` directory, if configured."""
    directory = config.r1_standards_path
    if directory is None:
        return None
    logger.info(f"R1-standards-path: {directory}")
    return Standards.from_files(
        standards=directory / "standards",
        drifts=[directory / "standards.drift"],
        aliases=config.aliases,
    )


def calculate(
    config: R1Config,
    gases: list[str] | None = None,
    max_pass: int = MAX_PASS,
    progress: Progress | None = None,
) -> CalcResults:
    """Propagate the R1 values of ``gases`` (default: all of the peak list).

    :param config: The R1 configuration.
    :param gases: Gases to calculate.
    :param max_pass: Maximum number of passes.
    :param progress: See :data:`Progress`.
    :return: Results per gas and the standards of all tanks.
    """
    standards = initial_standards(config)
    extra = path_standards(config)
    fixed = read_fixed(config.paths.standards_fixed, config.aliases)
    results = CalcResults(
        standards=standards, exclude=read_exclude(config.paths.standards_exclude)
    )

    for gas in gases or config.gases:
        reftank = config.reference_tank(gas)
        logger.info(f"=== {gas} (reftank {reftank}) ===")
        comparisons = load_comparisons(config, gas, progress=progress)
        comparisons = prepare_comparisons(comparisons, reftank)
        propagation = Propagation(
            comparisons, gas, reftank, standards, extra, fixed[fixed["gas"] == gas]
        )
        results.gases[gas] = propagation.run(max_pass, _stage(progress, "propagate"))
    return results


def _stage(progress: Progress | None, stage: str) -> Callable[[int, int], None] | None:
    """``progress`` with its stage set, or None."""
    if progress is None:
        return None
    return lambda done, total: progress(stage, done, total)
