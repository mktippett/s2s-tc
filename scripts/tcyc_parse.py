"""Parser for TCYC S2S tropical-cyclone track archives (nested tar -> per-basin HURDAT-like text).

Outer file  TC.<model>.<hdate>.<model_date>   tar of members  <center>.<model_date>.<hdate>.<member>
Member file tar of 8 basin text files: atl enp cnp wnp nin sin aus spc

Format details verified against data (see docs/tcyc_format.md), not just the TCTRACK documentation.
"""
import io
import re
import tarfile

import pandas as pd

HEADER = re.compile(r"^(\d{5}) (\d\d)/(\d\d)/(\d{4}) M=\s*(\d+)\s+(\d+) SNBR=\s*(\d+)\s*$")
# point:  LLLLL YYYY/MM/DD/HH*LATLON_ WWW PPPP*  0   0   (lat 3 chars, lon 4 chars, fixed width)
POINT = re.compile(r"^(\d{5}) (\d{4})/(\d\d)/(\d\d)/(\d\d)\*(.{3})(.{4})(.{4})(.{5})\*(.*)$")
TRAILER = re.compile(r"^(\d{5})\s+([A-Z]{2}\d?)\s*$")  # TD, TS, HR, HR1..HR5 (digit undocumented)


def parse_basin_text(text):
    """Parse one basin file. Returns (storms, points): lists of dicts. Raises on any unparsed line."""
    storms, points, cur = [], [], None
    for ln, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        if m := HEADER.match(line):
            if cur is not None and "category" not in cur:
                raise ValueError(f"line {ln}: header before trailer")
            seq, dd, mm, yyyy, n, c1, c2 = m.groups()
            cur = dict(first_date=f"{yyyy}-{mm}-{dd}", n_points=int(n), c1=int(c1), snbr=int(c2), line0=int(seq))
            if cur["n_points"] == 0:  # empty basin placeholder: 00000 00/00/0000 M= 0  0 SNBR=   0
                cur = None
                continue
            storms.append(cur)
        elif m := POINT.match(line):
            seq, y, mo, d, h, lat, lon, wind, pres, rest = m.groups()
            points.append(dict(snbr=cur["snbr"], time=f"{y}-{mo}-{d}T{h}", lat_raw=lat, lon_raw=lon,
                               wind=int(wind), pres=int(pres), tail=rest.strip()))
        elif m := TRAILER.match(line):
            cur["category"] = m.group(2)
        else:
            raise ValueError(f"line {ln}: unparsed {line!r}")
    return storms, points


def parse_outer(fileobj):
    """Parse an outer TC.* archive.

    Returns (members, storms, points) DataFrames. `members` has one row per ensemble member
    present in the archive (including members with no storms) so that "no TCs forecast"
    is distinguishable from "forecast missing". Member numbers are returned raw.
    """
    M, S, P = [], [], []
    with tarfile.open(fileobj=fileobj) as outer:
        for mem in outer.getmembers():
            center, model_date, hdate, member = mem.name.split(".")
            tag = dict(center=center, model_date=model_date, hdate=hdate, member_raw=int(member))
            n_storms, basins = 0, []
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile(mem).read())) as inner:
                for b in inner.getmembers():
                    storms, points = parse_basin_text(inner.extractfile(b).read().decode("ascii"))
                    basins.append(b.name)
                    n_storms += len(storms)
                    S += [{**tag, "basin": b.name, **s} for s in storms]
                    P += [{**tag, "basin": b.name, **p} for p in points]
            M.append({**tag, "n_storms": n_storms, "basins": ",".join(sorted(basins))})
    return pd.DataFrame(M), pd.DataFrame(S), pd.DataFrame(P)
