#!/usr/bin/env python3
"""把 trials.json（和 notes.json 里的人工分析）内嵌进网站模板，生成可直接发布的 index.html。

用法：python scripts/build_site.py site/template.html data/trials.json docs/index.html [data/notes.json]
"""
import json, os, re, sys

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


SURFACE_ONLY = {"CD3", "CD19", "CD20", "CD22", "CD30", "CD33", "CD38", "CD123", "BCMA", "GPRC5D", "FcRH5", "CLDN18.2",
                "CLDN6", "DLL3", "B7-H3", "B7-H4", "TROP2", "Nectin-4", "HER3", "CTLA-4", "TIGIT", "LAG-3", "TIM-3",
                "CD70", "CD7", "CEACAM5", "FRα (FOLR1)", "CDH6", "CDH17", "GPC3", "Mesothelin", "MUC1 / MUC16", "STEAP1",
                "ROR1", "PTK7", "组织因子 (TF)", "LIV-1", "OX40", "4-1BB", "GITR", "ICOS", "NKG2A", "TL1A", "IL-23 / IL-23R",
                "IL-13", "IL-5 / IL-5R", "TSLP", "IL-33 / ST2", "IL-31 / IL-31RA", "BAFF / APRIL", "CD40L", "OX40L", "FcRn"}


def drug_key(iv):
    """同一个药的研发代号和通用名（INN）归成一个项目：别名里有 INN 就用 INN。"""
    if not iv:
        return ""
    names = [iv.get("n", "")] + list(iv.get("on") or [])
    for nm in names:
        w = re.split(r"[\s(,/+]", nm.strip())[0] if nm else ""
        if re.fullmatch(r"[A-Za-z][a-z]{5,}", w or "") and tgmod.load() and not re.fullmatch(r"(?i)placebo|standard|control|matching", w):
            return w.lower()
    m = re.search(r"\b[A-Za-z]{1,6}(?:-[A-Za-z]{1,2})?-?\d{2,}[A-Za-z0-9]*\b", names[0] or "")
    return re.sub(r"[^a-z0-9]", "", (m.group(0) if m else names[0]).lower())


def set_tg(t, manual):
    """t.tg：靶点列表；t.tgm：[{g 靶点, n 药名, m 药物形式}]，靶点赛道按它把项目和形式对上。"""
    cands = modality.candidates(t)
    if manual:
        t["tg"] = tgmod.canonical(manual)
        t["tg_src"] = "人工"
        iv = next((x for x in cands if modality.GROUPS.get(modality.classify_one(x)) not in ("未识别", "其他")), cands[0] if cands else None)
        t["tgm"] = [{"g": g, "n": iv["n"] if iv else "", "m": modality.classify_one(iv) if iv else t.get("mod"), "k": drug_key(iv)}
                    for g in t["tg"]]
        return
    pairs = tgmod.extract_pairs(t, cands)
    tgm, tgs = [], []
    cand_groups = {modality.GROUPS.get(modality.classify_one(x)) for x in cands} - {"未识别", "其他"}
    for iv, gs in pairs:
        m = modality.classify_one(iv) if iv else t.get("mod")
        if iv and modality.GROUPS.get(m) == "未识别":
            m = t.get("mod")      # 单个干预认不出形式时，用整条试验的判断
        if not iv and len(cand_groups) > 1:
            m = "未识别"          # 靶点只在标题里出现、受试药又有几种形式时，对不上是哪一个
        for g in gs:
            # 这些细胞表面抗原 / 细胞因子基本只有大分子或细胞疗法，配到小分子多半是联用药配错
            mg = "未识别" if modality.GROUPS.get(m) == "小分子" and g in SURFACE_ONLY else m
            tgm.append({"g": g, "n": iv["n"] if iv else "", "m": mg, "k": drug_key(iv)})
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
deal_path = os.path.join(base, "deal_watch.json")
if os.path.exists(deal_path):
    d["deals"] = json.load(open(deal_path, encoding="utf-8"))

