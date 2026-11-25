# r1 — Python port of the GCwerks R1 programs

`r1` propagates calibration scales from the reference tank of each gas to
every other tank, using the tank-vs-standard comparisons exported by the
GCwerks instruments. It is a port of `R1calc2`, `R1diff`, `R1drift_update`
and (as static plots) `R1plot`. See [../README.md](../README.md) for the C
programs and the method.

It depends on the [gcwerks](../../../python/gcwerks/README.md) package, which
reads the GCwerks files and provides the CLI helpers. Install both:

```
pip install -e ../../../python/gcwerks
pip install -e .            # or: pip install -e ".[plot,test]"
```

## Command line

Every command works on one R1 directory: the current one, or the one given
with `-C` (also `--gcdir`, or `-gcdir` as in the C programs).
`-C` and `-v` can go before or after the command:
`r1 calc -C /agage/R1/medusa -v` works too.

```
r1 -C /agage/R1/medusa calc                   # all gases, writes results/R1.standards
r1 -C /agage/R1/medusa calc --gas CFC-12      # one gas (R1.standards not written)
r1 -C /agage/R1/medusa calc --sort            # calc files ordered by tank, not pass
r1 -C /agage/R1/medusa drift-update           # drift/standards.drift from .input
r1 -C /agage/R1/medusa diff old/R1.standards results/R1.standards [--gas CFC-12]
r1 -C /agage/R1/medusa plot --gas CFC-12 --tank E-001
r1 -C /agage/R1/medusa plot --gas CFC-12 --site JFJ --scale 1
r1 -C /agage/R1/medusa plot --gas CFC-12 --filter-tank G- -G-055 --filter-std J-
```

Add `-v` for progress, or `-vv` for debug output.

## Python

```python
from r1 import R1Config, calculate
from r1.io.outputs import write_results

config = R1Config.from_dir("/agage/R1/medusa")
results = calculate(config)                         # nothing written yet
results.gases["CFC-12"].tanks["value"]              # R1 value per tank
results.gases["CFC-12"].comparisons                 # R1std, R1_used, flags, ...
write_results(results, config.paths, config.gases)  # calc/, plot/, results/
```

## Input directory

An R1 directory (e.g. `/agage/R1/medusa2`) must look like this. The paths
are set in `src/r1/paths.py`. All files are whitespace-separated text, and
`#` starts a comment.

```
<R1 directory>/
├── config/
│   ├── peak.list             gas  reference_tank          (one gas per line)
│   ├── site.codes            instrument_prefix  site_code
│   ├── gcwerks.conf          key value; only R1-standards-path is read
│   ├── standards.drift       tank gas fit date0 r0 p0 date1 r1 p1  (J tanks)
│   ├── R1.standards.drift    same format                           (gold tanks)
│   ├── standards             tank gas1 gas2 ...  table   (plot only)
│   └── standards.factors     gas factor                  (diff only)
├── export2/<instrument>/<gas>/<tank>_<std>_<yymmdd>
│                             r_ht %sd_ht n_ht r_a %sd_a n_a [flag]
├── flags/
│   ├── default_<instrument>[_<yy>]   gas flag   (gas may be "all")
│   └── <tank>_<std>_<yymmdd>         gas flag   (only flagged comparisons)
├── R1.standards.fixed        tank gas value     (R1 values imposed)
├── R1.standards.exclude      tank               (left out of R1.standards)
├── R1tanks                   tank site [serial_no] [fill_date]  (plot --site)
└── drift/standards.drift.input                  (drift-update only)
```

Details:

- **`config/peak.list`** gives the gases and for each gas its
  reference (R1) tank (e.g. `R1`, `T-008B`).
