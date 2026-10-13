#!/usr/bin/env python3
"""把 trials.json（和 notes.json 里的人工分析）内嵌进网站模板，生成可直接发布的 index.html。

用法：python scripts/build_site.py site/template.html data/trials.json docs/index.html [data/notes.json]
"""
import json, os, sys

tpl, data, out = sys.argv[1:4]
notes_path = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.path.dirname(data), "notes.json")
html = open(tpl, encoding="utf-8").read()
d = json.load(open(data, encoding="utf-8"))
notes = json.load(open(notes_path, encoding="utf-8")) if os.path.exists(notes_path) else {}
n = 0
for v in d["sets"].values():
    for t in v:
        x = notes.get(t.get("nct"))
        if not x:
            continue
        n += 1
        t["note"] = x.get("note", "")
        if x.get("verdict") and t.get("as"):
            t["as"]["verdict"] = x["verdict"]
d["notes_count"] = n
js = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
tag = '<script id="trials-data" type="application/json">' + js + "</script>\n"
marker = "\n<script>\n"
assert html.count(marker) == 1, "template marker not found"
open(out, "w", encoding="utf-8").write(html.replace(marker, "\n" + tag + "<script>\n"))
print(f"built {out} · {n} notes merged", file=sys.stderr)