# 临床前靶点：人工精选（preclinical.json）+ Open Targets 自动打分（preclinical_auto.json，每周更新时刷新）
pre = {}
for k, fn in (("cur", "preclinical.json"), ("auto", "preclinical_auto.json")):
    fp_ = os.path.join(base, fn)
    if os.path.exists(fp_):
        pre[k] = json.load(open(fp_, encoding="utf-8"))
if pre:
    d["pre"] = pre

# 核对：精选临床前靶点是否已在本站的临床试验数据里出现（本次构建的三套数据；没有 data/active.json 时读上次的 docs/active.json）
clin = {}
act_trials = act_out if os.path.exists(act_in) else []
if not act_trials and os.path.exists(os.path.join(os.path.dirname(out), "active.json")):
    act_trials = json.load(open(os.path.join(os.path.dirname(out), "active.json"), encoding="utf-8")).get("trials", [])
for t in [t for v in d["sets"].values() for t in v] + early_out + act_trials:
    for g in t.get("tg") or []:
        clin.setdefault(g, []).append({"nct": t.get("nct"), "phase": t.get("phase"), "sponsor": t.get("sponsor")})
flagged = []
for a in (pre.get("cur") or {}).get("areas", []):
    for x in a["items"]:
        hits = clin.get(x["tg"]) or []
        if hits:
            x["clin"] = hits[:3]
            x["clin_n"] = len(hits)
            flagged.append(x["tg"])
if flagged:
    print(f"WARNING preclinical targets now in clinical data: {', '.join(flagged)}", file=sys.stderr)

# 搜索用的靶点别名和药名表：页面按别名把查询换成规范靶点名，再展开成「别名 + 已知药名」一起匹配
_td = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "target_dict.json"), encoding="utf-8"))
_alias = {}
for c, al in _td["targets"].items():
    if c.startswith("_"):
        continue
    out_ = []
    for a in al:
        a = a[3:] if a.startswith("cs:") else a
        if a.startswith("re:"):
            a = a[3:].replace("[\\s-]?", " ").replace("[\\s-]", " ")
            if re.search(r"[\\\[\](){}?*+|^$]", a):
                continue
        a = a.strip()
        if a and a.lower() != c.lower() and a not in out_:
            out_.append(a)
    _alias[c] = out_
_drugs = {}
for dn, tgs_ in _td.get("drugs", {}).items():
    if dn.startswith("_"):
        continue
    for g in ([tgs_] if isinstance(tgs_, str) else tgs_):
        _drugs.setdefault(g, []).append(dn)
d["tgsearch"] = {"alias": _alias, "drugs": _drugs}

# 每周 FDA 核对结果（scripts/check_watch.py 生成）
wa = os.path.join(base, "watch_alerts.json")
if os.path.exists(wa) and "deals" in d:
    d["deals"]["alerts"] = json.load(open(wa, encoding="utf-8"))
# ---------- 医生视角：主要终点的可比数据（效应量、应答率、中位时间） ----------
CTL = re.compile(r"placebo|control|vehicle|sham|standard of care|\bSOC\b|observation|best supportive|chemotherapy alone|comparator", re.I)
RATIO_PT = re.compile(r"hazard|odds|risk ratio|rate ratio|relative risk|\bHR\b|\bOR\b|\bRR\b|ratio", re.I)


def _arm_role(title, arms):
    tl = (title or "").lower()
    for a in arms or []:
        al = (a.get("l") or "").lower()
        if al and (al in tl or tl in al):
            if a.get("t") in ("PLACEBO_COMPARATOR", "ACTIVE_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION"):
                return "c"
            if a.get("t") == "EXPERIMENTAL":
                return "x"
    return "c" if CTL.search(title or "") else "x"


def _ratio_sub(pt):
    p = (pt or "").lower()
    return "HR" if "hazard" in p or re.search(r"\bhr\b", p) else "OR" if "odds" in p or re.search(r"\bor\b", p) else \
        "RR" if "risk ratio" in p or "relative risk" in p or re.search(r"\brr\b", p) else "Rate ratio" if "rate" in p else "Ratio"


