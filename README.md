# PipeWatch Nigeria

A web GIS dashboard that shows where oil and gas pipelines in the Niger Delta are attacked most, so UAV and
ground patrols can be sent there first. It is built on spill records from the National Oil Spill Detection and
Response Agency (NOSDRA) and pipeline routes from OpenStreetMap.

**Live dashboard:** https://johnedet12.github.io/pipewatch-nigeria/

**Technical documentation:** [PDF](docs/PipeWatch%20Nigeria%20Technical%20Documentation.pdf) · [Word](docs/PipeWatch%20Nigeria%20Technical%20Documentation.docx)

## What it shows

- Pipeline segments of up to 5 km, coloured by sabotage spills within 3 km
- A 5 km sabotage hotspot grid and individual spill points
- Rankings of named pipelines, segments and hotspot cells, with a 12-month trend
- UAV sorties ranked by sabotage spills per km, with an out-and-back flight time
- Filters for period, cause, state, operator and asset type, plus a time slider on the map

## How the data stays current

`pipeline.py` downloads the NOSDRA Oil Spill Monitor bulk feed, keeps confirmed or reviewed records from 2015
onward with coordinates in the Niger Delta, removes duplicates, names the line at each spill, snaps spills to
OpenStreetMap pipeline segments and writes `data.json`.

- **Online:** a GitHub Actions workflow (`.github/workflows/sync.yml`) runs the pipeline every 6 hours, commits
  the refreshed `data.json` and redeploys the site to GitHub Pages.
- **Locally:** `python server.py --port 8095 --interval 6` serves the dashboard at http://127.0.0.1:8095 and
  syncs on the same schedule. Python 3.10+ with no extra packages.

To refresh the cached OpenStreetMap pipeline geometry, run `python pipeline.py --osm`.

## Limitations

- Causes and volumes are reported by operators and confirmed through Joint Investigation Visits. A blank
  quantity means unknown, not zero.
- Recent months are likely undercounted because records are added over time.
- OpenStreetMap does not map every line. Lines it does not map (including Tebidaba–Brass) are drawn as
  approximate dashed traces through their own spill sites, not surveyed centrelines.
- The data records spills. Attacks that cause no recorded spill are missing.

## Sources

- Spill records: NOSDRA, Nigerian Oil Spill Monitor (https://oilspillmonitor.ng)
- Basemap and pipeline routes: © OpenStreetMap contributors, ODbL 1.0
- Fallback outline: Natural Earth (public domain)
- Map library: Leaflet 1.9.4 (BSD-2-Clause)
