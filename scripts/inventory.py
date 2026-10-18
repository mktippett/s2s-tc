"""Walk the TCYC FTP tree for one model/stream and record every file (name, size, mtime).

Usage: python scripts/inventory.py ecmwf reforecasts
Writes data/inventory/<model>_<stream>.parquet
"""
import sys
from ftplib import FTP
from pathlib import Path

import pandas as pd

HOST, USER, PW = "aux.ecmwf.int", "s2sidx", "s2sidx"
ROOT = Path(__file__).resolve().parents[1]


def walk(ftp, path):
    """Yield (path, size, mtime) for every regular file below path.

    The server does not support MLSD; parse the Unix-style LIST output. mtime is
    kept as the raw LIST string (year omitted for recent files).
    """
    lines = []
    ftp.dir(path, lines.append)
    for line in lines:
        parts = line.split(None, 8)
        perms, size, mtime, name = parts[0], int(parts[4]), " ".join(parts[5:8]), parts[8]
        if perms.startswith("d"):
            yield from walk(ftp, f"{path}/{name}")
        elif perms.startswith("-"):
            yield f"{path}/{name}", size, mtime


def main(model, stream):
    with FTP(HOST, timeout=120) as ftp:
        ftp.login(USER, PW)
        rows = [dict(path=p, size=size, mtime=mtime)
                for p, size, mtime in walk(ftp, f"TCYC/{model}/{stream}")]
    df = pd.DataFrame(rows)
    df["name"] = df.path.str.rsplit("/", n=1).str[-1]
    m = df.name.str.extract(r"^TC\.(?P<m>[a-z0-9]+)\.(?P<hdate>\d{8})\.(?P<model_date>\d{8})$")
    df["hdate"] = pd.to_datetime(m.hdate, format="%Y%m%d")
    df["model_date"] = pd.to_datetime(m.model_date, format="%Y%m%d")
    out = ROOT / "data" / "inventory" / f"{model}_{stream}.parquet"
    df.to_parquet(out, index=False)
    print(out, len(df), "files;", df.hdate.isna().sum(), "unparsed names")


if __name__ == "__main__":
    main(*sys.argv[1:3])
