"""
Redfin closed-sales data for the Zip Market Explorer build (imported by build.py).

Source: Redfin Data Center "Housing Market Tracker" downloads in raw/Redfin/ (All Residential,
monthly; one file per geography, a level may be split into several date-range files):
    redfin_housing_market_monthly_all_{country,states,metros,counties,zips}_<range>.csv

- Only rows with IS SEASONALLY ADJUSTED = false are used (consistent with realtor.com).
- Each period goes on our month axis by its period-end month. Zip rows are Redfin's
  rolling 3-month periods (e.g. Aug 1 - Oct 31 -> Oct); they're kept as-is and labelled in the UI.
- Percent columns are stored as fractions (x10000), like realtor.com's price_reduced_share.

Geography matching (stage 1 profile, Nov 2026): zips by number; states by name (DC is "Columbia");
counties by normalized name + state with a fixed table of exceptions; metros by principal city +
state. Redfin splits the 11 CBSAs that have metropolitan divisions into those divisions, so those
metros get no Redfin series (their counties and zips do).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

# short key -> Redfin column. Values are stored as round(value * scale).
RS_SRC = {
    "rs_p": "MEDIAN SALE PRICE NSA ($)",
    "rs_f": "MEDIAN SALE PRICE PER SQ.FT. ($)",
    "rs_n": "HOMES SOLD",
    "rs_pend": "PENDING SALES",
    "rs_mos": "MONTHS OF SUPPLY",
    "rs_dom": "MEDIAN DAYS ON MARKET (DAYS)",
    "rs_sl": "AVERAGE SALE TO LIST RATIO (%)",
    "rs_ab": "SHARE SOLD ABOVE LIST (%)",
    "rs_off2": "PERCENT OFF MARKET IN TWO WEEKS (%)",
}
RS_PCT = {"rs_sl", "rs_ab", "rs_off2"}          # Redfin gives percents; stored as fractions
RS_SCALE = {"rs_mos": 10, "rs_sl": 10000, "rs_ab": 10000, "rs_off2": 10000}
# encode() reads df[col] * scale; after read_redfin() the columns are named by their short keys.
RS_ENC = {k: (k, RS_SCALE.get(k, 1)) for k in RS_SRC}
RS_SCR = {k: RS_ENC[k] for k in ("rs_p", "rs_n", "rs_mos", "rs_sl")}   # screener subset

FILES = {"us": "country", "state": "states", "metro": "metros", "county": "counties", "zip": "zips"}

# CBSAs with metropolitan divisions (OMB 2023). Redfin reports their divisions, not the whole metro.
SPLIT_METROS = {
    "14460": "Boston", "16980": "Chicago", "19100": "Dallas", "19820": "Detroit", "31080": "Los Angeles",
    "33100": "Miami", "35620": "New York", "37980": "Philadelphia", "41860": "San Francisco",
    "42660": "Seattle", "47900": "Washington",
}

# Redfin county name -> county FIPS, where names alone don't line up (stage 1 misses).
COUNTY_FIPS = {
    "Dona Ana County, NM": "35013",       # realtor.com's name has a garbled ñ
    "Carson City, NV": "32510",
    "Charles City County, VA": "51036",
    "James City County, VA": "51095",
    "La Salle Parish, LA": "22059",
    "Juneau Borough, AK": "02110",
    "Sitka Borough, AK": "02220",
    "Wrangell Borough, AK": "02275",
    # independent cities ("X City County" in Redfin) vs the county of the same name
    "Baltimore City County, MD": "24510",
    "St. Louis City County, MO": "29510",
    "Richmond City County, VA": "51760",
    "Roanoke City County, VA": "51770",
    "Fairfax City County, VA": "51600",
    "Franklin City County, VA": "51620",
}
STATE_ALIASES = {"Columbia": "DC", "District of Columbia": "DC"}

_SUFFIX = re.compile(r"\s+(county|parish|borough|census area|city and borough|municipality|municipio)$")


def fold(s: str) -> str:
    """Lower-case, accents and punctuation off, '&' -> 'and', 'saint' -> 'st'."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ").replace(".", "").replace("'", "").replace("’", "")
    s = re.sub(r"^saint\s+", "st ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_st(name: str) -> tuple[str, str]:
    i = str(name).rfind(",")
    return (name[:i].strip(), name[i + 1:].strip()) if i >= 0 else (str(name).strip(), "")


def files_for(raw: Path, level: str) -> list[Path]:
    """All files for a level, oldest first, so a newer date-range file wins on overlapping months."""
    found = {p.resolve() for d in {raw / "Redfin", raw / "redfin"} if d.exists()
             for p in d.glob(f"redfin_housing_market_monthly_all_{FILES[level]}_*.csv")}
    return sorted(found, key=lambda p: p.stat().st_mtime)


def read_redfin(raw: Path, level: str, months: list[int], log, warnings: list, problems: list) -> pd.DataFrame | None:
    """Unadjusted rows for one level: columns REGION NAME, month, rs_* (scaled to stored units / fractions)."""
    files = files_for(raw, level)
    if not files:
        warnings.append(f"no Redfin {FILES[level]} file in raw/Redfin - closed-sales data skipped for {level}")
        return None
    use = ["PERIOD END", "REGION NAME", "IS SEASONALLY ADJUSTED"] + list(RS_SRC.values())
    keep = set(months)
    parts = []
    for f in files:
        header = pd.read_csv(f, nrows=0).columns.tolist()
        missing = [c for c in use if c not in header]
        if missing:
            problems.append(f"{f.name}: missing columns {missing}")
            continue
        for ch in pd.read_csv(f, usecols=use, dtype=str, chunksize=500_000,
                              keep_default_na=False, na_values=["", "NA"]):
            ch = ch[ch["IS SEASONALLY ADJUSTED"].str.strip().str.lower() == "false"]
            end = pd.to_datetime(ch["PERIOD END"], errors="coerce")
            month = end.dt.year * 100 + end.dt.month
            ok = month.isin(keep)
            ch = ch[ok].copy()
            ch["month"] = month[ok].astype(int)
            for k, col in RS_SRC.items():
                v = pd.to_numeric(ch[col], errors="coerce")
                ch[k] = v / 100 if k in RS_PCT else v
            parts.append(ch[["REGION NAME", "month"] + list(RS_SRC)])
        log(f"  read {f.name}")
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    df["REGION NAME"] = df["REGION NAME"].astype(str).str.strip()
    dupes = int(df.duplicated(["REGION NAME", "month"]).sum())
    if dupes:   # overlapping date-range files: the newest file (read last) wins
        df = df.drop_duplicates(["REGION NAME", "month"], keep="last")
        log(f"  {level}: dropped {dupes:,} duplicate months from overlapping Redfin files")
    return df


# ---------------------------------------------------------------- geography matching
def map_us(df: pd.DataFrame) -> dict[str, str]:
    return {n: "us" for n in df["REGION NAME"].unique() if n.lower() == "national"}


def map_states(df: pd.DataFrame, state_names: dict[str, str]) -> dict[str, str]:
    by_name = {fold(n): k for k, n in state_names.items()}
    out = {}
    for n in df["REGION NAME"].unique():
        k = STATE_ALIASES.get(n) or by_name.get(fold(n))
        if k:
            out[n] = k
    return out


def map_counties(df: pd.DataFrame, county_names: dict[str, str], warnings: list) -> dict[str, str]:
    """county_names: fips -> our display name ('Dekalb, GA')."""
    ours: dict[tuple[str, str], list[str]] = {}
    for fips, name in county_names.items():
        p, st = split_st(name)
        ours.setdefault((_SUFFIX.sub("", fold(p)), st), []).append(fips)
    out, ambiguous = {}, []
    for n in df["REGION NAME"].unique():
        if n in COUNTY_FIPS:
            if COUNTY_FIPS[n] in county_names:
                out[n] = COUNTY_FIPS[n]
            continue
        p, st = split_st(n)
        cands = ours.get((_SUFFIX.sub("", fold(p)), st), [])
        if len(cands) > 1:   # e.g. Richmond County vs Richmond city, VA: a plain county has a code below 500
            cands = [f for f in cands if int(f[2:]) < 500]
        if len(cands) == 1:
            out[n] = cands[0]
        elif len(cands) > 1:
            ambiguous.append(n)
    if ambiguous:
        warnings.append(f"Redfin counties with ambiguous names, skipped: {ambiguous}")
    return out


def _metro_cities(place: str) -> list[str]:
    cities = [c for c in re.split(r"[-/]+", place) if c.strip()]
    return [re.sub(r"^(urban|town of)\s+", "", fold(c)) for c in cities]


def map_metros(df: pd.DataFrame, metro_names: dict[str, str], warnings: list) -> dict[str, str]:
    """metro_names: cbsa -> CBSA title ('Atlanta-Sandy Springs-Roswell, GA'). First pass matches the
    first principal city + first state; a second pass tries the other principal cities."""
    first, anyc = {}, {}
    for code, title in metro_names.items():
        if code in SPLIT_METROS:
            continue
        p, st = split_st(title)
        cities, st2 = _metro_cities(p), st[:2]
        if cities:
            first.setdefault((cities[0], st2), []).append(code)
            for c in cities[1:]:
                anyc.setdefault((c, st2), []).append(code)
    out, used = {}, set()
    names = [n for n in df["REGION NAME"].unique()]
    keyed = {}
    for n in names:
        p, st = split_st(re.sub(r"\s+metro area$", "", n, flags=re.I))
        cities = _metro_cities(p)
        if cities:
            keyed[n] = (cities[0], st[:2])
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
    return out


def attach_ids(df: pd.DataFrame | None, mapping: dict[str, str], level: str, log) -> pd.DataFrame | None:
    """Keep matched regions, keyed by our id in column _id. Two Redfin regions on one id is a bug."""
    if df is None or not mapping:
        return None
    out = df[df["REGION NAME"].isin(mapping)].copy()
    out["_id"] = out["REGION NAME"].map(mapping)
    clash = out.groupby("_id")["REGION NAME"].nunique()
    clash = clash[clash > 1]
    if len(clash):
        raise ValueError(f"Redfin {level}: several Redfin regions map to one place: {list(clash.index)[:10]}")
    log(f"  Redfin {level}: {out['_id'].nunique():,} places matched ({df['REGION NAME'].nunique():,} Redfin regions)")
    return out


def raw_latest(raw: Path, level: str, region_name: str, month: int) -> dict[str, str] | None:
    """The raw (unadjusted) row for one region and period-end month, straight from the CSV text."""
    want = f"{month // 100:04d}-{month % 100:02d}"
    hit = None
    for f in files_for(raw, level):
        for ch in pd.read_csv(f, usecols=["PERIOD END", "REGION NAME", "IS SEASONALLY ADJUSTED"] + list(RS_SRC.values()),
                              dtype=str, chunksize=500_000, keep_default_na=False):
            m = ch[(ch["REGION NAME"].str.strip() == region_name) & ch["PERIOD END"].str.startswith(want)
                   & (ch["IS SEASONALLY ADJUSTED"].str.strip().str.lower() == "false")]
            if len(m):
                hit = m.iloc[-1].to_dict()
    return hit
