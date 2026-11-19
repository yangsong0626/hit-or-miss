"""分子对比表的数据：每个药一条，合并结构（PubChem）、ChEMBL（性质、机制、活性、选择性）和注册库里登记的给药方案。

build_site.py 调用：先在压缩试验数据之前用 regimens() 从干预描述里抽剂量、给药途径和频次，
最后用 export() 写 docs/molecules.json（页面按需加载；静态靶点页也用它）。

docs/molecules.json：{"generated", "drugs": {药名键: {...}}}，药名键和页面里 drugKeys 的第一个键一致。
"""
import collections
import json
import os
import re

CJK = re.compile(r"[㐀-鿿]")
CTL = re.compile(r"placebo|vehicle|sham|saline|standard of care|best supportive|matching", re.I)
ROUTES = [("口服", r"\boral(ly)?\b|\btablets?\b|\bcapsules?\b|\bp\.?o\.?\b|by mouth"),
          ("静脉", r"intravenous|\bi\.?v\.?\b|infusion"),
          ("皮下", r"subcutaneous|\bs\.?c\.?\b|\bsq\b"),
          ("肌注", r"intramuscular|\bi\.?m\.?\b"),
          ("吸入", r"inhal|nebuli"),
          ("外用", r"topical|cream|ointment|\bgel\b|transdermal"),
          ("玻璃体内", r"intravitreal"),
          ("鞘内", r"intrathecal"),
          ("鼻用", r"intranasal|nasal spray")]
FREQS = [("TID", r"three times (a |per )?da(il)?y|\btid\b|\bt\.i\.d"),
         ("BID", r"twice (a |per )?da(il)?y|\bbid\b|\bb\.i\.d|every 12 hours|\bq12h\b"),
         ("QD", r"once (a |per )?da(il)?y|\bqd\b|\bq\.d\.|every day|\bdaily\b|\bq24h\b"),
         ("QW", r"once (a |per )?week(ly)?|\bweekly\b|every week|\bqw\b|\bq1w\b"),
         ("Q2W", r"every (2|two) weeks|\bq2w\b|biweekly|every other week"),
         ("Q3W", r"every (3|three) weeks|\bq3w\b|21-day cycle"),
         ("Q4W", r"every (4|four) weeks|\bq4w\b|monthly|every month|28-day cycle"),
         ("Q8W+", r"every (8|eight|12|twelve) weeks|\bq8w\b|\bq12w\b|every (3|6) months|twice (a |per )?year|once (a |per )?year")]
DOSE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mg/kg|mg/m2|mg/m²|mg|µg|μg|mcg|ug)\b(?!\s*/\s*(?:ml|l|vial|dose)\b)", re.I)
# 丙烯酰胺、丁炔酰胺、氯乙酰胺、乙烯基砜（酰胺）：只作「可能共价」的提示，以 ChEMBL 机制注释为准
WARHEAD = re.compile(r"C\(=O\)C\(=C\)F|^C=CC\(=O\)|C\(=O\)C=C(?![A-Za-z0-9(=#\[/\\])|C=CC\(=O\)N|/C=C/C\(=O\)N|C#CC\(=O\)N|ClCC\(=O\)N|N\(C\(=O\)C=C|NC\(=O\)C=C|NC\(=O\)/C=C|C=CS\(=O\)\(=O\)")
FREQ_LBL = {"QD": ("每日一次", "once daily"), "BID": ("每日两次", "twice daily"), "TID": ("每日三次", "three times daily"),
            "QW": ("每周一次", "weekly"), "Q2W": ("每两周", "every 2 weeks"), "Q3W": ("每三周", "every 3 weeks"),
            "Q4W": ("每四周", "every 4 weeks"), "Q8W+": ("每 8 周或更久", "every 8+ weeks")}


