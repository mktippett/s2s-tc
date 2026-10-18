"""Sanity-check figures for one center's consolidated reforecast tracks against IBTrACS.

Usage (from scripts/): python sanity_plots.py ecmwf 2025 [--hdate-year 2005] [--n-boot 10000]

Writes plots/<center>/sanity_*_md<year>.png (exploratory, non-production: the method
details go in the suptitles):
  01  one hdate year, one member, tracks coloured by max wind
  02  genesis density, model vs IBTrACS
  03  track density, model vs IBTrACS
  04  monthly genesis count by source basin

Definitions (see README "Sanity plots"):
- Storms count only if lifetime max wind >= 34 kt (model and IBTrACS alike).
- Model genesis = first track point. Storms whose first point is at lead 1 are dropped,
  since storms present at initialization first appear at lead 1 (no lead-0 point).
  Genesis rates use leads 2-42 and are scaled by 365/41; track-point rates use leads
  1-42 and 365/42. Both are averaged over all forecasts in members_<year>.
- Cross-group duplicates (dup_* flags) are counted once: a storm whose first point is
  co-located with a partner that started earlier (or at the same time with a smaller
  storm_uid) is not a genesis, and of a pair of co-located points only the one on the
  smaller storm_uid is kept.
- IBTrACS: v04r01, TRACK_TYPE main, NATURE TS, USA_WIND >= 34 kt, synoptic hours.
  Genesis = first such point (6-hourly); track density uses 00Z points only (daily, as
  the model). Basins are mapped to the TCYC regions (docs/tcyc_format.md).
"""
import argparse

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from scipy.ndimage import gaussian_filter1d

from config import BASINS, ROOT, TRACKS

OBS = ROOT / "data" / "obs" / "ibtracs.since1980.list.v04r01.csv"
MAP_CRS = ccrs.PlateCarree(central_longitude=205)  # Pacific-centred display
CENTER_LON = 205
EXTENT_LAT = (-45, 45)
GRID = 1.5  # deg, density bins (S2S archive resolution)
TS_KT = 34
LEAD_MAX = 42
BASIN_LABELS = {"atl": "N Atlantic", "enp": "E N Pacific", "cnp": "Central Pacific",
                "wnp": "W N Pacific", "nin": "N Indian", "sin": "S Indian",
                "aus": "Australian", "spc": "S Pacific"}


# --------------------------------------------------------------------------- data
def load_model(center, year):
    p = pd.read_parquet(TRACKS / f"{center}_reforecasts" / f"points_{year}.parquet",
                        columns=["model_cycle", "init_time", "member", "basin", "storm_uid",
                                 "point_num", "valid_time", "lead_days", "lat", "lon360",
                                 "wind_kt", "dup_point", "dup_of", "source_file"])
    for c in ["basin", "storm_uid", "dup_of", "model_cycle"]:
        p[c] = p[c].astype(str)
    m = pd.read_parquet(TRACKS / f"{center}_reforecasts" / f"members_{year}.parquet")
    return p, m


def dedup(p):
    """Return (genesis_ok per storm_uid, point keep mask) implementing the duplicate rule."""
    first = p[p.point_num == 0].set_index("storm_uid")
    start = first.valid_time
    gen_ok = pd.Series(True, index=first.index)
    dup_first = first[first.dup_point]
    for uid, partners in dup_first.dup_of.items():
        for o in partners.split(";"):
            if start[o] < start[uid] or (start[o] == start[uid] and o < uid):
                gen_ok[uid] = False
    # co-located points: keep only those on the smallest uid of the pair
    smallest = p.dup_of.str.split(";").map(min, na_action="ignore")
    keep = ~p.dup_point | (p.storm_uid < smallest)
    return gen_ok, keep


def model_events(p):
    """Genesis rows (one per counted storm) and track points for storms reaching 34 kt."""
    gen_ok, keep = dedup(p)
    maxw = p.groupby("storm_uid").wind_kt.max()
    ts_storms = maxw.index[maxw >= TS_KT]
    first = p[p.point_num == 0].set_index("storm_uid")
    gen = first.loc[first.index.isin(ts_storms) & gen_ok.reindex(first.index).to_numpy()]
    gen = gen[gen.lead_days.between(2, LEAD_MAX)]
    pts = p[keep & p.storm_uid.isin(ts_storms) & (p.wind_kt >= TS_KT) & (p.lead_days <= LEAD_MAX)]
    return gen.reset_index(), pts


