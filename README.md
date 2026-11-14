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

## Mortgage Distress layer (v02)

A county-level panel with the share of mortgages 30–89 days and 90+ days delinquent, compared with the state and the US.

- **Data:** CFPB Mortgage Performance Trends (National Mortgage Database). This build covers Jan 2008 – Mar 2026, published Nov 2026. CFPB publishes only counties with at least 1,000 mortgages in its sample (509 counties). Elsewhere the panel says so and shows the state series.
- **Zip → county:** the Census 2020 ZCTA-to-county relationship file. Each zip uses the county with the largest land-area overlap, and the panel shows that overlap % when a zip spans several counties.
- **Script:** `scripts/build_cfpb.py` reads `raw/cfpb/` and `raw/census/` and writes `site/d/cfpb_delinquency.json` and `site/d/zip_to_county.json`, with spot checks against the raw CSVs. `refresh.ps1` runs it automatically after `build.py`.
- **Known gap:** Connecticut. CFPB uses CT's 2022 planning regions, but the Census 2020 file still uses the old counties, so CT zips show the state series.

**When CFPB publishes new data (roughly quarterly):**
1. Go to consumerfinance.gov → Mortgage Performance Trends → Download the data. Under "The most recent data", download the **States** and **Counties** CSVs for both "30–89 days" and "90 or more days" into `raw/cfpb/`. The build uses the newest `thru-YYYY-MM` files.
2. Run `.\refresh.ps1` as usual.

The Census file (`raw/census/tab20_zcta520_county20_natl.txt`) only changes once a decade.

## realtor.com links

Each place has a **Homes for sale on realtor.com ↗** button in the explorer header, and a ⌂ icon on each screener row. Both open realtor.com's search for that area in a new tab. On a phone with the realtor.com app installed, the link usually opens in the app. Listings can't be shown inside this site: realtor.com has no public listings feed and blocks embedding, and showing listings directly would need an MLS/IDX license.

- **How each place maps to a realtor.com search:**
  - Zip: `/realestateandhomes-search/30084`
  - County: `DeKalb-County_GA` (`-Parish` in Louisiana, and Alaska boroughs/census areas as named)
  - State: `Georgia` (DC goes to `Washington_DC`)
  - Metro: its first-named city, e.g. `Atlanta_GA`, because realtor.com has no metro search.
- realtor.com blocks automated checks, so these formats were built from its standard search URLs and should be click-tested after any change.

## Screener (v04)

The **Explorer | Screener** toggle at the top (link: `#screener`) switches to a ranked table of every state, metro, county or zip.

- **Controls:** level, state filter, minimum average active listings (default 25), median price min/max, and show top 50/100/250. The trailing-average box and window are shared with the explorer. Search, compare, benchmark and "show monthly values" are hidden in this mode.
- **Figures:** every column is the N-month trailing average. Every YoY compares that average with the same window 12 months earlier, exactly like the explorer tiles (shares in points). The files hold the last 24 months, so YoY needs a window of 12 months or less.
- **Columns:** name, state, median price, $/sq ft, active listings, new listings, median DOM, price-reduced share, price-reduced count and pending ratio, each with its YoY, plus a market score. Click a header to sort, and click again to flip.
- **Market score:** the explorer's six market-read signals, with a Seller / Balanced / Buyer pill. The benchmark is the parent state for zips and counties, and the US for states and metros. In the explorer, a metro is compared with its state, so a metro's score can differ between the two views.
- **Presets** set the sort only:
  - **Levels:** highest/lowest price, highest $/sq ft, most inventory, most new listings, most price cuts, highest price-cut share, highest pending ratio, selling fastest, slowest selling.
  - **Changes:** price cuts rising fastest, biggest inventory build, fastest price gains, prices falling, cooling fastest, hottest.
- **Other actions:** clicking a row opens that place in the explorer. "Copy table as CSV" copies the rows shown.
- **Data:** `build.py` writes `site/d/scr/<level>.json` as `{start, keys, rows: {id: [name, state, series...]}}`. These hold the last 24 months of price, $/sq ft, active, new and pending listings, DOM, price-reduced share, **price-reduced count** (screener only) and pending ratio. Scaling is the same as the explorer files, and each series is delta-encoded (each value minus the previous non-blank one). Only places with active listings in the last 3 months are included. The build logs each file's rows and size, and spot-checks the screener rows for zip 30084, county 13089 and Georgia against the raw CSV.
- **Size (Oct 2026 build):** zip 21.4 MB on disk / 7.8 MB as served (GitHub Pages gzips JSON), county 2.5 MB, metro 0.8 MB, state 0.05 MB. Each level loads only when it's selected.

## Location map (v03)

A map card under the place name zooms to the selected area and draws its outline in gold. A dashed outline gives context: a zip's main county, or the state of a county or metro. A comparison place is outlined in violet.

- **Outlines** are fetched live from the US Census TIGERweb service when you open a place: 2020 zip-code tabulation areas (ZCTAs) for zips, and current county, metro/micro area and state boundaries. Nothing is added to the build or the repo, and there's nothing to refresh.
- **Pick on the map:** zoom in past about city level and every zip in view is outlined in teal (hover for its number and town). Click any spot and a menu lists the zip, county, metro and state there that have realtor.com data. Choose one to open it. This uses Census point and area lookups, also live.
- **Basemap:** Esri dark gray canvas tiles (no API key needed). The map library is Leaflet 1.9.4 from cdnjs.
- **Known gap:** about 1,800 of the 34,271 zips (PO-box and single-building zips) have no Census area. For those, the map shows the county or state and says why.

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
python scripts/build_cfpb.py                      # Mortgage Distress layer (run after build.py)
python -m http.server 8765 --directory site       # then open http://localhost:8765
```

## Requirements

Python 3.12 + pandas, Git, and the GitHub CLI (`gh auth login`). Node is optional; it's only used for `node --check`.
