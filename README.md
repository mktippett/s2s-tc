# s2s-tc

Analysis-ready tables of **S2S reforecast tropical-cyclone tracks** from the
[TCYC archive](https://aux.ecmwf.int/ecpds/data/list/TCYC) maintained by ECMWF. The archive
holds tracks computed with one common tracker (Vitart et al. 1997) from S2S reforecasts of
many centers.

This is a data curation project, not an analysis project. Scope: reforecasts
(hindcasts) only, track data only (no gridded fields). Started with ECMWF; other centers
come later.

## Data products

All products are under `data/tracks/<center>_reforecasts/`, written one **model_date year**
per file.

### `points_<year>.parquet`: one row per track point

| column | type | description |
|---|---|---|
| `center` | cat | producing center (`ecmwf`) |
| `model_cycle` | cat | model version (e.g. `CY49R1`), assigned from `model_date` (see `docs/ecmwf.md`) |
| `model_date` | datetime | real-time date the reforecast belongs to; defines the model version |
| `init_time` | datetime | reforecast start date (hdate) |
| `member` | int8 | ensemble member, 0..n−1 (0 = control) |
| `basin` | cat | source basin file: atl enp cnp wnp nin sin aus spc |
| `storm_num` | int16 | storm number within member × basin file (SNBR) |
| `c1` | int16 | storm number within member × basin group |
| `storm_uid` | str | `<center>.<model_date>.<init>.m<member>.<basin>.<storm_num>`, unique |
| `point_num` | int16 | 0-based index of the point within the storm |
| `valid_time` | datetime | valid (target) time; daily, 00Z |
| `lead_days` | int16 | `valid_time − init_time` in days (1–46) |
| `lat` | float32 | °N, signed |
| `lon`, `lon360` | float32 | °E in −180…180 and 0…360 |
| `wind_kt` | int16 | maximum wind (kt) |
| `mslp_hpa` | int16 | minimum MSLP (hPa) |
| `category` | cat | lifetime category from the source: TD, TS, HR, HR1–HR5 |
| `dup_point` | bool | point co-located (same time, <0.5°) with a point of a storm in another basin group's file |
| `dup_of` | str | partner `storm_uid`(s) of a cross-group duplicate, `;`-joined, `""` if none |
| `dup_type` | cat | this storm relative to its partner: identical, contained, contains, partial |
| `source_file` | cat | raw archive path below `data/raw/` |

### `members_<year>.parquet`: one row per forecast present

Columns: `center, model_cycle, model_date, init_time, member, member_raw, n_members,
n_storms, source_file`. A forecast with zero storms appears here and not in `points`. Use
this table, not `points`, as the denominator for forecast probabilities. Missing forecasts
(empty or undeliverable archives) appear in neither table.

### Important caveats
- **A forecast is `(model_date, init_time, member)`.** The same `init_time` recurs under
  several model_dates, i.e. with different model versions.
- **Cross-group duplicates are flagged, not removed** (~1.7% of storms). For storm counts,
  drop the duplicate side, e.g. count each storm in its genesis basin.
- **Time resolution is daily with gaps of up to 4 days.** Don't assume consecutive rows are
  24 h apart.
- Units are as in the source: kt and hPa.

Archive format: [`docs/tcyc_format.md`](docs/tcyc_format.md). ECMWF details (cycles,
cadence, anomalies): [`docs/ecmwf.md`](docs/ecmwf.md).

## Pipeline

```
python scripts/inventory.py   ecmwf reforecasts                        # FTP listing -> data/inventory/
python scripts/download.py    ecmwf reforecasts <year> [--workers 8]   # mirror raw tars -> data/raw/
cd scripts && python consolidate.py ecmwf reforecasts <year>           # -> data/tracks/
```
`<year>` is the model_date year. Downloads resume (complete files are skipped). Files the
server cannot deliver are listed in `data/inventory/<center>_reforecasts_failed_<year>.csv`.
Consolidation asserts every format invariant in `docs/tcyc_format.md` and fails loudly on
anything new.

Environment: Python ≥3.10 with pandas and pyarrow. `data/` is not in git: raw ≈ 6 GB for
ECMWF, regenerable from the FTP.

## Status (ECMWF)
| model_date year | downloaded | consolidated |
|---|---|---|
| 2025 | ✓ | ✓ |
| 2024 | ✓ | ✓ |
| 2023 | ✓ (5 undeliverable) | ✓ |
| 2015–2022, 2026 | | |

## Sanity plots
`cd scripts && python sanity_plots.py ecmwf 2025` writes `plots/ecmwf/sanity_0[1-4]_*.png`:
one hdate year of tracks (one member), genesis density, track density, and monthly genesis
by basin, all against IBTrACS v04r01 (`data/obs/`, downloaded from NCEI). These are
exploratory figures; the definitions are in the script docstring and the figure titles.
Key choices:
- Storms count if their lifetime max wind reaches 34 kt (IBTrACS) or 30 kt (model). The model
  value is an ad hoc choice that may be revised. It roughly matches the observed global storm
  count, and also the pooled frequency of the weekly basin-occupancy event scored in a
  NeuralGCM–ECMWF comparison. Basin-level biases remain.
- Model genesis is the first track point. Storms first seen at lead 1 are dropped: they may
  already exist at initialization.
- Rates are per-forecast means × 365/41 (genesis, leads 2–42) or × 365/42 (track points).
- Cross-basin duplicates are counted once.

## Data credit and terms
The track data are produced by ECMWF for the WWRP/WCRP
[Subseasonal-to-Seasonal (S2S) Prediction Project](https://www.ecmwf.int/en/forecasts/dataset/subseasonal-to-seasonal-prediction),
from the reforecasts of the contributing centers. This repository contains code and
documentation only. It does **not** redistribute the data: the pipeline downloads them from
ECMWF, and their use is subject to ECMWF's terms for S2S data.

## References
- Vitart, F., J. L. Anderson, and W. F. Stern, 1997: Simulation of interannual variability of
  tropical storm frequency in an ensemble of GCM integrations. *J. Climate*, **10**, 745–760.
- van der Grijn, G., J.-E. Paulsen, F. Lalaurette, and M. Leutbecher, 2005: Early medium-range
  forecasts of tropical cyclones. *ECMWF Newsletter*, **102**, 7–14.
- Vitart, F., and coauthors, 2017: The Subseasonal to Seasonal (S2S) Prediction Project
  database. *Bull. Amer. Meteor. Soc.*, **98**, 163–173.