def ibtracs_basin(df):
    """Map IBTrACS BASIN + location to the TCYC basin regions (docs/tcyc_format.md)."""
    lon = df.lon360
    return np.select(
        [df.BASIN == "NA", (df.BASIN == "EP") & (lon >= 220), df.BASIN == "EP",
         df.BASIN == "WP", df.BASIN == "NI",
         df.BASIN.isin(["SI", "SP"]) & (lon < 90),
         df.BASIN.isin(["SI", "SP"]) & (lon < 160), df.BASIN.isin(["SI", "SP"])],
        ["atl", "enp", "cnp", "wnp", "nin", "sin", "aus", "spc"], default="other")


def load_ibtracs(years):
    df = pd.read_csv(OBS, skiprows=[1], keep_default_na=False, low_memory=False,
                     usecols=["SID", "BASIN", "ISO_TIME", "NATURE", "TRACK_TYPE", "LAT", "LON", "USA_WIND"])
    df["ISO_TIME"] = pd.to_datetime(df.ISO_TIME)
    df["USA_WIND"] = pd.to_numeric(df.USA_WIND, errors="coerce")
    df = df[(df.TRACK_TYPE == "main") & (df.NATURE == "TS") & (df.USA_WIND >= TS_KT)
            & df.ISO_TIME.dt.hour.isin([0, 6, 12, 18]) & (df.ISO_TIME.dt.minute == 0)
            & df.ISO_TIME.dt.year.isin(years)].copy()
    df["lat"] = df.LAT.astype(float)
    df["lon360"] = df.LON.astype(float) % 360
    df["basin"] = ibtracs_basin(df)
    gen = df.sort_values("ISO_TIME", kind="stable").drop_duplicates("SID")
    pts = df[df.ISO_TIME.dt.hour == 0]
    print(f"IBTrACS {min(years)}-{max(years)}: {len(gen)} storms >= {TS_KT} kt; "
          f"genesis basin 'other' (e.g. S Atlantic): {(gen.basin == 'other').sum()}")
    return gen, pts


# --------------------------------------------------------------------------- helpers
def grid_edges():
    return np.arange(0, 360 + GRID, GRID), np.arange(-60, 60 + GRID, GRID)


def density(lon360, lat):
    xe, ye = grid_edges()
    H, _, _ = np.histogram2d(lon360, lat, bins=[xe, ye])
    return H.T  # (lat, lon)


def add_map(ax):
    ax.set_extent([-180, 180, *EXTENT_LAT], crs=MAP_CRS)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.4, edgecolor="0.3")
    gl = ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.4)
    gl.top_labels = gl.right_labels = False
    gl.xlabel_style = gl.ylabel_style = {"size": 7}


def pcolor(ax, H, **kw):
    xe, ye = grid_edges()
    return ax.pcolormesh(xe, ye, np.ma.masked_equal(H, 0) if kw.pop("mask0", False) else H,
                         transform=ccrs.PlateCarree(), **kw)


def density_figure(H_mod, H_obs, title, cbar_label, out, cmap, shared_scale):
    fig = plt.figure(figsize=(13, 6.2), layout="constrained")
    axs = [fig.add_subplot(2, 2, i + 1, projection=MAP_CRS) for i in range(3)]
    ax_prof = fig.add_subplot(2, 2, 4)
    for ax in axs:
        add_map(ax)
    cm = plt.get_cmap(cmap).copy()
    cm.set_under("white")
    v_mod, v_obs = 0.9 * H_mod.max(), 0.9 * H_obs.max()
    if shared_scale:
        v_mod = v_obs = np.sqrt(v_mod * v_obs)
    for ax, H, v, lab in [(axs[0], H_mod, v_mod, f"(a) model ({H_mod.sum():.1f}/yr)"),
                          (axs[1], H_obs, v_obs, f"(b) IBTrACS ({H_obs.sum():.1f}/yr)")]:
        im = pcolor(ax, H, cmap=cm, norm=mpl.colors.Normalize(vmin=v / 1000, vmax=v))
        ax.set_title(lab, fontsize=10)
        fig.colorbar(im, ax=ax, shrink=0.85, label=cbar_label)
    D = H_mod - H_obs
    vl = 0.9 * np.abs(D).max()
    im = pcolor(axs[2], D, cmap="RdBu_r", norm=mpl.colors.TwoSlopeNorm(0, -vl, vl))
    axs[2].set_title("(c) model − IBTrACS", fontsize=10)
    fig.colorbar(im, ax=axs[2], shrink=0.85, label=cbar_label)
    # (d) sum over latitude per hemisphere, smoothed 2 grid points, plotted on map longitudes
    xe, ye = grid_edges()
    xc, yc = 0.5 * (xe[1:] + xe[:-1]), 0.5 * (ye[1:] + ye[:-1])
    xplot = (xc - CENTER_LON + 180) % 360 - 180 + CENTER_LON  # unwrap to the map's longitude span
    order = np.argsort(xplot)
    for H, color, name in [(H_mod, "steelblue", "model"), (H_obs, "tomato", "IBTrACS")]:
        for sel, ls, hemi in [(yc >= 0, "-", "NH"), (yc < 0, "--", "SH")]:
            prof = gaussian_filter1d(H[sel].sum(axis=0), 2, mode="wrap")
            ax_prof.plot(xplot[order], prof[order], color=color, ls=ls, lw=1.4, label=f"{name} {hemi}")
    ax_prof.set_xlim(CENTER_LON - 180, CENTER_LON + 180)
    ticks = np.arange(60, 390, 60)
    ax_prof.set_xticks(ticks, [f"{t % 360:.0f}°E" if t % 360 <= 180 else f"{360 - t % 360:.0f}°W" for t in ticks])
    ax_prof.set_ylabel(cbar_label)
    ax_prof.set_title("(d) sum over latitude (smoothed σ = 2 cells)", fontsize=10)
    ax_prof.legend(fontsize=7)
    ax_prof.grid(alpha=0.3)
    fig.suptitle(title, fontsize=10)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------- figures