def derive_cmp(t):
    out = []
    dt = t.get("dt") or {}
    arms = dt.get("arms") or []
    for pr in (dt.get("prim") or [])[:2]:
        title = (pr.get("title") or "")[:90]
        if re.search(r"adverse|\bAEs?\b|TEAE|safety|tolerab|dose.limiting|\bDLT|toxicit|pharmacokinetic|\bPK\b|C ?max|AUC|immunogenicity|antibod(y|ies) titer|seroconver|laboratory", title, re.I):
            continue
        unit, pm = (pr.get("unit") or ""), (pr.get("pm") or "").upper()
        best = [a for a in pr.get("an") or [] if a.get("est") is not None]
        rat = [a for a in best if RATIO_PT.search(a.get("pt") or "") and a["est"] > 0 and (a.get("lo") is None or a["lo"] > 0)]
        if rat:
            a = min(rat, key=lambda a: a["p"] if a.get("p") is not None else 1)
            out.append({"n": t["nct"], "k": "r", "e": title, "s": _ratio_sub(a.get("pt")), "v": a["est"], "lo": a.get("lo"), "hi": a.get("hi"), "p": a.get("p")})
            continue
        gs = [g for g in pr.get("groups") or [] if g.get("v") is not None]
        if len(gs) < 2:
            continue
        role = [(_arm_role(g["t"], arms), g) for g in gs]
        cs = [g for r_, g in role if r_ == "c"]
        xs = [g for r_, g in role if r_ == "x"]
        if len(cs) != 1 or not xs:
            continue
        c = cs[0]
        if re.search(r"change|reduction from baseline|mean", title, re.I) and not re.search(r"percent(age)? of participants|proportion|responder", title, re.I):
            kind = None
        else:
            kind = None
        u = unit.lower()
        val = None
        if re.search(r"percent|%|proportion", u) and "change" not in u and pm in ("NUMBER", "COUNT_OF_PARTICIPANTS", ""):
            kind, val = "p", (lambda g: g["v"])
        elif re.search(r"participants", u) and pm in ("COUNT_OF_PARTICIPANTS", "NUMBER") and all(g.get("n") for g in [c] + xs):
            kind, val = "p", (lambda g: 100.0 * g["v"] / g["n"] if g.get("n") else None)
        elif re.search(r"^(months?|weeks?|days?)$", u.strip()) and pm in ("MEDIAN",):
            f = 1.0 if u.startswith("month") else (1 / 4.345 if u.startswith("week") else 1 / 30.44)
            kind, val = "m", (lambda g, f=f: g["v"] * f)
        if not kind:
            continue
        if kind == "p" and re.search(r"change from baseline|mean change", title, re.I):
            continue
        cv = val(c)
        if cv is None or (kind == "p" and not (0 <= cv <= 100)):
            continue
        p = min([a["p"] for a in pr.get("an") or [] if a.get("p") is not None] or [None], key=lambda v: 1 if v is None else v)
        for x in xs[:3]:
            xv = val(x)
            if xv is None or (kind == "p" and not (0 <= xv <= 100)) or (kind == "m" and xv > 240):
                continue
            out.append({"n": t["nct"], "k": kind, "e": title + (f" · {x['t'][:40]}" if len(xs) > 1 else ""), "x": [x["t"][:50], round(xv, 2)], "c": [c["t"][:50], round(cv, 2)], "p": p})
    return out


cmp = []
for t in d["sets"].get("results", []):
    try:
        cmp += derive_cmp(t)
    except Exception as e:  # 单条数据异常不影响构建
        print(f"cmp skip {t.get('nct')}: {e}", file=sys.stderr)
d["cmp"] = cmp
print(f"comparable endpoints: {len(cmp)} (ratio {sum(c['k']=='r' for c in cmp)}, rate {sum(c['k']=='p' for c in cmp)}, median {sum(c['k']=='m' for c in cmp)})", file=sys.stderr)

# ---------- BD：并购案例 ----------
ma_path = os.path.join(base, "ma_deals.json")
if os.path.exists(ma_path):
    d["ma"] = json.load(open(ma_path, encoding="utf-8"))