- **`export2/`**: each instrument is a directory, e.g. `sio-medusa`. Its site
  code is the first entry of `site.codes` that is a prefix of the name. Each
  gas directory must use the gas's `peak.list` name. A file name must have
  exactly three `_`-separated parts, so tank names use `-` (the `*.uscore`
  scripts convert them). Ratios of `0` or `nan` count as missing, and files
  with fewer than 6 numbers are skipped with a warning.
- **`flags/`**: a missing `default_<instrument>` file means no default flags
  (a warning is logged). Flags are `F`, `I`, `H`, `L`, and `UF`, `UI`, `UH`,
  `UL` to unset them.
- **`R1-standards-path`** (in `gcwerks.conf`, optional) is a directory, e.g.
  `/agage/R1/medusa2/standards.fixed`, containing a `standards` table and a
  `standards.drift` file. Its values are used as known std values.
  Relative paths are resolved from the R1 directory.
- `calc` needs `config/peak.list`, `site.codes`, `gcwerks.conf`, both drift
  files, `export2/`, `flags/`, `R1.standards.fixed` and
  `R1.standards.exclude`. The other files are only needed by the command noted
  above.

`calc` writes `calc/calc.<gas>`, `plot/plot.<gas>` and `results/R1.standards`
(only after all gases are done). `drift-update` writes
`drift/standards.drift`.

## Standard drift

The concentration in a tank can change while it is used: some compounds
deplete (e.g. by adsorbing on the walls), others grow as the pressure drops
(e.g. by desorbing from the walls). A drifting tank therefore has no single
value. Its value depends on the date of the comparison it is used in, and
the drift replaces the tank's value in the `standards` table.

Each line of a drift file is one segment for one tank and gas:

```
# Tank  Compound  Fit  date0   R0       P0    date1   R1       P1
T-004A  COS       1    071211  1.02457  510   170407  1.04222  280
G-189   CH3I      0    110615  0.80819  910   120109  2.03539  80
```

The tank has value `R0` on `date0` and `R1` on `date1`. `P0` and `P1` are
the tank pressures on those dates. Between the two dates, the value
follows the fit:

- **Fit 1, linear** (depletion; the pressures are ignored):
  `R(t) = R0 + (R1 - R0) * (t - t0) / (t1 - t0)`
- **Fit 0, logarithmic in pressure** (growth at a constant molar rate, which
  speeds up as the tank empties). The pressure is assumed to fall linearly,
  `P(t) = P0 + (P1 - P0) * (t - t0) / (t1 - t0)`, and
  `R(t) = R0 + (R1 - R0) * ln(P(t) / P0) / ln(P1 / P0)`.
  If a pressure is missing or not positive, or `P0 = P1`, the segment is
  treated as linear.

Both fits give exactly `R0` at `date0` and `R1` at `date1`. Before the first
segment and after the last one, the value is held at the nearest end-point.
Several segments of one tank and gas are joined, with a linear step between
consecutive segments. These rules for outside the segments are inferred: the
GCwerks library source was not available.

R1 uses two drift files, which `calc` both reads:

| File | Tanks | End-points |
|---|---|---|
| `config/R1.standards.drift` | gold tanks (T tanks) | set by hand, fixed |
| `config/standards.drift` | working tanks (J, G, … tanks) | from the propagation |

`config/standards.drift` is usually a link to `drift/standards.drift`, made by
`r1 drift-update` (`R1drift_update`) from `drift/standards.drift.input`. In
the input, an end-point written as `-` is replaced by the tank's R1 value on
that date from `plot/plot.<gas>`. So run `calc`, then `drift-update`, then
`calc` again for the new drift to be used.

When a comparison uses a drifting tank as its std, the std value is the
drift value on the comparison date. A drift wins over the tank's value in a
`standards` table. `r1 plot` draws the drift curve of the plotted tank.

## Package layout

Only the R1-specific parts are here. Everything GCwerks-level is in
`gcwerks`: the `config/` files (peak list, aliases, `gcwerks.conf`, site
codes, standards, factors, drift), the `Standards` model, the 2σ filter
and the CLI helpers.

