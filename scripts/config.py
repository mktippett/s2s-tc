"""Shared constants for the S2S TC-track curation project."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INVENTORY = ROOT / "data" / "inventory"
TRACKS = ROOT / "data" / "tracks"

BASINS = ["atl", "enp", "cnp", "wnp", "nin", "sin", "aus", "spc"]
SH_BASINS = {"sin", "aus", "spc"}  # latitude stored unsigned (see docs/tcyc_format.md)
# Larger basin groups that share the header C1 counter. Storms crossing between groups are
# written to both groups' files (docs/tcyc_format.md); within a group there are no duplicates.
BASIN_GROUP = {"atl": "NA", "enp": "NP", "cnp": "NP", "wnp": "NP", "nin": "NI",
               "sin": "SH", "aus": "SH", "spc": "SH"}
DUP_DEG = 0.5  # co-location radius (deg, lat/lon difference with lon wrap) for duplicate points

EMPTY_TAR_SIZE = 10240  # outer archive with no members

# ECMWF extended-range cycle history (implementation date, cycle), from
# https://confluence.ecmwf.int/display/S2S/ECMWF+Model (retrieved 2026-10-18).
# Not recorded in the track files; assigned by model_date >= implementation date.
ECMWF_CYCLES = pd.DataFrame(
    [("2015-01-01", "CY40R1"), ("2015-05-14", "CY41R1"), ("2016-03-08", "CY41R2"),
     ("2016-11-22", "CY43R1"), ("2017-07-11", "CY43R3"), ("2018-06-06", "CY45R1"),
     ("2019-06-11", "CY46R1"), ("2020-06-30", "CY47R1"), ("2021-05-11", "CY47R2"),
     ("2021-10-13", "CY47R3"), ("2023-06-27", "CY48R1"), ("2024-11-12", "CY49R1"),
     ("2026-05-13", "CY50R1")],
    columns=["implemented", "cycle"],
).assign(implemented=lambda d: pd.to_datetime(d.implemented))


def ecmwf_cycle(model_date):
    """Cycle operational on each model_date (Series of datetimes -> Series of str)."""
    idx = ECMWF_CYCLES.implemented.searchsorted(model_date, side="right") - 1
    if (idx < 0).any():
        raise ValueError("model_date before first tabulated cycle")
    return pd.Series(ECMWF_CYCLES.cycle.to_numpy()[idx], index=getattr(model_date, "index", None))