def fig_tracks(p, hdate_year, every, out):
    """One hdate year, member 0, every `every`-th start date; all tracked storms."""
    sel = p[(p.init_time.dt.year == hdate_year) & (p.member == 0)]
    inits = np.sort(sel.init_time.unique())[::every]
    sel = sel[sel.init_time.isin(inits)].sort_values(["storm_uid", "valid_time"])
    x = (sel.lon360 - CENTER_LON + 180) % 360 - 180  # MAP_CRS coordinates
    segs, vals = [], []
    for (_, xs), (_, ys), (_, ws) in zip(x.groupby(sel.storm_uid), sel.lat.groupby(sel.storm_uid),
                                         sel.wind_kt.groupby(sel.storm_uid)):
        xs, ys, ws = xs.to_numpy(), ys.to_numpy(), ws.to_numpy()
        for i in range(len(xs) - 1):
            if abs(xs[i + 1] - xs[i]) < 180:  # skip segments crossing the map seam
                segs.append([(xs[i], ys[i]), (xs[i + 1], ys[i + 1])])
                vals.append(0.5 * (ws[i] + ws[i + 1]))
    fig = plt.figure(figsize=(13, 4.2), layout="constrained")
    ax = fig.add_subplot(projection=MAP_CRS)
    add_map(ax)
    ax.add_feature(cfeature.LAND, facecolor="0.92", zorder=0)
    lc = LineCollection(segs, array=np.asarray(vals), cmap="Spectral_r", linewidths=0.8,
                        norm=mpl.colors.Normalize(10, 80), transform=MAP_CRS)
    ax.add_collection(lc)
    fig.colorbar(lc, ax=ax, shrink=0.9, label="max wind (kt)", extend="max")
    cyc = ",".join(sorted(sel.model_cycle.unique()))
    fig.suptitle(f"ECMWF {cyc} reforecast tracks: {len(inits)} starts in hdate year {hdate_year} "
                 f"(every {every}th start date), member 0, {sel.storm_uid.nunique()} storms "
                 f"(all tracked, incl. TD); leads 1–46 d, daily", fontsize=10)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("wrote", out)


