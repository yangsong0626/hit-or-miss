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
d["mod_order"] = modality.ORDER
d["mod_groups"] = modality.GROUPS

# 靶点：人工标注（targets.json，写入 t.tgt）优先，其余自动抽取；t.tg 是列表，靶点赛道用
import targets as tgmod  # noqa: E402


def compact_iv(t):
    return [{"n": iv["n"], "m": modality.classify_one(iv), "r": iv.get("r", "x")}
            for iv in (t.get("iv") or []) if not modality.PLACEBO.search(iv.get("n") or "")][:6]


def set_tg(t, manual):
    """t.tg：靶点列表；t.tgm：[{g 靶点, n 药名, m 药物形式}]，靶点赛道按它把项目和形式对上。"""
    cands = modality.candidates(t)
    if manual:
        t["tg"] = tgmod.canonical(manual)
        t["tg_src"] = "人工"
        iv = next((x for x in cands if modality.GROUPS.get(modality.classify_one(x)) not in ("未识别", "其他")), cands[0] if cands else None)
        t["tgm"] = [{"g": g, "n": iv["n"] if iv else "", "m": modality.classify_one(iv) if iv else t.get("mod")} for g in t["tg"]]
        return
    pairs = tgmod.extract_pairs(t, cands)
    tgm, tgs = [], []
    for iv, gs in pairs:
        m = modality.classify_one(iv) if iv else t.get("mod")
        if iv and modality.GROUPS.get(m) == "未识别":
            m = t.get("mod")      # 单个干预认不出形式时，用整条试验的判断
        for g in gs:
            tgm.append({"g": g, "n": iv["n"] if iv else "", "m": m})
            if g not in tgs:
                tgs.append(g)
    t["tg"], t["tgm"] = tgs[:4], tgm[:6]
    if tgs:
        t["tg_src"] = "自动"


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
        c["tg"] = tgmod.canonical(c["tgt"])
for v in d["sets"].values():
    for t in v:
        set_tg(t, t.get("tgt"))
        t["iv"] = compact_iv(t) if t.get("iv") and "ds" in (t["iv"][0] or {}) else t.get("iv", [])
        for k in ("sum", "kw", "hv"):
            t.pop(k, None)

# 早期新进（I/II 期）单独写一个文件，页面需要时再加载
early = d.pop("early", [])
early_out = []
for t in early:
    set_tg(t, tg["trials"].get(t.get("nct")))
    r = {k: t.get(k) for k in ("nct", "title", "acronym", "sponsor", "group", "phase", "status", "n", "fp",
                               "pcd", "ta", "mod", "mods", "modg", "tg", "tgm", "tg_src", "hv", "why", "why_cat")
         if t.get(k) not in (None, "", [])}
    if r.get("group") == r.get("sponsor"):
        r.pop("group")          # 页面里 group 缺省等于 sponsor
    if len(r.get("mods") or []) <= 1:
        r.pop("mods", None)
    r["conditions"] = (t.get("conditions") or [])[:2]
    r["iv"] = [{k: v for k, v in iv.items() if not (k == "r" and v == "x")} for iv in compact_iv(t)][:4]
    early_out.append(r)
d["early_n"] = len(early_out)
d["early_days"] = d.get("early_days")
if early_out:
    eo = os.path.join(os.path.dirname(out), "early.json")
    with open(eo, "w", encoding="utf-8") as f:
        json.dump({"generated": d.get("generated"), "early_days": d.get("early_days"), "trials": early_out},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {eo} · {len(early_out)} early trials · {sum(1 for t in early_out if t.get('tg'))} with targets", file=sys.stderr)

# 在研 II/III 期（data/active.json，由抓取脚本生成、不进仓库）：只保留识别出靶点的，写 docs/active.json。
# 没有 data/active.json 时保留上次生成的 docs/active.json，不覆盖。
act_in = os.path.join(base, "active.json")
if os.path.exists(act_in):
    act = json.load(open(act_in, encoding="utf-8"))
    act_out = []
    for t in act.get("trials", []):
        set_tg(t, tg["trials"].get(t.get("nct")))
        if not t.get("tg"):
            continue
        r = {k: t.get(k) for k in ("nct", "title", "acronym", "sponsor", "group", "phase", "status", "n", "fp", "pcd",
                                   "ta", "mod", "modg", "tg", "tgm", "tg_src") if t.get(k) not in (None, "", [])}
        if r.get("group") == r.get("sponsor"):
            r.pop("group")
        r["title"] = r.get("title", "")[:120]
        r["conditions"] = (t.get("conditions") or [])[:2]
        r["iv"] = [{k: v for k, v in iv.items() if not (k == "r" and v == "x")} for iv in compact_iv(t)][:3]
        act_out.append(r)
    ao = os.path.join(os.path.dirname(out), "active.json")
    with open(ao, "w", encoding="utf-8") as f:
        json.dump({"generated": act.get("generated"), "trials": act_out}, f, ensure_ascii=False, separators=(",", ":"))
    d["active_n"] = len(act.get("trials", []))
    d["active_tg"] = len(act_out)
    print(f"wrote {ao} · {len(act_out)} of {len(act.get('trials', []))} active II/III trials with targets", file=sys.stderr)
d["curated"] = cur
js = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
tag = '<script id="trials-data" type="application/json">' + js + "</script>\n"
marker = "\n<script>\n"
assert html.count(marker) == 1, "template marker not found"
open(out, "w", encoding="utf-8").write(html.replace(marker, "\n" + tag + "<script>\n"))
print(f"built {out} · {n} notes merged", file=sys.stderr)
