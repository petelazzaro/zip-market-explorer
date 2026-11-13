"""
Mortgage Distress layer - build script.

Inputs (not committed; see README):
  raw/cfpb/StateMortgagesPercent-30-89DaysLate-thru-YYYY-MM.csv
  raw/cfpb/StateMortgagesPercent-90-plusDaysLate-thru-YYYY-MM.csv
  raw/cfpb/CountyMortgagesPercent-30-89DaysLate-thru-YYYY-MM.csv
  raw/cfpb/CountyMortgagesPercent-90-plusDaysLate-thru-YYYY-MM.csv
      CFPB Mortgage Performance Trends, "Download the data" (newest files are used).
  raw/census/tab20_zcta520_county20_natl.txt
      Census 2020 ZCTA-to-county relationship file.

Outputs:
  site/d/cfpb_delinquency.json  - 30-89 and 90+ day delinquency rates for the US, states, counties
  site/d/zip_to_county.json     - each zip's primary county (largest land overlap) + overlap %

    python scripts/build_cfpb.py

Exits non-zero if any validation check fails. Run it after build.py (which clears site/d).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build import STATE_FIPS  # noqa: E402  (shared state FIPS -> postal code map)

RAW_CFPB = ROOT / "raw" / "cfpb"
REL_FILE = ROOT / "raw" / "census" / "tab20_zcta520_county20_natl.txt"
OUT = ROOT / "site" / "d"
SCALE = 10          # rates are published to 0.1 percentage point; stored as round(rate * 10)
problems: list[str] = []
warnings: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def newest(pattern: str) -> Path | None:
    files = sorted(RAW_CFPB.glob(pattern), key=lambda p: re.findall(r"thru-(\d{4}-\d{2})", p.name) or [""])
    return files[-1] if files else None


def read_cfpb(path: Path, key_col_name: str) -> tuple[pd.DataFrame, list[str]]:
    """Wide CFPB file -> (rows with clean FIPS, list of YYYY-MM month columns)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    months = [c for c in df.columns if re.fullmatch(r"\d{4}-\d{2}", c)]
    df["fips"] = df["FIPSCode"].str.replace("'", "", regex=False).str.strip()
    for m in months:
        df[m] = pd.to_numeric(df[m].str.strip(), errors="coerce")
    log(f"  read {path.name}: {len(df)} rows, {len(months)} months ({months[0]} -> {months[-1]})")
    return df, months


def enc(values) -> str:
    return ",".join("" if pd.isna(v) else str(int(round(float(v) * SCALE))) for v in values)