def fig_monthly(gen, n_fcst, ibt_gen, years, n_boot, out, cyc):
    rng = np.random.default_rng(0)
    months = np.arange(1, 13)
    mod = (gen.groupby([gen.basin, gen.valid_time.dt.month]).size()
           .unstack(fill_value=0).reindex(index=BASINS, columns=months, fill_value=0)) / n_fcst * 365 / (LEAD_MAX - 1)
    ym = (ibt_gen.groupby([ibt_gen.basin, ibt_gen.ISO_TIME.dt.year.rename("year"), ibt_gen.ISO_TIME.dt.month.rename("month")])
          .size().rename("n").reset_index())
    fig, axs = plt.subplots(2, 4, figsize=(15, 6.5), layout="constrained")
    for ax, b in zip(axs.flat, BASINS):
        tab = (ym[ym.basin == b].pivot(index="year", columns="month", values="n")
               .reindex(index=years, columns=months, fill_value=0).fillna(0))
        obs = tab.mean()
        boot = np.stack([tab.to_numpy()[rng.integers(0, len(years), len(years))].mean(axis=0) for _ in range(n_boot)])
        lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
        w = 0.4
        ax.bar(months - w / 2, mod.loc[b], w, color="steelblue", alpha=0.85, label="model")
        ax.bar(months + w / 2, obs, w, color="tomato", alpha=0.85, label="IBTrACS")
        ax.errorbar(months + w / 2, obs, yerr=[obs - lo, hi - obs], fmt="none", ecolor="k", elinewidth=0.8, capsize=1.5)
        ax.set_title(f"{BASIN_LABELS[b]} ({b}): model {mod.loc[b].sum():.1f}, obs {obs.sum():.1f} /yr", fontsize=9)
        ax.set_xticks(months, list("JFMAMJJASOND"), fontsize=8)
        ax.set_ylabel("storms / month")
        ax.legend(fontsize=7, loc="upper right" if b in ("sin", "aus", "spc") else "upper left")
    fig.suptitle(f"Monthly TC genesis by basin, ECMWF {cyc} reforecasts (hdates {min(years)}–{max(years)}) vs IBTrACS. "
                 f"Storms reaching ≥{TS_KT} kt; model: first point at leads 2–{LEAD_MAX} d, mean over {n_fcst} forecasts × 365/{LEAD_MAX - 1}, "
                 f"month of genesis; IBTrACS: first ≥{TS_KT} kt point, 95% CI from {n_boot} bootstrap resamples of years",
                 fontsize=9, wrap=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("wrote", out)


def main(center, year, hdate_year, every, n_boot):
    out = ROOT / "plots" / center
    out.mkdir(parents=True, exist_ok=True)
    p, m = load_model(center, year)
    n_fcst = len(m)
    cyc = ",".join(sorted(m.model_cycle.astype(str).unique()))
    years = list(range(p.init_time.dt.year.min(), p.init_time.dt.year.max() + 1))

    fig_tracks(p, hdate_year, every, out / f"sanity_01_tracks_md{year}_h{hdate_year}_m00.png")

    gen, pts = model_events(p)
    ibt_gen, ibt_pts = load_ibtracs(years)
    print(f"model: {len(gen)} genesis events, {len(pts)} track points >= {TS_KT} kt over {n_fcst} forecasts")

    common = (f"ECMWF {cyc} reforecasts (model_date year {year}, hdates {min(years)}–{max(years)}, "
              f"{n_fcst} forecasts) vs IBTrACS {min(years)}–{max(years)}\nstorms reaching ≥{TS_KT} kt; "
              f"{GRID}° bins, no map smoothing; cross-basin duplicates counted once")
    H_mod = density(gen.lon360, gen.lat) / n_fcst * 365 / (LEAD_MAX - 1)
    H_obs = density(ibt_gen.lon360, ibt_gen.lat) / len(years)
    density_figure(H_mod, H_obs,
                   f"TC genesis density. {common}.\nModel genesis = first track point at leads 2–{LEAD_MAX} d "
                   f"(lead-1 starts dropped), ×365/{LEAD_MAX - 1}; IBTrACS genesis = first ≥{TS_KT} kt 6-hourly point",
                   "storms yr⁻¹", out / f"sanity_02_genesis_density_md{year}.png", "YlOrRd", shared_scale=False)

    H_mod = density(pts.lon360, pts.lat) / n_fcst * 365 / LEAD_MAX
    H_obs = density(ibt_pts.lon360, ibt_pts.lat) / len(years)
    density_figure(H_mod, H_obs,
                   f"TC track density. {common}.\nPoints with wind ≥{TS_KT} kt: model daily 00Z at leads 1–{LEAD_MAX} d, "
                   f"×365/{LEAD_MAX}; IBTrACS 00Z points (daily, as the model). Shared colour scale for (a), (b)",
                   "storm-days yr⁻¹", out / f"sanity_03_track_density_md{year}.png", "Blues", shared_scale=True)

    fig_monthly(gen, n_fcst, ibt_gen, years, n_boot, out / f"sanity_04_monthly_genesis_md{year}.png", cyc)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("center")
    ap.add_argument("year", type=int, help="model_date year")
    ap.add_argument("--hdate-year", type=int, default=2005)
    ap.add_argument("--every", type=int, default=5, help="track map: every n-th start date")
    ap.add_argument("--n-boot", type=int, default=10000)
    a = ap.parse_args()
    main(a.center, a.year, a.hdate_year, a.every, a.n_boot)
