# consolidate.py

## 1. Purpose
Convert one model_date year of raw TCYC reforecast track archives for one center into two
analysis-ready parquet tables: track points, and the forecasts present. Every format
invariant documented in `docs/tcyc_format.md` is asserted, so any new format variant fails
loudly instead of being silently misparsed.

## 2. Inputs
| file | relevant content | filters |
|---|---|---|
| `data/inventory/<center>_<stream>.parquet` | `path`, `name`, `size` of every FTP file | name starts `TC.`; path under `<year>/`; size > `EMPTY_TAR_SIZE` |
| `data/raw/<center>/<stream>/<YYYY>/<MM>/TC.*` | nested tar → member tar → 8 basin text files | must exist unless listed in the failure record |
| `data/inventory/<center>_<stream>_failed_<year>.csv` | `path` of archives the server could not deliver | optional |

## 3. Outputs
| file | contents | format |
|---|---|---|
| `data/tracks/<center>_<stream>/points_<year>.parquet` | one row per track point (schema in README) | parquet; categorical string columns |
| `data/tracks/<center>_<stream>/members_<year>.parquet` | one row per (model_date, init_time, member) present: `n_storms`, `n_members`, `member_raw`, `model_cycle` | parquet |
| stdout (→ `logs/consolidate_<center>_<year>.log`) | counts and soft diagnostics | text |

## 4. Algorithm
1. Select the year's archives from the inventory and drop empty tars (10,240 B). Any raw
   file that is absent must be listed in the failure record; otherwise assert-fail.
2. For each archive, parse it with `tcyc_parse.parse_outer` (strict: any unrecognised line
   raises). Assert that the inner member names carry the outer file's model_date and hdate.
3. **Members.** In each archive, the raw member numbers must form one contiguous block whose
   minimum is a multiple of the block size n. Set `member = member_raw − min`. This covers
   the 2018 offset numbering `11·k + m`.
4. **Hard invariants** (assert):
   - hdate MMDD = model_date MMDD
   - all points at 00Z
   - trailing fields `0   0`
   - `M=` = number of point rows
   - header date = first point date
   - no duplicate valid_time within a track
   - SNBR = 1..N per (archive, member, basin)
   - category prefix = TD (<35 kt) / TS (<64) / HR, from lifetime max wind
5. **Soft diagnostics** (printed):
   - HRn digit against `SS_THRESH`
   - count of `-` latitudes in SH and NH files
   - lead range
   - step-length histogram
   - members per archive and archives with offset numbering
6. **Derived columns.**
   - `lat` = raw/10, negated for SH basin files (`SH_BASINS`).
   - `lon360` = raw/10 (assert 0–360), and `lon` wrapped to −180…180 (arithmetic in float64, stored float32).
   - `lead_days` = valid_time − init_time in days.
   - `model_cycle` from `config.ecmwf_cycle(model_date)`.
   - `storm_uid` = `<center>.<model_date>.<init>.m<member:02>.<basin>.<snbr:03>`.
   - `point_num` = 0-based index within the storm.
7. **Duplicate flags** (`flag_duplicates`):
   - Self-join points on (archive, member, valid_time).
   - Keep pairs in different basin groups (`BASIN_GROUP`) whose positions differ by less than
     `DUP_DEG`, with distance = hypot(Δlat, Δlon wrapped).
   - `dup_point` marks such points. Per storm, `dup_of` = partner storm_uid(s), `;`-joined.
   - `dup_type` compares shared count s with storm lengths n_self, n_other: identical
     (s = n_self = n_other), contained (s = n_self), contains (s = n_other), otherwise partial.
   - Flags only: no rows are dropped.
8. Write both tables.

## 5. Constants & Scientific Rationale
| name | value | why |
|---|---|---|
| `EMPTY_TAR_SIZE` | 10240 B | size of a GNU tar with no members; 432 such placeholders on irregular 2017–18 model_dates |
| `SH_BASINS` | sin, aus, spc | these files store \|lat\|; negating matches IBTrACS (54% vs 0% within 2° at leads 1–2) |
| `BASIN_GROUP` | NA=atl; NP=enp,cnp,wnp; NI=nin; SH=sin,aus,spc | groups sharing the C1 counter; duplicates occur only between groups (verified, 2025) |
| `DUP_DEG` | 0.5° | co-location radius; chosen at recon (89% of co-located pairs are identical), not tuned |
| `SS_THRESH` | HR1 64, HR2 82, HR3 95, HR4 112, HR5 136 kt | observed lower bounds (1 kt below standard Saffir–Simpson) on 2023–2025; HR5 inferred, not yet observed |
| `ECMWF_CYCLES` | table in `config.py` | ECMWF S2S model page (retrieved 2026-10-18); cycle is not in the files |
| dedup policy | flag only | user decision 2026-10-18; dedup is left to each analysis |

## 6. Edge Cases & Error Handling
- **Empty basin placeholder** (`M= 0`) produces no storm.
- **Members with zero storms** still get a `members` row. Absent archives produce no rows in
  either table, so they count as missing forecasts, not zero storms.
- **Unprefixed names** `TC.<hdate>.<model_date>` in 2015/01: model_date and hdate are taken
  from the last two dot-fields, so both naming forms work.
- **Duplicate partner bookkeeping.** A storm may have several partners. `dup_of`/`dup_type`
  are aligned `;`-joined lists.
- **Cycle boundary.** Assignment uses model_date ≥ implementation date. Reforecasts made
  ahead of the operational date would be mislabelled; the archive cannot resolve this.
- **Imports.** Must be run from `scripts/`: it imports `config` and `tcyc_parse` as siblings.

## Open items
- Extent of offset member numbering is unknown until the 2018 consolidation. The block
  check will pass or fail it.
- How an SH-file point north of the equator is written (none seen in 2023–2025).
- The HR5 lower bound (136 kt) is inferred.

## 7. Synchronization Log
| date | code change | spec updated |
|---|---|---|
| 2026-10-18 | created: strict parse, member normalisation, SH lat sign, cycle table, `HRn` thresholds (82/95/112), duplicate flags, failure-record check | created |

## Verification snippet
```python
import pandas as pd
y = 2025
p = pd.read_parquet(f"data/tracks/ecmwf_reforecasts/points_{y}.parquet")
m = pd.read_parquet(f"data/tracks/ecmwf_reforecasts/members_{y}.parquet")
assert p[["lat", "lon360", "wind_kt", "mslp_hpa", "lead_days"]].notna().all().all()
assert p.lead_days.between(1, 46).all() and (p.valid_time.dt.hour == 0).all()
assert (p[p.basin.isin(["sin", "aus", "spc"])].lat <= 0).all()
assert not p.duplicated(["storm_uid", "valid_time"]).any()
assert m.member.between(0, 10).all() and not m.duplicated(["model_date", "init_time", "member"]).any()
n = p.groupby("storm_uid").size().size
assert n == m.n_storms.sum(), (n, m.n_storms.sum())
print("ok", len(p), "points", n, "storms", len(m), "forecasts")
```
