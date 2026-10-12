#!/bin/bash
# macOS：在 Finder 里双击即可抓取最新数据并重建网站
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
"$PY" scripts/fetch_trials.py --out data/trials.json 2>&1 | tee fetch.log
"$PY" scripts/build_site.py site/template.html data/trials.json docs/index.html
echo "DONE" | tee -a fetch.log
