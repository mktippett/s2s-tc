"""Parse raw TCYC reforecast archives for one model_date year into analysis-ready parquet.

Usage: python scripts/consolidate.py ecmwf reforecasts 2025

Writes data/tracks/<model>_<stream>/
  points_<year>.parquet   one row per track point
  members_<year>.parquet  one row per (model_date, init_time, member) present, with n_storms;
                          a forecast with zero storms appears here but not in points
Format invariants (docs/tcyc_format.md) are asserted; soft diagnostics are printed.
"""
import sys

import numpy as np
import pandas as pd

from config import BASIN_GROUP, DUP_DEG, EMPTY_TAR_SIZE, INVENTORY, RAW, SH_BASINS, TRACKS, ecmwf_cycle
from tcyc_parse import parse_outer

# HRn lower bounds (kt) as observed in the data: 1 kt below standard Saffir-Simpson (83/96/113/137)
# for HR2-HR4; HR5 (136) inferred from that pattern, not yet observed
SS_THRESH = [(5, 136), (4, 112), (3, 95), (2, 82), (1, 64)]


def expected_category(maxw):
    """Category implied by lifetime-max wind: TD <35, TS 35-63, HR >=64 (TCTRACK doc)."""
    return np.select([maxw < 35, maxw < 64], ["TD", "TS"], "HR")


def ss_category(maxw):
    return np.select([maxw >= t for _, t in SS_THRESH], [c for c, _ in SS_THRESH], 0)


def normalise_members(m):
    """Map raw member numbers to 0..n-1 per archive.

    Some archives number members 11*k + m (docs/ecmwf.md); require each archive's raw
    numbers to be one contiguous block starting at a multiple of the block size.
    """
    g = m.groupby("source_file").member_raw
    base, n = g.transform("min"), g.transform("count")
    contiguous = g.transform(lambda x: (np.sort(x.to_numpy()) == x.min() + np.arange(len(x))).all())
    assert contiguous.all() and (base % n == 0).all(), "non-contiguous member block"
    return m.member_raw - base


def flag_duplicates(p):
    """Flag storms written to files of two basin groups (flag only, nothing dropped).

    Points are co-located when same archive, member and valid_time, in different basin
    groups, within DUP_DEG. Adds dup_point (bool), and per storm dup_of (partner
    storm_uid(s), ';'-joined, '' if none) and dup_type (this storm relative to partner:
    identical | contained | contains | partial).
    """
    a = p[["source_file", "member", "valid_time", "storm_uid", "basin", "lat", "lon360"]].assign(
        grp=lambda d: d.basin.astype(str).map(BASIN_GROUP), row=np.arange(len(p)))
    q = a.merge(a, on=["source_file", "member", "valid_time"], suffixes=("", "_o"))
    q = q[q.grp != q.grp_o]
    q = q[np.hypot(q.lat - q.lat_o, (q.lon360 - q.lon360_o + 180) % 360 - 180) < DUP_DEG]
    p["dup_point"] = np.isin(np.arange(len(p)), q.row.to_numpy())
    pairs = q.groupby(["storm_uid", "storm_uid_o"]).size().rename("shared").reset_index()
    n = p.storm_uid.value_counts()
    full_self, full_other = pairs.shared == pairs.storm_uid.map(n), pairs.shared == pairs.storm_uid_o.map(n)
    pairs["dup_type"] = np.select([full_self & full_other, full_self, full_other],
                                  ["identical", "contained", "contains"], "partial")
    per = pairs.groupby("storm_uid").agg(dup_of=("storm_uid_o", ";".join), dup_type=("dup_type", ";".join))
    p["dup_of"] = p.storm_uid.map(per.dup_of).fillna("")
    p["dup_type"] = p.storm_uid.map(per.dup_type).fillna("")
    print(f"duplicates: {p.dup_point.sum()} points, {len(per)} storms "
          f"({len(per) / n.size:.2%}); pair types {pairs.dup_type.value_counts().to_dict()}")
    return p