def main() -> int:
    log(f"Mortgage Distress build - {datetime.now():%Y-%m-%d %H:%M}")
    files = {
        ("state", "d30"): newest("StateMortgagesPercent-30-89DaysLate-thru-*.csv"),
        ("state", "d90"): newest("StateMortgagesPercent-90-plusDaysLate-thru-*.csv"),
        ("county", "d30"): newest("CountyMortgagesPercent-30-89DaysLate-thru-*.csv"),
        ("county", "d90"): newest("CountyMortgagesPercent-90-plusDaysLate-thru-*.csv"),
    }
    missing = [f"{lvl} {k}" for (lvl, k), p in files.items() if p is None]
    if missing or not REL_FILE.exists():
        log(f"FAIL: missing inputs: {missing + ([] if REL_FILE.exists() else [REL_FILE.name])}")
        return 1
    thru = {re.search(r"thru-(\d{4}-\d{2})", p.name).group(1) for p in files.values()}
    if len(thru) != 1:
        problems.append(f"CFPB files end in different months: {sorted(thru)}")

    log("Reading CFPB files")
    data, months = {}, None
    for key, path in files.items():
        df, m = read_cfpb(path, "FIPSCode")
        if months is None:
            months = m
        elif m != months:
            problems.append(f"{path.name} month columns differ from the other files")
        data[key] = df
    if problems:
        return report()

    out = {"source": "CFPB Mortgage Performance Trends (National Mortgage Database)",
           "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "months": [int(m.replace("-", "")) for m in months], "scale": SCALE,
           "us": {}, "states": {}, "counties": {}}

    # ---- national + states
    for k in ("d30", "d90"):
        st = data[("state", k)]
        nat = st[st["RegionType"] == "National"]
        if len(nat) != 1:
            problems.append(f"state {k} file: expected 1 National row, found {len(nat)}")
            continue
        out["us"]["n"] = "United States"
        out["us"][k] = enc(nat.iloc[0][months])
        for _, r in st[st["RegionType"] == "State"].iterrows():
            ab = STATE_FIPS.get(r["fips"])
            if not ab:
                warnings.append(f"unknown state FIPS {r['fips']} ({r['Name']})")
                continue
            out["states"].setdefault(ab, {"n": r["Name"], "fips": r["fips"]})[k] = enc(r[months])

    # ---- counties
    for k in ("d30", "d90"):
        co = data[("county", k)]
        for _, r in co[co["RegionType"] == "County"].iterrows():
            f = r["fips"].zfill(5)
            out["counties"].setdefault(f, {"n": r["Name"], "st": r["State"]})[k] = enc(r[months])
    incomplete = [f for f, v in out["counties"].items() if "d30" not in v or "d90" not in v]
    if incomplete:
        warnings.append(f"{len(incomplete)} counties appear in only one of the two county files")

    # ---- zip -> primary county
    log("Reading Census ZCTA-to-county relationship file")
    rel = pd.read_csv(REL_FILE, sep="|", dtype=str, encoding="utf-8-sig")
    rel = rel[rel["GEOID_ZCTA5_20"].fillna("").str.len() == 5].copy()
    rel["land"] = pd.to_numeric(rel["AREALAND_PART"], errors="coerce").fillna(0)
    rel["water"] = pd.to_numeric(rel["AREAWATER_PART"], errors="coerce").fillna(0)
    rel["zland"] = pd.to_numeric(rel["AREALAND_ZCTA5_20"], errors="coerce").fillna(0)
    # Largest land overlap wins; total area breaks ties (and handles water-only ZCTAs).
    rel = rel.sort_values(["GEOID_ZCTA5_20", "land", "water"], ascending=[True, False, False])
    n_counties = rel.groupby("GEOID_ZCTA5_20").size()
    prim = rel.drop_duplicates("GEOID_ZCTA5_20").set_index("GEOID_ZCTA5_20")
    z2c = {}
    for z, r in prim.iterrows():
        pct = 100.0 * r["land"] / r["zland"] if r["zland"] > 0 else 100.0
        z2c[z] = [r["GEOID_COUNTY_20"], int(round(pct)), int(n_counties[z])]
    log(f"  {len(z2c):,} zips; {sum(1 for v in z2c.values() if v[2] > 1):,} span more than one county")
    with_cfpb = sum(1 for v in z2c.values() if v[0] in out["counties"])
    ct = sum(1 for v in z2c.values() if v[0].startswith("09"))

    # ---- write
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, obj in (("cfpb_delinquency.json", out), ("zip_to_county.json", z2c)):
        s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        (OUT / name).write_text(s, encoding="utf-8")
        sizes[name] = len(s.encode("utf-8"))

    # ---- validation: re-read raw CSVs with the csv module and compare the latest month
    log("Validation")
    last = months[-1]
    li = len(months) - 1

    def raw_value(path: Path, region: str, fips: str | None) -> float | None:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                f = (r.get("FIPSCode") or "").replace("'", "").strip()
                if r["RegionType"] == region and (fips is None or f == fips):
                    v = (r.get(last) or "").strip()
                    return float(v) if v else None
        return None

    def out_value(rec: dict, k: str) -> float | None:
        v = rec[k].split(",")[li]
        return None if v == "" else int(v) / SCALE

    checks = [("National", None, out["us"], "United States"),
              ("State", "12", out["states"].get("FL"), "Florida"),
              ("State", "25", out["states"].get("MA"), "Massachusetts"),
              ("County", "12011", out["counties"].get("12011"), "Broward County, FL"),
              ("County", "25017", out["counties"].get("25017"), "Middlesex County, MA"),
              ("County", "13089", out["counties"].get("13089"), "DeKalb County, GA")]
    for region, fips, rec, label in checks:
        if rec is None:
            problems.append(f"spot check: {label} missing from output")
            continue
        parts = []
        for k, lvl in (("d30", "state" if region != "County" else "county"),
                       ("d90", "state" if region != "County" else "county")):
            rv = raw_value(files[(lvl, k)], region, fips)
            ov = out_value(rec, k)
            ok = (rv is None and ov is None) or (rv is not None and ov is not None and abs(rv - ov) < 1e-9)
            parts.append(f"{k}={ov} vs raw {rv} {'ok' if ok else 'MISMATCH'}")
            if not ok:
                problems.append(f"spot check {label} {k}: output {ov} != raw {rv}")
        log(f"  {label} @ {last}: " + "; ".join(parts))
    for z, want in (("30084", "13089"), ("33067", "12011"), ("02139", "25017")):
        got = z2c.get(z)
        log(f"  zip {z} -> {got}")
        if not got or got[0] != want:
            problems.append(f"zip {z} expected primary county {want}, got {got}")

    log("")
    log("=" * 64)
    log("MORTGAGE DISTRESS BUILD REPORT")
    log("=" * 64)
    log(f"CFPB months: {len(months)} ({months[0]} -> {months[-1]})")
    log(f"Series: US + {len(out['states'])} states + {len(out['counties'])} counties (CFPB publishes counties with >= 1,000 sampled mortgages)")
    log(f"Zips mapped: {len(z2c):,}; primary county has CFPB data: {with_cfpb:,}; Connecticut zips (old county codes, fall back to state): {ct}")
    for k, v in sizes.items():
        log(f"  {k}: {v / 1e6:.2f} MB")
    return report()


def report() -> int:
    for w in warnings:
        log(f"WARNING: {w}")
    for p in problems:
        log(f"FAIL: {p}")
    log("FAILED" if problems else "OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
