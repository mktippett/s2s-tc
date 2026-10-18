# TCYC archive format

The S2S tropical-cyclone track archive on ECMWF's FTP server. Facts here are **verified
against data** unless marked *(doc)*, meaning the archive's own `TCTRACK_Documentation.docx`,
which is wrong or incomplete in several places noted below. Verified so far on ECMWF
reforecasts only. Other centers use the same tracker and nominal format, but **re-verify
every item before trusting it for another center**. Center-specific details are in
`docs/<center>.md`.

## Access
- FTP `aux.ecmwf.int`, user/password `s2sidx`/`s2sidx`, root `TCYC/`. Web listing at
  `https://aux.ecmwf.int/ecpds/data/list/TCYC`.
- No MLSD; parse Unix-style `LIST` output. No server-side query: files are selected by path.
- Throughput is latency-bound (~0.9 files/s per connection, ~1 s per RETR). It scales
  linearly to at least 24 connections in short bursts. Under sustained 8-connection load the
  server intermittently refuses connections, and some files fail persistently with
  `java.rmi.ServerException` / `426 ... RemoteException` while their neighbours download
  fine. `scripts/download.py` retries each file 3 times, then records it in
  `data/inventory/<center>_<stream>_failed_<year>.csv`.

## Directory tree
```
TCYC/
  <center>/real-time/<YYYY>/<MM>/TC.<date>                         (doc; not inspected)
  <center>/reforecasts/<YYYY>/<MM>/TC.<center>.<hdate>.<model_date>
  era5/tcyc.EA.<year>          ERA5 tracks with the same tracker, 1959–2024
  TCTRACK_Documentation*.docx
```
Centers present: bom cma cnrm eccc ecmwf hmcr iap isac jma kma ncep ukmo. There is also a
stray `20190101/` directory, not inspected.

- `hdate` = reforecast start date. `model_date` = the real-time date the reforecast belongs
  to; *(doc)* calls it the "reference date". `<YYYY>/<MM>` is the year/month of
  `model_date`. See the center doc for how hdates relate to model_dates.
- `era5/` files are single-level tars of `<seq><YYYYMMDD>_<basin>` files (not yet parsed).
  They are a candidate tracker-consistent verification set.

## Nested tar structure
1. Outer file `TC.<center>.<hdate>.<model_date>` is a tar of one file per ensemble member,
   named `<center4>.<model_date>.<hdate>.<member>`. **Note: the date order is reversed
   relative to the outer name.** ECMWF: `ecmf`.
2. Each member file is a tar of 8 ASCII basin files:
   `atl` (N Atlantic), `enp` (E N Pacific), `cnp` (Central Pacific), `wnp` (W N Pacific),
   `nin` (N Indian), `sin` (S Indian), `aus` (Australian), `spc` (S Pacific).
3. An outer tar of exactly 10,240 bytes is empty (no members).

## Basin file (HURDAT-like)
```
00210 23/07/2023 M= 9  4 SNBR=   2                  header
00220 2023/07/23/00*1971132  28 1001*  0   0        point (M of these)
00305  TD                                           trailer
```
An empty basin is the single line `00000 00/00/0000 M= 0  0 SNBR=   0`.

**Header.** Fields: line number, first date `DD/MM/YYYY`, `M=` number of point rows, C1,
`SNBR=` C2.
- `M` equals the number of point rows, which is not the span in days, because tracks have gaps.
- The header date equals the first point's date.
- `SNBR` numbers storms 1..N, contiguous, per member × basin file.
- C1 numbers storms 1..N per member × **basin group**. The groups are NA = atl,
  NP = enp+cnp+wnp, NI = nin, SH = sin+aus+spc. Line numbers are also continuous within a
  group. C1 is unique per storm; it does not link storms across files.

**Point.** Fixed width after `*`. Do not split on whitespace (e.g. `*230 826`).

