# ECMWF reforecasts in TCYC

ECMWF-specific details. The archive-wide format is in `docs/tcyc_format.md`. Facts are
verified against data unless marked *(web)*, meaning ECMWF's S2S model page
<https://confluence.ecmwf.int/display/S2S/ECMWF+Model> (retrieved 2026-10-18).

## Files
- Files are at `TCYC/ecmwf/reforecasts/<YYYY>/<MM>/TC.ecmwf.<hdate>.<model_date>`. Members
  inside are named `ecmf.<model_date>.<hdate>.<member>`.
- The full inventory has 27,692 outer files (6.07 GB), with model_dates from 2015-01-01 to
  2026-10-01 (still growing). Rebuild it with `scripts/inventory.py ecmwf reforecasts`.
- Exception: 100 files in `2015/01` are named `TC.<hdate>.<model_date>` (no center).

## model_date, hdate and model cycle
- Reforecasts are run "on the fly". Each real-time `model_date` comes with 20 hindcasts
  that share its month and day, in the 20 preceding years (hdate year = model_date year −1
  … −20). All 20 are run with the model cycle operational at `model_date`.
- **The same hdate recurs under several model_dates**, and so under different cycles.
  Over 9,989 distinct non-empty hdates, the number of model_dates per hdate is
  1: 2145, 2: 2799, 3: 2189, 4: 1749, 5: 788, 6: 319. For example, hdate 2010-06-27 appears
  under the 2016, 2019, 2022, 2024, 2025 and 2026 model_dates. File sizes differ, so these are
  distinct forecasts.
- **A forecast is identified by `(model_date, hdate, member)`.**
- **The cycle is not recorded in the files.** It is assigned from model_date using the *(web)*
  table, which lives in `scripts/config.py:ECMWF_CYCLES`:

| cycle | implemented | ensemble (real time) | reforecast cadence | reforecast members |
|---|---|---|---|---|
| CY40R1 | 2015-01-01 | 51 | weekly (Thu) | 5 |
| CY41R1 | 2015-05-14 | 51 | Mon/Thu | 11 |
| CY41R2 | 2016-03-08 | 51 | Mon/Thu | 11 |
| CY43R1 | 2016-11-22 | 51 | Mon/Thu | 11 |
| CY43R3 | 2017-07-11 | 51 | Mon/Thu | 11 |
| CY45R1 | 2018-06-06 | 51 | Mon/Thu | 11 |
| CY46R1 | 2019-06-11 | 51 | Mon/Thu | 11 |
| CY47R1 | 2020-06-30 | 51 | Mon/Thu | 11 |
| CY47R2 | 2021-05-11 | 51 | Mon/Thu | 11 |
| CY47R3 | 2021-10-13 | 51 | Mon/Thu | 11 |
| CY48R1 | 2023-06-27 | 101 | Mon/Thu | 11 |
| CY49R1 | 2024-11-12 | 101 | odd days of month (no 29 Feb) | 11 |
| CY50R1 | 2026-05-13 | 101 | odd days of month (no 29 Feb) | 11 |

  - Atmosphere resolution *(web)*: TL639/TL319 (~32/64 km) for CY40R1–41R1; Tco639/Tco319
    (~16/32 km) for CY41R2–47R3; Tco319 L137 (~32 km) from CY48R1.
  - Caveat: reforecasts for a new cycle may have been produced before its operational date.
    Near a cycle boundary, the assignment by model_date can be wrong, and the archive cannot
    settle this (FTP mtimes are upload times). *(web)* says the first CY48R1 reforecasts ran
    on 2023-06-29.

## What the data shows, by model_date
| model_date | start days | hdates/date | members |
|---|---|---|---|
| 2015 Jan – ~May | mostly Thu (33 Mon in 2015 overall) | 20 | **5** |
| ~May 2015 – 2024-11-14 | Mon/Thu | 20 | 11 |
| 2024-11-17 → | odd days of the month | 20 | 11 |

The exact 5→11-member switch date is still to be confirmed once the 2015 data is
downloaded.

## Anomalies
- **Empty placeholders.** 432 files on irregular model_dates from 2017-10 to 2018-07
  (1st/9th/17th/25th, 13–18 hdates covering 1997–2014) are all empty 10,240-byte tars.
  They are skipped.
- **Offset member numbers.** Some 2018 archives number members `11·k + m`, where k is the
  hindcast-year index (e.g. hdate 2009 under model_date 2018 → members 121–131).
  `consolidate.py` maps each archive's member block to 0..n−1 and asserts the block is
  contiguous and aligned. How widespread this is will be known after the 2018 consolidation.
- **Undeliverable files.** Some archives fail persistently on the server (see
  `docs/tcyc_format.md` § Access). They are listed in
  `data/inventory/ecmwf_reforecasts_failed_<year>.csv` and are absent from
  `members_<year>`, so they count as missing forecasts.

## 2025 model_date year (consolidated)
- All CY49R1: 186 model_dates, hindcast years 2005–2024, 11 members, 3,720 archives.
- 40,920 forecasts, 694,237 storms, 3.9 M points.
- Categories: TD 365k, TS 314k, HR1 13.8k, HR2 987, HR3 149, HR4 10.
- Duplicate flags: 1.71% of storms (both sides of each cross-group pair).
