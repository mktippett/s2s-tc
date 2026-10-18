# sanity_plots.py

## 1. Purpose
Exploratory checks that a center's consolidated reforecast tracks look like tropical
cyclones: one year of tracks, genesis and track density, and the monthly genesis cycle
by basin, all against IBTrACS. These are not production figures.

## 2. Inputs
| file | relevant columns | filters |
|---|---|---|
| `data/tracks/<center>_reforecasts/points_<year>.parquet` | init_time, member, basin, storm_uid, point_num, valid_time, lead_days, lat, lon360, wind_kt, dup_point, dup_of | see Algorithm |
| `data/tracks/<center>_reforecasts/members_<year>.parquet` | one row per forecast; `model_cycle` | all rows = denominator |
| `data/obs/ibtracs.since1980.list.v04r01.csv` | SID, BASIN, ISO_TIME, NATURE, TRACK_TYPE, LAT, LON, USA_WIND | TRACK_TYPE main, NATURE TS, USA_WIND ≥ 34, minute 0 and hour ∈ {0,6,12,18}, calendar year within the hdate years |

## 3. Outputs
| file | contents | format |
|---|---|---|
| `plots/<center>/sanity_01_tracks_md<year>_h<hdate_year>_m00.png` | tracks of member 0, every 5th start date in one hdate year, coloured by wind (kt); all tracked storms, TD included | png |
| `plots/<center>/sanity_02_genesis_density_md<year>.png` | (a) model, (b) IBTrACS, (c) difference, (d) per-hemisphere latitude sums | png |
| `plots/<center>/sanity_03_track_density_md<year>.png` | same layout; storm-days per year | png |
| `plots/<center>/sanity_04_monthly_genesis_md<year>.png` | 8 panels (TCYC basins): model vs IBTrACS bars, IBTrACS 95% CI | png |

## 4. Algorithm
1. **Deduplication** (cross-group duplicates, from the `dup_*` flags):
   - A storm whose first point is co-located with a partner is not a genesis if that partner
     started earlier, or started at the same time with a lexicographically smaller storm_uid.
   - A co-located point is kept only on the storm with the smallest uid in its `dup_of` set.
2. **TS thresholds.** IBTrACS 34 kt; model T = `MODEL_TS_KT` = 30 kt (ad hoc).
   - Diagnostics printed and put in titles: the IBTrACS LMI quantile of 34 kt, i.e.
     P(LMI < 34) over storms first seen in the hdate years (depression-only storms included,
     no-`USA_WIND` storms excluded); and the model LMI quantile of T over the
     genesis-eligible population (deduplicated, first point at leads 2…42).
3. **Storm selection.** Keep model storms with LMI ≥ T. IBTrACS keeps LMI ≥ 34 kt.
4. **Model genesis.** The first point (point_num 0) of a selected, genesis-eligible storm with
   `lead_days` in 2…42. Storms first seen at lead 1 are dropped.
   - Rate per cell or month = count / N_fcst × 365/41, where N_fcst = rows of `members`.
5. **Model track points.** Points of selected storms with wind ≥ T, lead ≤ 42, kept by the
   dedup rule. Rate = count / N_fcst × 365/42 (storm-days per year).
5. **IBTrACS.**
   - Genesis = first filtered (≥34 kt) 6-hourly point per SID.
   - Track points = filtered points at 00Z only, matching the model's daily cadence.
   - Rates = count / number of years.
6. **IBTrACS basins** → TCYC regions:
   - NA → atl; WP → wnp; NI → nin.
   - EP → enp if lon ≥ 220°E, else cnp.
   - SI/SP → sin if lon < 90°E, aus if lon < 160°E, else spc.
   - Anything else → "other", whose count is printed.
7. **Density.** 2-D histogram on 1.5° cells (0–360°E, 60°S–60°N), with no smoothing.
   - Panel (d): sum over latitude per hemisphere, Gaussian σ = 2 cells, wrap mode.
   - Genesis: separate colour scales for (a) and (b), each vmax = 0.9 × its own max.
   - Track: one shared scale for (a) and (b), vmax = √(0.9·max_a × 0.9·max_b).
   - Difference: RdBu_r, symmetric at 0.9 × |max|.
8. **Monthly.** Model genesis by valid_time month of the genesis point.
   - IBTrACS year × month counts, with 95% percentile CI from `n_boot` resamples of years
     with replacement (rng seed 0).