def main(model, stream, year):
    inv = pd.read_parquet(INVENTORY / f"{model}_{stream}.parquet")
    inv = inv[inv.name.str.startswith("TC.") & inv.path.str.startswith(f"TCYC/{model}/{stream}/{year}/")]
    n_empty = (inv["size"] == EMPTY_TAR_SIZE).sum()
    inv = inv[inv["size"] > EMPTY_TAR_SIZE]
    # archives the server could not deliver (download.py failure record) are absent, so those
    # forecasts are missing from members_<year> too; any other missing file is an error
    fail_csv = INVENTORY / f"{model}_{stream}_failed_{year}.csv"
    failed = set(pd.read_csv(fail_csv).path) if fail_csv.exists() else set()
    present = [(RAW / p.removeprefix("TCYC/")).exists() for p in inv.path]
    missing = set(inv.path[[not x for x in present]])
    assert missing <= failed, f"missing raw files not in {fail_csv.name}: {sorted(missing - failed)[:5]}"
    if missing:
        print(f"{year}: skipping {len(missing)} undeliverable archives: {sorted(missing)}")
    inv = inv[present]

    M, S, P = [], [], []
    for path in inv.path:
        local = RAW / path.removeprefix("TCYC/")
        hdate, model_date = local.name.split(".")[-2:]
        with open(local, "rb") as f:
            m, s, p = parse_outer(f)
        assert (m.model_date == model_date).all() and (m.hdate == hdate).all(), f"inner names {local}"
        rel = str(local.relative_to(RAW))
        for df in (m, s, p):
            df["source_file"] = rel
        M.append(m), S.append(s), P.append(p)
    m, s, p = pd.concat(M, ignore_index=True), pd.concat(S, ignore_index=True), pd.concat(P, ignore_index=True)
    print(f"{year}: {len(inv)} archives (+{n_empty} empty skipped), {len(m)} members, "
          f"{len(s)} storms, {len(p)} points")

    # --- members ---
    m["member"] = normalise_members(m)
    n_mem = m.groupby("source_file").size()
    print("members per archive:", n_mem.value_counts().to_dict(),
          "| archives with offset member numbers:", (m.groupby("source_file").member_raw.min() > 0).sum())
    print("basin sets:", m.basins.value_counts().to_dict())
    p = p.merge(m[["source_file", "member_raw", "member"]], on=["source_file", "member_raw"])
    s = s.merge(m[["source_file", "member_raw", "member"]], on=["source_file", "member_raw"])

    # --- hard invariants ---
    key = ["source_file", "member", "basin", "snbr"]
    p["valid_time"] = pd.to_datetime(p.time, format="%Y-%m-%dT%H")
    p["init_time"] = pd.to_datetime(p.hdate, format="%Y%m%d")
    p["model_date"] = pd.to_datetime(p.model_date, format="%Y%m%d")
    assert (p.init_time.dt.strftime("%m%d") == p.model_date.dt.strftime("%m%d")).all()
    assert (p.valid_time.dt.hour == 0).all(), "non-00Z point"
    assert (p["tail"] == "0   0").all(), "unexpected trailing fields"
    p = p.sort_values(key + ["valid_time"], ignore_index=True)
    rows = p.groupby(key).size()
    st = s.set_index(key)
    assert (st.n_points == rows.reindex(st.index)).all(), "M= != rows"
    assert (st.first_date == p.groupby(key).valid_time.min().dt.strftime("%Y-%m-%d").reindex(st.index)).all()
    assert not p.duplicated(key + ["valid_time"]).any(), "duplicate time in track"
    g = s.groupby(["source_file", "member", "basin"]).snbr
    assert ((g.min() == 1) & (g.max() == g.count())).all(), "SNBR not 1..N"
    maxw = p.groupby(key).wind.max().reindex(st.index)
    assert (st.category.str[:2] == expected_category(maxw)).all(), "category vs max wind"

    # --- soft diagnostics ---
    digit = st.category.str.extract(r"^HR(\d)$")[0].astype(float)
    ss_bad = digit.notna() & (digit != ss_category(maxw))
    print("trailer categories:", st.category.value_counts().to_dict(),
          "| HRn inconsistent with Saffir-Simpson:", int(ss_bad.sum()))
    print("SH-basin points with '-' in raw lat:", int((p.basin.isin(SH_BASINS) & p.lat_raw.str.contains("-")).sum()),
          "| NH-basin points with '-':", int((~p.basin.isin(SH_BASINS) & p.lat_raw.str.contains("-")).sum()))

    # --- derived columns ---
    lat = pd.to_numeric(p.lat_raw.str.strip()) / 10
    p["lat"] = np.where(p.basin.isin(SH_BASINS), -lat, lat).astype("float32")
    lon360 = pd.to_numeric(p.lon_raw.str.strip()) / 10  # arithmetic in float64, cast at the end
    assert lon360.between(0, 360).all()
    p["lon360"] = lon360.astype("float32")
    p["lon"] = (((lon360 + 180) % 360) - 180).astype("float32")
    p["lead_days"] = (p.valid_time - p.init_time).dt.days.astype("int16")
    print("lead_days range:", p.lead_days.min(), p.lead_days.max(),
          "| step days:", p.groupby(key).valid_time.diff().dt.days.value_counts().sort_index().to_dict())
    p["center"] = model
    p["model_cycle"] = ecmwf_cycle(p.model_date).to_numpy()
    p = p.merge(s[key + ["category", "c1"]], on=key)
    p = p.rename(columns={"snbr": "storm_num", "wind": "wind_kt", "pres": "mslp_hpa"})
    p["storm_uid"] = (model + "." + p.model_date.dt.strftime("%Y%m%d") + "." + p.init_time.dt.strftime("%Y%m%d")
                      + ".m" + p.member.astype(str).str.zfill(2) + "." + p.basin + "." + p.storm_num.astype(str).str.zfill(3))
    p["point_num"] = p.groupby("storm_uid").cumcount().astype("int16")
    p = flag_duplicates(p)
    cols = ["center", "model_cycle", "model_date", "init_time", "member", "basin", "storm_num", "c1",
            "storm_uid", "point_num", "valid_time", "lead_days", "lat", "lon", "lon360",
            "wind_kt", "mslp_hpa", "category", "dup_point", "dup_of", "dup_type", "source_file"]
    p = p[cols].astype({"member": "int8", "storm_num": "int16", "c1": "int16",
                        "wind_kt": "int16", "mslp_hpa": "int16"})
    for c in ["center", "model_cycle", "basin", "category", "dup_type", "source_file"]:
        p[c] = p[c].astype("category")

    m["model_date"] = pd.to_datetime(m.model_date, format="%Y%m%d")
    m["init_time"] = pd.to_datetime(m.hdate, format="%Y%m%d")
    m["center"] = model
    m["model_cycle"] = ecmwf_cycle(m.model_date).to_numpy()
    m["n_members"] = m.groupby("source_file").member.transform("count").astype("int8")
    m = m[["center", "model_cycle", "model_date", "init_time", "member", "member_raw", "n_members",
           "n_storms", "source_file"]].sort_values(["model_date", "init_time", "member"], ignore_index=True)

    out = TRACKS / f"{model}_{stream}"
    out.mkdir(parents=True, exist_ok=True)
    p.to_parquet(out / f"points_{year}.parquet", index=False)
    m.to_parquet(out / f"members_{year}.parquet", index=False)
    print("cycles:", m.groupby("model_cycle", observed=True).model_date.agg(["min", "max", "nunique"]).to_string())
    print("wrote", out / f"points_{year}.parquet", len(p), "rows;", out / f"members_{year}.parquet", len(m), "rows")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
