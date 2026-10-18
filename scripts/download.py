"""Mirror raw TCYC track archives for one model_date year to data/raw/.

Usage: python scripts/download.py ecmwf reforecasts 2025 [--workers 8]

Driven by the inventory (scripts/inventory.py). Resumable: a file is skipped when a
local copy with the inventory size exists. Downloads go to a .part file, renamed on
completion. Empty placeholder tars (10240 B) are mirrored too, so the raw tree is a
complete copy of the server.
"""
import argparse
import sys
import threading
import time
from ftplib import FTP, all_errors
from pathlib import Path

import pandas as pd

HOST, USER, PW = "aux.ecmwf.int", "s2sidx", "s2sidx"
ROOT = Path(__file__).resolve().parents[1]
FILE_ATTEMPTS = 3


def main(model, stream, year, workers=1):
    inv = pd.read_parquet(ROOT / "data" / "inventory" / f"{model}_{stream}.parquet")
    inv = inv[inv.name.str.startswith("TC.") & inv.path.str.startswith(f"TCYC/{model}/{stream}/{year}/")]
    # local path mirrors the FTP path below TCYC/
    inv["local"] = [ROOT / "data" / "raw" / p.removeprefix("TCYC/") for p in inv.path]
    todo = inv[[not (f.exists() and f.stat().st_size == s) for f, s in zip(inv.local, inv["size"])]]
    print(f"{year}: {len(inv)} files, {len(todo)} to fetch ({todo['size'].sum() / 1e6:.0f} MB)", flush=True)

    shards = [todo.iloc[i::workers] for i in range(workers)]
    done, failed = [0] * workers, []
    lock = threading.Lock()

    def fetch(i):
        """One FTP connection working through shard i.

        Each file gets FILE_ATTEMPTS tries (reconnecting between tries); a file that still
        fails is recorded and skipped, so one bad file cannot block the rest of the shard.
        The server returns a persistent java.rmi.ServerException for some files.
        """
        ftp = None
        for row in shards[i].itertuples():
            row.local.parent.mkdir(parents=True, exist_ok=True)
            part = row.local.with_name(row.local.name + ".part")
            for attempt in range(1, FILE_ATTEMPTS + 1):
                try:
                    if ftp is None:
                        ftp = FTP(HOST, timeout=120)
                        ftp.login(USER, PW)
                    with open(part, "wb") as f:
                        ftp.retrbinary(f"RETR {row.path}", f.write)
                    if part.stat().st_size != row.size:
                        raise OSError(f"size mismatch: {part.stat().st_size} != {row.size}")
                    part.rename(row.local)
                    done[i] += 1
                    with lock:
                        if sum(done) % 500 == 0:
                            print(f"  {sum(done)}/{len(todo)}", flush=True)
                    break
                except all_errors as e:
                    err = repr(e)[:160]
                    if ftp is not None:
                        ftp.close()
                    ftp = None
                    time.sleep(5 * attempt)
            else:
                part.unlink(missing_ok=True)
                with lock:
                    failed.append(dict(path=row.path, size=row.size, error=err))
                print(f"  worker {i}: giving up on {row.path} ({err})", flush=True)
        if ftp is not None:
            ftp.close()

    threads = [threading.Thread(target=fetch, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # failures of this run (overwritten each run; empty file when none)
    fail_csv = ROOT / "data" / "inventory" / f"{model}_{stream}_failed_{year}.csv"
    pd.DataFrame(failed, columns=["path", "size", "error"]).to_csv(fail_csv, index=False)
    print(f"{year}: fetched {sum(done)}/{len(todo)}, failed {len(failed)} (listed in {fail_csv.name})", flush=True)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model"); ap.add_argument("stream"); ap.add_argument("year", type=int)
    ap.add_argument("--workers", type=int, default=8, help="parallel FTP connections (8 tested 2026-10-18)")
    a = ap.parse_args()
    main(a.model, a.stream, a.year, a.workers)