# ---------- 中英文词典 ----------
i18n = {"ui": {"exact": {}, "patterns": [], "phrases": {}}, "content": {}}
for fn, key in (("ui_en.json", "ui"), ("content_en.json", "content")):
    fp_ = os.path.join(base, "i18n", fn)
    if os.path.exists(fp_):
        i18n[key] = json.load(open(fp_, encoding="utf-8"))
d["i18n"] = i18n


def _harvest(o):
    """数据里写成 X 和 X_en 成对的字段，英文自动进 content 词典，然后删掉 _en 字段减小页面体积。"""
    if isinstance(o, list):
        for v in o:
            _harvest(v)
    elif isinstance(o, dict):
        for k in [k for k in o if k.endswith("_en")]:
            base_ = k[:-3]
            zh, en = o.get(base_), o.pop(k)
            if isinstance(zh, str) and isinstance(en, str):
                i18n["content"].setdefault(zh, en)
            elif isinstance(zh, list) and isinstance(en, list):
                for a_, b_ in zip(zh, en):
                    if isinstance(a_, str) and isinstance(b_, str):
                        i18n["content"].setdefault(a_, b_)
        for v in o.values():
            _harvest(v)


for k in ("curated", "deals", "pre", "ma"):
    _harvest(d.get(k))


def _cjk_strings(o, out, skip=("ta", "mod", "mods", "modg", "why_cat", "verdict", "tag", "out", "g", "tg", "tgt", "group", "sponsor", "status", "phase", "ph", "st")):
    if isinstance(o, str):
        if re.search(r"[\u3400-\u9fff]", o):
            out.add(o)
    elif isinstance(o, list):
        for v in o:
            _cjk_strings(v, out)
    elif isinstance(o, dict):
        for k, v in o.items():
            if k not in skip:
                _cjk_strings(v, out)


_need = set()
for k in ("curated", "deals", "pre", "ma"):
    _cjk_strings(d.get(k), _need)
for v in d["sets"].values():
    for t in v:
        if t.get("note"):
            _need.add(t["note"])
_ex = i18n["ui"].get("exact", {})
_missing = sorted(x for x in _need if x not in i18n["content"] and x.strip() not in _ex)
if _missing:
    print(f"WARNING {len(_missing)} curated strings have no English translation (data/i18n/content_en.json); first: {_missing[0][:60]}", file=sys.stderr)
    with open(os.path.join(base, "i18n", "missing.txt") if os.path.isdir(os.path.join(base, "i18n")) else os.devnull, "w", encoding="utf-8") as f:
        f.write("\n".join(_missing))

# ---------- 靶点索引（给每周抓文献 / 新闻的脚本用） ----------
_tcount = {}
for t in [t for v in d["sets"].values() for t in v] + early_out + (act_trials or []):
    for g in t.get("tg") or []:
        _tcount[g] = _tcount.get(g, 0) + 1
for a in (pre.get("cur") or {}).get("areas", []):
    for x in a["items"]:
        _tcount.setdefault(x["tg"], 0)
for dl in (d.get("ma") or {}).get("deals", []):
    for g in dl.get("tg") or []:
        _tcount.setdefault(g, 0)
with open(os.path.join(os.path.dirname(out), "targets_index.json"), "w", encoding="utf-8") as f:
    json.dump({"generated": d.get("generated"), "targets": [{"g": g, "n": n, "alias": _alias.get(g, [])} for g, n in sorted(_tcount.items(), key=lambda x: -x[1])]},
              f, ensure_ascii=False, separators=(",", ":"))

js = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
tag = '<script id="trials-data" type="application/json">' + js + "</script>\n"
_pj = os.path.join(os.path.dirname(os.path.abspath(tpl)), "portals.js")
if "/*@@PORTALS@@*/" in html and os.path.exists(_pj):
    html = html.replace("/*@@PORTALS@@*/", open(_pj, encoding="utf-8").read())
marker = "\n<script>\n"
assert html.count(marker) == 1, "template marker not found"
open(out, "w", encoding="utf-8").write(html.replace(marker, "\n" + tag + "<script>\n"))
print(f"built {out} · {n} notes merged", file=sys.stderr)