```
src/r1/
├── paths.py          R1 files on top of gcwerks.paths.GCWerksPaths (R1Paths)
├── io/
│   ├── config.py     R1.standards.fixed/.exclude, R1tanks,
│   │                 R1Config (a gcwerks.config.GCWerksConfig)
│   ├── export2.py    export2/<inst>/<gas>/<tank>_<std>_<date> files
│   └── outputs.py    calc/, plot/ and results/R1.standards
├── flags.py          flag files and the F/N/*/x, I, H, L positions
├── calc.py           propagation (R1calc2)
├── drift.py          drift end-points from the results (R1drift_update)
├── diff.py           comparison of standards files (R1diff)
├── select.py         selection by tank, site or name filters (R1plot)
├── plot.py           matplotlib plots (optional dependency)
└── cli/              one module per `r1` subcommand; main.py runs them with
                      gcwerks.cli.run_commands
```

Only the CLI modules and `io/outputs.write_results` write files. Everything
else returns DataFrames.

## Tests

```
pytest
```

`tests/data/medusa/` is a small R1 directory. Its test cases cover:
- a reference tank per gas, including an automatic inversion (`H-001_J-102`);
- a 2σ outlier (`J-101`, 1.08);
- a std that is never resolved (`X-999`, marked `x`);
- the `F`, `L`, `I`, `H` and `UH` flags, the default flags per instrument,
  and a gas alias in a flag file;
- a fixed tank (`G-001`) and a drifting working tank (`J-102`);
- two instruments (SIO and JFJ);
- a comparison with too few points (`E-008`);
- a `-` end-point in `drift/standards.drift.input`.

## Differences from the C programs

- **Fixed tanks** (`R1.standards.fixed`) are treated as resolved and are
  never recalculated. `R1calc2` set `pass_done = 0` but left `value` unset,
  so a fixed tank that also has comparisons was recalculated. Its computed
  mean then replaced the fixed value in `R1.standards`.
- **Height/area choice**: `H` is read from the comparison's own flags. In
  `R1export2.read.c`, `HEIGHT(i)` used a stale index, so `r_used`,
  `pstdev_used` and `n_used` could come from the wrong comparison.
- **`r_used`** is inverted with `r_ht` and `r_a` when the `I` flag is set, so
  the calc file shows the ratio actually used.
- **Filter patterns** (`r1 plot --filter-*`): exclusions (`-XYZ`) always win,
  whatever the pattern order.
- **Not ported**: `R1export2`, which reads the GCwerks binary results table
  (`io/export2.write_export2_file` writes its output format); `R1convert`, a
  legacy one-off; the interactive GTK viewer, including its flag editing; and
  the `gccalc_status` lock.

## Assumptions about GCwerks formats

The formats assumed for the GCwerks files, the drift and the 2σ filter are
listed in the [gcwerks README](../../../python/gcwerks/README.md#assumptions).
On the R1 side, `R1.standards` uses the same format as `config/standards`, and
the only `gcwerks.conf` key read is `R1-standards-path`.



## Things to check

Guessed file formats. No GCwerks library source was available, so I inferred the formats of peak.list, standards, standards.factors and the drift files from how the C code uses them. The same goes for the drift interpolation and the exact 2σ filter. They're listed in the package README; please check them against a real R1 directory.
Two deliberate differences from the C code, which fix bugs:
Fixed tanks are never recalculated. In R1calc2, a fixed tank that also has comparisons gets recalculated, and the calculated value then replaces the fixed one in R1.standards.
Height or area is chosen from each comparison's own flags. This fixes the wrong-index bug I mentioned earlier.
Not ported:
R1export2: it reads the GCwerks binary results table. I did include a writer for the export2 format.
R1convert: legacy.
The interactive GTK viewer: r1 plot saves PNGs instead, with the same tank/site/filter selection and scaling options.
The gccalc_status lock.