9. **Track map.** Segments are drawn in display (central_longitude 205) coordinates;
   segments crossing the map seam are skipped. Colour = mean wind of the two endpoints.

## 5. Constants & Scientific Rationale
| name | value | why |
|---|---|---|
| `TS_KT` | 34 kt | observed TS threshold. It is used directly for IBTrACS, and its LMI quantile sets the model threshold |
| `MODEL_TS_KT` | 30 kt | **Ad hoc** (user, 2026-10-18), for sanity checking only; may be revised. It roughly matches the observed global count (ECMWF 2025: 87.1 vs 86.5 storms/yr) and is the model LMI 31st percentile. It also matches the pooled frequency of the weekly basin-occupancy event scored in the neuralGCM ECMWF comparison: pooled bias −0.003 against an observed rate of 0.511, crossing zero near 29.8 kt; basin biases range from −0.19 (AL) to +0.17 (SP). Reported by that session (`neuralGCM/analysis/specs/ecmwf_comparison.md` §5–6) and not re-run here. Rejected: 34 kt (64/yr, CY49R1 winds not comparable to obs); LMI quantile matching after Lee et al. (2018, WAF 33, doi:10.1175/WAF-D-17-0165.1), which gives 24 kt with q = 8.1% from IBTrACS 2005–2024, or 27 kt with their 18%. The observed q is low because SI/SP agencies rarely archive depressions (0–1% of storms there, against 12–14% in WP/EP) |
| lead-1 drop | first point at lead 1 → not genesis | user decision 2026-10-18. No lead-0 point exists, so storms present at initialization first appear at lead 1. All 4,988 storms first seen poleward of 38° start at lead 1 |
| `LEAD_MAX` | 42 d | window of 6 whole weeks, as in the neuralGCM project; genesis scale 365/41 because lead 1 is excluded |
| `GRID` | 1.5° | S2S archive resolution; default proposed 2026-10-18, not objected to |
| `n_boot` | 10000 | as in the neuralGCM reference figure |
| `--every` | 5 | ~37 forecasts per year, comparable to the neuralGCM one-year figure (73 forecasts) |
| projection | PlateCarree(central_longitude=205) | Pacific-centred, as the reference |

## 6. Edge Cases & Error Handling
- **The denominator includes zero-storm forecasts** (from `members`). Undeliverable
  archives are excluded from both numerator and denominator.
- **IBTrACS 6-hourly genesis vs model daily genesis.** Model genesis time can be up to a day
  later than the true formation.
- **IBTrACS years are calendar years** matching the hdate span. Model targets of late-year
  hdates spill into the following year.
- **Run from `scripts/`** (sibling imports).

## Open items
- `MODEL_TS_KT` = 30 kt is ad hoc. Decision: keep it, or adopt a principled rule
  (quantile matching with a basin-consistent observed q, a fixed 18%, or per-cycle matching
  for multi-cycle use).
- At 30 kt, N Atlantic and E N Pacific are still about half of IBTrACS (7.5 and 9.5 vs
  16.4/yr), while the SH and WNP are over. Decision: is the AL/EP deficit a model property
  to document, or worth checking with all tracked storms?

## 7. Synchronization Log
| date | code change | spec updated |
|---|---|---|
| 2026-10-18 | created; production run n_boot = 10000 on the ECMWF 2025 model_date year | created |
| 2026-10-18 | model TS threshold: 34 kt → LMI quantile matching (24 kt) → ad hoc `MODEL_TS_KT` = 30 kt; IBTrACS LMI quantile printed as a diagnostic | Algorithm 2–5, Constants, Open items |
| 2026-10-18 | no code change; added the second line of evidence for 30 kt (pooled event frequency, neuralGCM comparison) | Constants |

## Verification snippet
```python
import sys; sys.path.insert(0, "scripts")
import sanity_plots as s
p, m = s.load_model("ecmwf", 2025)
gen, pts, q_model = s.model_events(p, s.MODEL_TS_KT)
assert gen.lead_days.between(2, 42).all() and (pts.wind_kt >= s.MODEL_TS_KT).all()
assert gen.storm_uid.is_unique
rate = len(gen) / len(m) * 365 / 41
assert 40 < rate < 100, rate   # global storms per year
ig, ip, q = s.load_ibtracs(list(range(2005, 2025)))
assert (ig.basin != "other").all() and (ip.ISO_TIME.dt.hour == 0).all()
print(f"ok: model {rate:.1f}/yr, IBTrACS {len(ig) / 20:.1f}/yr")
```