| field | chars | meaning |
|---|---|---|
| time | `YYYY/MM/DD/HH` | valid time. *(doc)* also says `DD/MM/YYYY/HH`, which is wrong |
| lat | 3 | latitude × 10. **Unsigned in SH basin files** (see below) |
| lon | 4 | longitude × 10, °E, 0–360 |
| wind | 4 | maximum wind, kt |
| pres | 5 | minimum MSLP, hPa |
| tail | `*  0   0` | always zeros |

- **SH latitude.** In `sin`/`aus`/`spc` files, latitude is stored as |lat|. With the sign
  negated, 54% of lead-1–2 points fall within 2° of an IBTrACS fix; as stored, 0% do. NH
  basin files carry a `-` sign for points south of the equator. How a north-of-equator point
  is written in an SH file is unverified (none seen so far).
- **Time.** In the ECMWF data, points are daily at 00Z only, at leads 1–46 days. There is
  never a lead-0 point, even though *(doc)* says storms present at initialization are included.
- **Gaps.** Consecutive points can be 2, 3 or 4 days apart (~6% of steps).
- **Genesis domain |lat| < 38°.** After lead 1, no storm starts poleward of 37.9° (ECMWF
  2025 model_date year). All 4,988 storms whose first point is poleward of 38° first appear
  at lead 1, i.e. they already existed at initialization. So lead-1 first points mix storms
  present at initialization with new genesis, and the sanity plots drop them.

**Lifetime-max floor.** Every storm reaches at least 21 kt. In the ECMWF 2025 model_date
year the minimum LMI is exactly 21 kt (11,846 of 694,237 storms), while individual points
go down to 3 kt. This is presumably a tracker retention criterion (not in *(doc)*), so any
model intensity threshold at or below 21 kt selects every storm.

**Trailer.** `TD`, `TS`, `HR`, and the **undocumented** `HR1`–`HR5`. The category is a
function of lifetime-maximum wind: TD < 35 ≤ TS < 64 ≤ HR kt. The HRn digit follows
Saffir–Simpson thresholds shifted **1 kt low**: HR2 ≥ 82, HR3 ≥ 95, HR4 ≥ 112 kt
(standard 83/96/113). HR5 has not been observed.

## Basin files and duplicates
- **A basin file is not a geographic clip; it is the genesis basin.** A storm keeps its full
  track in one file even after it crosses a basin boundary (e.g. `wnp` points reach 269°E).
  First points fall inside their file's region without exception (ECMWF 2025):
  sin < 90°E ≤ aus < 160°E ≤ spc (SH); wnp < 180° ≤ cnp < 220°E (140°W) ≤ enp.
  nin/wnp (87–103°E) and atl/enp (102–87°W) split along the coastline, not a meridian.
  For IBTrACS, `sanity_plots.py` uses its BASIN field for those two splits and the meridians
  above for the rest.
- **Storms crossing between basin groups appear in both groups' files**, with overlapping
  segments. Pairs: nin–wnp, atl–enp, and rarely nin–sin, aus–nin, aus–wnp, enp–spc.
  Within a group there are no co-located points.
  - Full ECMWF 2025 model_date year: 5,963 pairs (0.86% of storms). Of these, 1,322 are
    identical tracks, 2,077 have one contained in the other, and 2,564 overlap partially.
  - The curated tables flag these (`dup_point`, `dup_of`, `dup_type`) and keep every row.
- Within a group there are ~0.3% end→start near-continuations (≤1 d, <5°, different basin
  file). Their ends are not at basin boundaries, so they may be tracker breaks or coincidence.
  They are not linked in the data and not flagged.

## Tracker *(doc)*
Vitart et al. (1997) detection on 24-hourly S2S fields: an MSLP minimum, vorticity above
3.5×10⁻⁵ s⁻¹, and a warm core (200–500 hPa temperature maximum and 200–1000 hPa thickness
maximum, each within 2° of the MSLP minimum). Detections are linked into tracks following
van der Grijn et al. (2005).
