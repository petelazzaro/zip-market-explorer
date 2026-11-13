# Zip Market Explorer

**Live site:** https://petelazzaro.github.io/zip-market-explorer/

A static web app for exploring realtor.com listing-market data for any US **zip, county, metro, state, or the US as a whole**. It shows summary tiles, a market read, rankings within the state, ten charts and a monthly table. Every metric can be smoothed with a trailing average whose window (1–24 months) you type in.

## Data

- **Source:** realtor.com Data Library → Inventory → Core Metrics, monthly **History** files (Jul 2016 → latest month).
- **Current build:** Jul 2016 – Oct 2026 (built Nov 2026). It covers 34,271 zips, 3,142 counties, 925 metros, 50 states + DC, and the US.
- These are **listing** metrics (asking prices, active inventory, pending contracts), not closed sales.

## How it works

```
raw/*.csv  ──►  build.py  ──►  site/d/*.json  ──►  GitHub Pages (gh-pages branch)
```

- `build.py` reads the five History CSVs with pandas and writes compact JSON to `site/d/`:
  - `meta.json`: the month list and the search index.
  - `us.json` and `states.json`.
  - Shards for metros, counties and zips: `metro/`, `county/<state fips>/`, and `zip/<first 2 digits>/`.

  It then spot-checks values against the raw files and **fails if anything mismatches**.
- `site/index.html` is the whole app. It uses Chart.js 4 from cdnjs and loads only the data shard it needs.
- The `raw/` folder is never committed (the zip file alone is about 840 MB).
- The site data (about 210 MB) is published to the `gh-pages` branch, which is **replaced on every refresh**. Old monthly data never piles up in the repo's history. The `main` branch holds only the code.

## Monthly refresh

1. In the realtor.com Data Library, download the five monthly **History** files into `raw/`, replacing the old ones:
   - `RDC_Inventory_Core_Metrics_Zip_History.csv`
   - `RDC_Inventory_Core_Metrics_County_History.csv`
   - `RDC_Inventory_Core_Metrics_Metro_History.csv`
   - `RDC_Inventory_Core_Metrics_State_History.csv`
   - `RDC_Inventory_Core_Metrics_Country_History.csv`

   **Never open or save these in Excel.** It cuts off rows and strips leading zeros from zips. If your browser saves a file as `... (1).csv`, the build still finds it and reminds you to rename it.

2. In PowerShell, from this folder:

   ```powershell
   .\refresh.ps1
   ```

   The script builds the data, runs the validation report, commits any code changes to `main` with the message `Data refresh YYYY-MM`, and publishes `site/` to GitHub Pages. The live site updates within a few minutes.

   If PowerShell refuses to run the script, run this once:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Local testing

```powershell
python build.py                                   # full build (~1 min); add --quick to skip zips
python -m http.server 8765 --directory site       # then open http://localhost:8765
```

## Requirements

Python 3.12 + pandas, Git, and the GitHub CLI (`gh auth login`). Node is optional; it's only used for `node --check`.
