# Final report — architecture document

`final_report.tex` is the D7065E architecture document, written to the course template
(`D7065E-buildsim/lab-assignment/final_report_template`) and guide.

| Path | What it is |
|---|---|
| `final_report.tex` / `.pdf` | The report source and compiled PDF |
| `diagrams/*.d2` | C4 and behaviour diagrams as D2 source |
| `figures/*.pdf` | Diagrams rendered to vector PDF; `figures/*.png` are screenshots |
| `data/` | Measured data behind every chart and number in Section 11; `data/raw/` holds the container logs they were computed from |
| `experiments/` | Scripts that produced `data/` (see below) |
| `svg2pdf.py` | Prints D2's SVG output to page-sized PDF with headless Chrome |

## Build

With TeX Live installed: `make`.

Without a local TeX installation, compile in the TeX Live image (run twice for the
table of contents):

```sh
docker run --rm -v "$PWD:/work" -w /work texlive/texlive:latest \
  sh -c 'pdflatex -interaction=nonstopmode final_report.tex && pdflatex -interaction=nonstopmode final_report.tex'
```

Re-render a diagram after editing it (needs `d2` and Chrome/Edge):

```sh
d2 --theme 4 --pad 25 --layout elk diagrams/container.d2 build/svg/container.svg
python svg2pdf.py build/svg/container.svg
```

The context diagram uses `--layout dagre`. D2's own PNG export is not used because it
downloads a Playwright driver from a host that no longer exists. If Ghostscript is on
the `PATH`, `svg2pdf.py` also shrinks each PDF about tenfold (Chrome embeds whole
fonts); without it the figures are just larger.

## Reproducing the evaluation

1. `experiments/run_e1.sh <output-dir>` starts the stack, lets it run for 40 real
   minutes (≈ 40 simulated hours at factor 60), injects the faults E2–E5, and saves
   container logs, `docker stats` and Prometheus exports.
2. `python experiments/analyze_e1.py <output-dir>` writes `data/e1_rooms.csv`,
   `data/e1_latency.csv` and `data/e1_results.json`.
3. `python experiments/replay.py` replays E1's occupancy and weather through the
   production physics and PID code (deployed, constant 21 °C, and corrected-area
   scenarios) and writes `data/replay_*.{csv,json}`.
4. `experiments/run_scale.sh <rooms> <output-dir>` enables the first N rooms that
   resolve in both BuildSim and the occupancy simulator, starts the stack and
   measures memory, stepping and latency; `python experiments/analyze_scale.py`
   summarises the runs into `data/scale.csv`. Back up `JSON files/rooms.json` and
   `services-compose.yaml` first, and restore them afterwards.
