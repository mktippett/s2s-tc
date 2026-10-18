# download.py (and inventory.py)

## 1. Purpose
Mirror the raw TCYC track archives for one center/stream and model_date year from the ECMWF
FTP server into `data/raw/`, resumably and with bounded load on a free public server.
`inventory.py` produces the file list this works from.

## 2. Inputs
| file | relevant content | filters |
|---|---|---|
| FTP `aux.ecmwf.int:/TCYC/<center>/<stream>/` | Unix `LIST` output (no MLSD) | `inventory.py` walks all subdirectories |
| `data/inventory/<center>_<stream>.parquet` | `path`, `size`, `name`, parsed `hdate`, `model_date` | name starts `TC.`; path under `<year>/` |

## 3. Outputs
| file | contents | format |
|---|---|---|
| `data/inventory/<center>_<stream>.parquet` | one row per FTP file: path, size, raw mtime string, name, hdate, model_date | parquet (`inventory.py`) |
| `data/raw/<path below TCYC/>` | byte-identical copy of each archive | raw tar |
| `data/inventory/<center>_<stream>_failed_<year>.csv` | path, size, last error of archives that failed every attempt (overwritten each run) | csv |

## 4. Algorithm
1. To-do list = inventory files for the year with no local copy of the inventory size.
2. Split the list into `workers` interleaved shards; each thread holds one FTP connection.
3. Each file: RETR to `<name>.part`, check size equals the inventory size, then rename.
   On any FTP or socket error: close the connection, sleep 5·attempt s, reconnect, retry.
4. After `FILE_ATTEMPTS` failures, delete the `.part` file, record the file in the failure
   list, and continue with the next file, so one bad file cannot block a shard.
5. Write the failure CSV. Exit 1 if any file failed.

## 5. Constants & Scientific Rationale
| name | value | why |
|---|---|---|
| `--workers` default | 8 | throughput is latency-bound (~0.9 files/s per connection) and scales linearly to ≥24 in short tests; 8 chosen by the user 2026-10-18 as a polite load. Use 4 if refusals recur |
| `FILE_ATTEMPTS` | 3 | some files fail persistently with a server-side `java.rmi.ServerException` (5 in 2023), while transient refusals clear on retry |
| backoff | 5·attempt s | short; transient refusals cleared within one retry in practice |

## 6. Edge Cases & Error Handling
- **Empty placeholder tars** (10,240 B) are mirrored too, so `data/raw` is a complete copy.
- **The inventory is a snapshot.** The server keeps adding model_dates (2026 is growing), so
  re-run `inventory.py` before downloading a current year.
- **LIST mtimes** have no year for recent files; they are kept as raw strings and are not
  used. FTP mtimes are upload times, not production times.
- **Interrupted runs** leave `.part` files. These are never mistaken for complete files, and
  are overwritten on rerun.

## Open items
- Downloads paused after 2023 at the user's request. Remaining: model_date years
  2015–2022 and 2026 (~4.3 GB). Decision: when to resume, at 8 or 4 workers.
- 5 undeliverable 2023 archives (`ecmwf_reforecasts_failed_2023.csv`). Decision: retry
  later, or accept them as missing.

## 7. Synchronization Log
| date | code change | spec updated |
|---|---|---|
| 2026-10-18 | created: LIST-based inventory; resumable mirror; 8 parallel workers; per-file retries with failure record | created |

## Verification snippet
```python
import pandas as pd
from pathlib import Path
y = 2025
inv = pd.read_parquet("data/inventory/ecmwf_reforecasts.parquet")
inv = inv[inv.name.str.startswith("TC.") & inv.path.str.contains(f"/reforecasts/{y}/")]
f = Path(f"data/inventory/ecmwf_reforecasts_failed_{y}.csv")
failed = set(pd.read_csv(f).path) if f.exists() else set()
bad = [p for p, s in zip(inv.path, inv["size"])
       if p not in failed and (not (q := Path("data/raw") / p.removeprefix("TCYC/")).exists() or q.stat().st_size != s)]
assert not bad, bad[:5]
assert not list(Path("data/raw").rglob("*.part"))
print("ok", len(inv), "files,", len(failed), "recorded failures")
```
