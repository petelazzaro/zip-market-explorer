"""
Zillow home values (ZHVI) and rents (ZORI) for the Zip Market Explorer build (imported by build.py).

Source: Zillow Research CSVs in raw/zillow/ (wide: id columns, then one column per month-end date):
    {Zip,County,Metro,State}_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv   typical home value
    {Zip,County,Metro}_zori_uc_sfrcondomfr_sm_month.csv                      typical asking rent
The Metro files also hold the United States row (RegionType = country). There is no state ZORI file;
the City ZORI file isn't used. ZHVI is smoothed and seasonally adjusted by Zillow; ZORI is smoothed.

Each month-end column goes on our month axis as yyyymm; months before the axis start are dropped.
Matching (stage 1 profile, Nov 2026): zips by number; counties by StateCodeFIPS + MunicipalCodeFIPS;
states by name; metros by principal city + state (Zillow names metros "Dayton, OH"). Zillow's
metro ZHVI file has no Dayton, OH or Poughkeepsie, NY rows, so those get rents only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from redfin import fold, split_st, _metro_cities

ZL_SCALE = {"zr": 100}                           # ZHVI whole dollars; ZORI to the cent (rents are small,
                                                 # so whole dollars would shift rent YoY by ~0.01 pt)
ZL_ENC = {k: (k, ZL_SCALE.get(k, 1)) for k in ("zv", "zr")}
PATTERN = {"zv": "{lvl}_zhvi_*.csv", "zr": "{lvl}_zori_*.csv"}
LEVEL_FILE = {"zip": "Zip", "county": "County", "metro": "Metro", "us": "Metro", "state": "State"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Zillow's files spell these with '±' where the 'ñ' should be.
NAME_FIX = {"Ca±on City, CO": "Canon City, CO", "Espa±ola, NM": "Espanola, NM"}


def zdir(raw: Path) -> Path | None:
    for d in (raw / "zillow", raw / "Zillow"):
        if d.exists():
            return d
    return None


def file_for(raw: Path, level: str, key: str) -> Path | None:
    d = zdir(raw)
    if d is None:
        return None
    hits = sorted(d.glob(PATTERN[key].format(lvl=LEVEL_FILE[level])), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def read_wide(path: Path, months: list[int]) -> pd.DataFrame:
    """Wide Zillow CSV -> long rows (id columns..., month, v) on our month axis, blanks dropped."""
    hdr = pd.read_csv(path, nrows=0).columns.tolist()
    dates = [c for c in hdr if DATE.match(c)]
    ids = [c for c in hdr if c not in dates]
    keep = set(months)
    use = [d for d in dates if int(d[:4]) * 100 + int(d[5:7]) in keep]
    df = pd.read_csv(path, usecols=ids + use, dtype={c: str for c in ids}, keep_default_na=False, na_values=[""])
    lg = df.melt(id_vars=ids, value_vars=use, var_name="date", value_name="v").dropna(subset=["v"])
    lg["month"] = lg["date"].str[:4].astype(int) * 100 + lg["date"].str[5:7].astype(int)
    lg["v"] = pd.to_numeric(lg["v"], errors="coerce")
    return lg.dropna(subset=["v"]).drop(columns=["date"])


def ids_for(level: str, lg: pd.DataFrame, names: dict[str, str]) -> pd.Series:
    """Our id for each long row (NaN when unmatched). names: our id -> display name/title."""
    if level == "us":
        return lg["RegionType"].where(lg["RegionType"] == "country").map({"country": "us"})
    if level == "zip":
        z = lg["RegionName"].str.strip().str.zfill(5)
        return z.where(z.isin(set(names)))
    if level == "county":
        f = lg["StateCodeFIPS"].str.strip().str.zfill(2) + lg["MunicipalCodeFIPS"].str.strip().str.zfill(3)
        return f.where(f.isin(set(names)))
    if level == "state":
        by = {fold(n): k for k, n in names.items()}
        return lg["RegionName"].map(lambda n: by.get(fold(n)))
    if level == "metro":
        first, anyc = {}, {}
        for code, title in names.items():
            p, st = split_st(title)
            cs = _metro_cities(p)
            if cs:
                first.setdefault((cs[0], st[:2]), []).append(code)
                for c in cs[1:]:
                    anyc.setdefault((c, st[:2]), []).append(code)
        msa = lg.loc[lg["RegionType"] == "msa", "RegionName"].unique()
        keyed = {}
        for n in msa:
            p, st = split_st(NAME_FIX.get(n, n))
            cs = _metro_cities(p)
            if cs:
                keyed[n] = (cs[0], st[:2])
        out, used = {}, set()
        for n, k in keyed.items():
            c = first.get(k, [])
            if len(c) == 1 and c[0] not in used:
                out[n] = c[0]
                used.add(c[0])
        for n, k in keyed.items():
            if n in out:
                continue
            c = [x for x in anyc.get(k, []) if x not in used]
            if len(c) == 1:
                out[n] = c[0]
                used.add(c[0])
        return lg["RegionName"].map(out).where(lg["RegionType"] == "msa")
    raise ValueError(level)


def read_zillow(raw: Path, level: str, months: list[int], names: dict[str, str], log, warnings: list) -> pd.DataFrame | None:
    """Both series for one level: columns _id, month, zv, zr (zr missing where there's no ZORI)."""
    parts = []
    for key in ("zv", "zr"):
        f = file_for(raw, level, key)
        if f is None:
            if not (level == "state" and key == "zr"):      # Zillow publishes no state ZORI
                warnings.append(f"no Zillow {'ZHVI' if key == 'zv' else 'ZORI'} file for {level} in raw/zillow")
            continue
        lg = read_wide(f, months)
        lg["_id"] = ids_for(level, lg, names)
        lg = lg.dropna(subset=["_id"])
        if lg.duplicated(["_id", "month"]).any():
            raise ValueError(f"Zillow {f.name}: several regions map to one place")
        parts.append(lg[["_id", "month", "v"]].rename(columns={"v": key}).set_index(["_id", "month"]))
        log(f"  read {f.name}: {lg['_id'].nunique():,} places matched")
    if not parts:
        return None
    df = pd.concat(parts, axis=1).reset_index()
    for key in ("zv", "zr"):
        if key not in df:
            df[key] = float("nan")
    return df


def raw_value(raw: Path, level: str, key: str, match, month: int) -> float | None:
    """The raw cell for one region and month-end, straight from the wide CSV (for spot checks).
    match: function(row dict) -> bool picking the region row."""
    f = file_for(raw, level, key)
    if f is None:
        return None
    hdr = pd.read_csv(f, nrows=0).columns.tolist()
    col = next((c for c in hdr if DATE.match(c) and int(c[:4]) * 100 + int(c[5:7]) == month), None)
    if col is None:
        return None
    ids = [c for c in hdr if not DATE.match(c)]
    df = pd.read_csv(f, usecols=ids + [col], dtype=str, keep_default_na=False)
    hit = df[df.apply(lambda r: match(r.to_dict()), axis=1)]
    if hit.empty or hit[col].iloc[0] == "":
        return None
    return float(hit[col].iloc[0])
