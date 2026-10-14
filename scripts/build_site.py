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

# 药物形式：页面只需要每个干预的名字、细类和角色，描述和别名不内嵌，减小页面体积
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modality  # noqa: E402
for v in d["sets"].values():
    for t in v:
        if "modg" not in t:
            t["mod"], t["mods"] = modality.classify_trial(t)
            t["modg"] = modality.GROUPS.get(t["mod"], "未识别")
        t["iv"] = [{"n": iv["n"], "m": modality.classify_one(iv), "r": iv.get("r", "x")}
                   for iv in (t.get("iv") or []) if not modality.PLACEBO.search(iv.get("n") or "")][:6]
d["mod_order"] = modality.ORDER
d["mod_groups"] = modality.GROUPS
base = os.path.dirname(data)
cur_path, tg_path = os.path.join(base, "curated.json"), os.path.join(base, "targets.json")
cur = json.load(open(cur_path, encoding="utf-8")) if os.path.exists(cur_path) else {"readouts": [], "readthrough": [], "calendar": []}
tg = json.load(open(tg_path, encoding="utf-8")) if os.path.exists(tg_path) else {"trials": {}, "curated": {}}
ov = tg.get("outcome_override", {})
for v in d["sets"].values():
    for t in v:
        if t.get("nct") in tg["trials"]:
            t["tgt"] = tg["trials"][t["nct"]]
            if t["nct"] in ov:
                t["tgt_out"] = ov[t["nct"]]
for c in cur["readouts"]:
    if c["id"] in tg["curated"]:
        c["tgt"] = tg["curated"][c["id"]]
d["curated"] = cur
js = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
tag = '<script id="trials-data" type="application/json">' + js + "</script>\n"
marker = "\n<script>\n"
assert html.count(marker) == 1, "template marker not found"
open(out, "w", encoding="utf-8").write(html.replace(marker, "\n" + tag + "<script>\n"))
print(f"built {out} · {n} notes merged", file=sys.stderr)