def nk(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def dkeys(name):
    """和页面里 drugKeys 一致（括号里的剂量、分组之类不算）。"""
    s, out = str(name or ""), []
    main = re.split(r"[(（\[]", s)[0]
    if not CJK.search(main):
        out.append(nk(main))
    for p in re.findall(r"[(（]([^)）]+)[)）]", s):
        out += [nk(z) for z in re.split(r"[,;/]", p)]
    return [k for k in dict.fromkeys(out) if len(k) >= 4 and not re.match(r"^\d", k)]


SALT = (r"mesylate|mesilate|dihydrochloride|hydrochloride|hcl|maleate|sodium|potassium|tosylate|citrate|fumarate|succinate|tartrate|"
        r"besylate|phosphate|sulfate|sulphate|monohydrate|hemihydrate|free base|malate|acetate|hydrobromide|bromide|chloride")
FORM = (r"tablets?|capsules?|cream|ointment|gel|granules?|injection|infusion|solution|suspension|oral|orally|enteric|sprinkle|minitablets?|"
        r"formulation|fdc|er|xr|sr|ir|foam|implant|inhalation|dry powder|single agent|film[- ]coated|dispersible|powder|ophthalmic|topical|iv|sc|po|is provided|administered|given")
STOP = (r"dose|doses|dosing|cohort|part|arm|level|dl\d*|ds\d*|monotherapy|escalation|expansion|high|low|higher|lower|adult|pediatric|"
        r"continuous|optimi[sz]ed|rp2d|regimen|qd|bid|tid|daily|weekly|q\dw")


def core_names(name):
    """把干预名拆成单个药名：去掉括号、盐型、剂量、剂型和「Dose 1」之类的后缀，联用方案按 + / , 拆开。
    「Osimertinib Mesylate Tablets 80mg」→ ["Osimertinib"]，「PF-07220060 + PF-07104091 combination」→ 两个代号。"""
    s = re.sub(r"[(（\[][^)）\]]*[)）\]]", " ", str(name or ""))
    out = []
    for part in re.split(r"\s*(?:\+|/|,|;|±|&| and | with | plus | combined with | in combination with |\bcombination\b)\s*", s, flags=re.I):
        p = re.sub(r"^\s*(?:(?:oral|topical|intravenous|subcutaneous|iv|sc)\s+)+", "", part, flags=re.I)
        p = re.sub(r"\b(" + SALT + r")\b", " ", p, flags=re.I)
        p = re.sub(r"\b\d+(\.\d+)?\s*(mg|µg|μg|mcg|g|%|ml|mg/kg|mg/m2)\b.*$", " ", p, flags=re.I)
        for rx in (STOP, FORM):
            p = re.sub(r"\b(" + rx + r")\b.*$", " ", p, flags=re.I)
        p = re.sub(r"\s+[A-Da-d]$", "", re.sub(r"\s+", " ", p).strip(" ,;:-."))  # 「Etavopivat A」这类分组字母
        k = nk(p)
        if len(k) >= 4 and not re.match(r"^\d", k) and len(p.split()) <= 3:
            out.append(p)
    return list(dict.fromkeys(out))


def core_keys(name):
    return list(dict.fromkeys(nk(p) for p in core_names(name)))


def regimens(trials, acc=None):
    """从干预名称和描述里抽给药方案，累加到 acc：{药名键: {"dose": Counter, "route": Counter, "freq": Counter, "n": 试验数}}。"""
    acc = acc if acc is not None else {}
    for t in trials:
        for iv in t.get("iv") or []:
            n = iv.get("n") or ""
            if iv.get("r") == "c" or CTL.search(n):
                continue
            ks = dkeys(n)
            if not ks:
                continue
            txt = f"{n} . {iv.get('ds') or ''}"
            a = acc.setdefault(ks[0], {"dose": collections.Counter(), "route": collections.Counter(), "freq": collections.Counter(), "n": 0})
            a["n"] += 1
            low = txt.lower()
            for lbl, rx in ROUTES:
                if re.search(rx, low):
                    a["route"][lbl] += 1
            for lbl, rx in FREQS:
                if re.search(rx, low):
                    a["freq"][lbl] += 1
                    break
            seen = set()
            for v, u in DOSE.findall(txt):
                u = {"μg": "µg", "mcg": "µg", "ug": "µg", "mg/m²": "mg/m2"}.get(u.lower(), u.lower())
                v = v.rstrip("0").rstrip(".") if "." in v else v
                d = f"{v} {u}"
                if d not in seen and float(v) > 0:
                    seen.add(d)
                    a["dose"][d] += 1
    return acc


def _covalent(ch, smi):
    if any(re.search(r"covalent|irreversib", f"{m.get('c') or ''} {m.get('moa') or ''}", re.I) for m in (ch or {}).get("mech") or []):
        return 1
    if smi and WARHEAD.search(smi):
        return 2
    return 0


def export(root, docs, targeted_names, regimen):
    """targeted_names：有靶点的试验里出现的受试药名（tgm.n）。写 docs/molecules.json，返回条目数。"""
    st_items = {}
    p = os.path.join(root, "data", "structures.json")
    if os.path.exists(p):
        st_items = json.load(open(p, encoding="utf-8")).get("items", {})
    ch_items = {}
    p = os.path.join(root, "data", "chembl.json")
    if os.path.exists(p):
        ch_items = json.load(open(p, encoding="utf-8")).get("items", {})
    by_key = {}
    for k, x in st_items.items():
        if x.get("cid") or x.get("smi"):
            for kk in [k] + list(x.get("al") or []):
                by_key.setdefault(kk, x)
    # 专利推测的结构排在确认结构后面，只补空缺
    p = os.path.join(root, "data", "structures_patent.json")
    if os.path.exists(p):
        for k, x in json.load(open(p, encoding="utf-8")).get("items", {}).items():
            if x.get("smi"):
                for kk in [k] + list(x.get("al") or []):
                    by_key.setdefault(kk, dict(x, src="patent"))
    drugs = {}
    for name in targeted_names:
        ks = dkeys(name)
        if not ks or ks[0] in drugs:
            continue
        k = ks[0]
        # 先用原名键，对不上再用去掉盐型、剂量、剂型后的药名（「Osimertinib Mesylate Tablets」→ osimertinib）
        sx = next((by_key[kk] for kk in ks + core_keys(name) if kk in by_key), None)
        rg = regimen.get(k)
        if not sx and not rg:
            continue
        e = {"n": re.split(r"[(（\[]", name)[0].strip()}
        if sx:
            e.update({k2: v for k2, v in {"cid": sx.get("cid"), "smi": sx.get("smi"), "mw": sx.get("mw"), "src": sx.get("src"),
                                                    "pat": sx.get("pat"), "pex": sx.get("ex"), "pwhy": sx.get("why"), "pconf": sx.get("conf")}.items() if v})
            ch = ch_items.get(sx.get("ik") or "") if sx.get("src") != "patent" else None
            if ch and not ch.get("miss"):
                e["ch"] = ch["id"]
                for f in ("ph", "fa", "p", "bio", "cell", "sel"):
                    if ch.get(f) not in (None, {}, []):
                        e[f] = ch[f]
                m = (ch.get("mech") or [{}])[0]
                if m.get("moa"):
                    e["moa"] = m["moa"]
                if m.get("a"):
                    e["act"] = m["a"]
            cov = _covalent(ch, sx.get("smi"))
            if cov:
                e["cov"] = cov
        if rg:
            # 只留常见的写法，联用方案里偶尔出现的其他途径 / 频次不算
            top = lambda c, n: [x for x, v in c.most_common(n) if v >= max(1, 0.3 * c.most_common(1)[0][1])] if c else []
            for f, c, n in (("dose", rg["dose"], 4), ("route", rg["route"], 2), ("freq", rg["freq"], 2)):
                if top(c, n):
                    e[f] = top(c, n)
        if len(e) > 1:
            drugs[k] = e
    gen = None
    try:
        gen = json.load(open(os.path.join(root, "data", "chembl.json"), encoding="utf-8")).get("generated")
    except (OSError, ValueError):
        pass
    with open(os.path.join(docs, "molecules.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": gen, "freq_lbl": FREQ_LBL, "drugs": drugs}, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return len(drugs), sum(1 for e in drugs.values() if "ch" in e)
