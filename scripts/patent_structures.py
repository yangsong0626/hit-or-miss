#!/usr/bin/env python3
"""用 SureChEMBL 从专利里给研发代号找候选结构（只出候选，人工核对后再写进 data/structures_patent.json）。

做法：
  1. SureChEMBL 全文检索代号（"VS-7375" 这类精确短语，带连字符/空格的写法都试），有申办方时优先用 pa:申请人 过滤；
  2. 取回专利全文，确认正文里真的出现这个代号，截取代号前后的文字；
  3. 把这些片段交给 SureChEMBL 的 Leadmine（化学命名实体识别），化学名解析成 SMILES；
  4. 按「离代号多近、出现几次、是不是单化合物专利（盐型/晶型/给药方案/制备方法）」打分排序。

结构式画在图里、正文只写「化合物 1」的专利拿不到结构，这时会列出专利，留给人工看图（/api/patent/pdf/<ucid> 可下 PDF）。

用法：
  python scripts/patent_structures.py ST-1898 --sponsor "Scitech"      # 单个代号，打印候选
  python scripts/patent_structures.py --missing                         # 靶点项目里缺结构的小分子代号，批量跑
  python scripts/patent_structures.py --missing --out data/patent_candidates.json
"""
import argparse, collections, html, json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

API = "https://www.surechembl.org/api"
UA = {"User-Agent": "hit-or-miss/1.0 (https://github.com/yangsong0626/hit-or-miss)", "Content-Type": "application/json"}
CODE = re.compile(r"^[A-Za-z]{1,6}[- ]?\d{2,}[A-Za-z0-9-]{0,4}$")
# 单化合物专利：标题里有这些词，多半只讲一个药
SINGLE = re.compile(r"crystal|polymorph|salt|solid form|amorphous|dosage|dosing|regimen|administration of|formulation|"
                    r"preparation method|process for prepar|synthesis of|deuterat|isotop|impurit|"
                    r"晶型|盐|制备方法|用途|剂量|给药", re.I)
WINDOW = 700          # 代号前后各取多少字符
MAX_DOCS = 8          # 每个代号最多细看几篇专利
LEADMINE_CHARS = 60000
STOP_SPONSOR = re.compile(r"\b(co|ltd|limited|inc|llc|corp|corporation|company|pharmaceuticals?|pharma|therapeutics|"
                          r"biotech(nology)?|bio|medicines?|sciences?|group|holdings?|the|of|and|gmbh|ag|sa|plc|"
                          r"shanghai|beijing|jiangsu|zhejiang|guangzhou|nanjing|suzhou|shenzhen|hangzhou|chengdu)\b|[^a-z ]", re.I)


def _get(path, data=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data is not None else None, headers=UA)
            return json.load(urllib.request.urlopen(req, timeout=180))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  [retry] {path[:60]}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))


def variants(code):
    """VS-7375 → VS-7375 / VS7375 / VS 7375。"""
    m = re.match(r"^([A-Za-z]+)[- ]?(\d.*)$", code.strip())
    if not m:
        return [code]
    a, b = m.groups()
    return list(dict.fromkeys([code.strip(), f"{a}-{b}", f"{a}{b}", f"{a} {b}"]))


def code_re(code):
    m = re.match(r"^([A-Za-z]+)[- ]?(\d.*)$", code.strip())
    core = (re.escape(m.group(1)) + r"[\s\-‐–]?" + re.escape(m.group(2))) if m else re.escape(code)
    return re.compile(r"(?<![A-Za-z0-9])" + core + r"(?![0-9])", re.I)


def sponsor_words(sp):
    w = [x for x in STOP_SPONSOR.sub(" ", (sp or "").lower()).split() if len(x) >= 3]
    return w[:2]


def search(code, sponsor=None):
    """返回 [{ucid, pd, title, pa, fam, hit_sponsor}]，按同族去重。"""
    phrase = " OR ".join(f'"{v}"' for v in variants(code))
    qs = []
    sw = sponsor_words(sponsor)
    if sw:
        qs.append((f"({phrase}) AND pa:({' OR '.join(sw)})", True))
    qs.append((f"({phrase})", False))
    seen, out = set(), []
    for q, sp_hit in qs:
        try:
            r = _get("/search/content?" + urllib.parse.urlencode({"query": q, "itemsPerPage": 25}))
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] search {code}: {e}", file=sys.stderr)
            continue
        for g in r.get("groups", []):
            for d in g["doclist"]["docs"]:
                if d.get("fam") in seen:
                    continue
                seen.add(d.get("fam"))
                out.append({"ucid": d["ucid"], "pd": d.get("pd"), "title": (d.get("ttl_en") or d.get("ttl_zh") or [""])[0],
                            "pa": (d.get("pa") or [""])[0], "fam": d.get("fam"), "sp": sp_hit})
        time.sleep(0.5)
    return out


def _text(field):
    """专利正文字段（多语言列表）→ 纯文本，优先英文。"""
    if not field:
        return ""
    items = sorted(field, key=lambda x: 0 if x.get("language") == "EN" else 1)
    t = items[0].get("text") or ""
    t = re.sub(r"<img[^>]*>", " [IMAGE] ", t)
    t = re.sub(r"<sub>(.*?)</sub>|<sup>(.*?)</sup>", lambda m: m.group(1) or m.group(2) or "", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def windows(text, rx):
    """代号前后各 WINDOW 字符；重叠的窗口合并，同样的文字（权利要求里常重复）只留一份。"""
    spans = []
    for m in rx.finditer(text):
        a, b = max(0, m.start() - WINDOW), m.end() + WINDOW
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    out, seen = [], set()
    for a, b in spans:
        w = text[a:b]
        if w[:200] in seen:
            continue
        seen.add(w[:200])
        out.append((a, w))
    return out


def leadmine(text, depth=0):
    """Leadmine 对长文本会 500，切成 ≤8000 字符的块分别跑；块内出错再对半切一次。"""
    if len(text) > 8000 and depth == 0:
        ents, step = [], 8000
        for i in range(0, min(len(text), LEADMINE_CHARS), step):
            for e in leadmine(text[i:i + step], 1):
                e = dict(e, beginIndex=e["beginIndex"] + i)
                ents.append(e)
            time.sleep(0.3)
        return ents
    try:
        r = _get("/patent/analyze_sections_with_leadmine", {"description": text}, tries=2)
    except Exception as e:  # noqa: BLE001
        if depth < 2 and len(text) > 1500:
            h = len(text) // 2
            return leadmine(text[:h], depth + 1) + [dict(x, beginIndex=x["beginIndex"] + h) for x in leadmine(text[h:], depth + 1)]
        print(f"  [warn] leadmine ({len(text)} chars): {e}", file=sys.stderr)
        return []
    return [e for e in r.get("entities", []) if e.get("entityType") == "Mol" and e.get("resolvedForm")]


def _chem():
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem.rdMolDescriptors import CalcMolFormula
        from rdkit.Chem.Descriptors import MolWt
        RDLogger.DisableLog("rdApp.*")
        return Chem, CalcMolFormula, MolWt
    except ImportError:
        return None, None, None


def score_doc(doc, sponsor_hit):
    s = 0
    if sponsor_hit:
        s += 5
    if SINGLE.search(doc["title"] or ""):
        s += 3
    if doc.get("in_title"):
        s += 6
    if doc.get("n_hits"):
        s += min(doc["n_hits"], 10) * 0.5
    return s


def analyse(code, sponsor=None, max_docs=MAX_DOCS, verbose=True):
    Chem, Formula, MolWt = _chem()
    rx = code_re(code)
    docs = search(code, sponsor)
    # 先看最可能讲这个药本身的专利：申请人对得上、标题里就有代号、标题像单化合物专利
    docs.sort(key=lambda d: -(5 * d["sp"] + 6 * bool(rx.search(d["title"] or "")) + 3 * bool(SINGLE.search(d["title"] or ""))))
    found = []
    for d in docs:
        if len(found) >= max_docs:
            break
        try:
            p = _get("/patent/get_patent/" + urllib.parse.quote(d["ucid"]))
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] get {d['ucid']}: {e}", file=sys.stderr)
            continue
        body = _text(p.get("claims")) + " \n " + _text(p.get("description"))
        title = _text(p.get("title")) or d["title"]
        ws = windows(title + " " + body, rx)
        if not ws:      # 检索是分词匹配，正文里没有完整代号的不算
            continue
        d.update(title=title, n_hits=len(ws), in_title=bool(rx.search(title)))
        d["score"] = score_doc(d, d["sp"])
        found.append((d, ws))
        time.sleep(0.5)
    found.sort(key=lambda x: -x[0]["score"])
    cands = collections.OrderedDict()
    for d, ws in found:
        # 片段拼起来做一次 NER；记住每段在拼接文本里的起点，算化学名离代号多远
        parts, offs, pos = [], [], 0
        for _, w in ws[:40]:
            offs.append(pos)
            parts.append(w)
            pos += len(w) + 3
        joined = " | ".join(parts)
        for e in leadmine(joined):
            smi = e["resolvedForm"].split(" |")[0]
            if Chem:
                mol = Chem.MolFromSmiles(smi)
                # 像药的才要：至少 15 个重原子、有环、有 ≥2 个 N/O（滤掉溶剂、色谱柱填料、试剂）
                if not mol or mol.GetNumHeavyAtoms() < 15 or "*" in smi or not mol.GetRingInfo().NumRings() \
                        or sum(a.GetSymbol() in ("N", "O") for a in mol.GetAtoms()) < 2:
                    continue
                can = Chem.MolToSmiles(mol)
            else:
                can = smi
            # 离最近的代号出现处的距离（每段中间就是代号）
            i = max(j for j, o in enumerate(offs) if o <= e["beginIndex"]) if offs else 0
            dist = abs(e["beginIndex"] - (offs[i] + min(WINDOW, len(parts[i]) // 2)))
            c = cands.setdefault(can, {"smi": can, "names": set(), "n": 0, "best": 1e9, "pats": collections.OrderedDict(), "w": 0.0})
            c["names"].add(e["entityText"][:200])
            c["n"] += 1
            c["best"] = min(c["best"], dist)
            c["pats"].setdefault(d["ucid"], d["title"][:120])
            # 离代号越近、所在专利分越高，权重越大
            c["w"] += (1.0 + d["score"] / 5) * (2.0 if dist < 250 else 1.0 if dist < 600 else 0.4)
        time.sleep(0.5)
    out = []
    for c in sorted(cands.values(), key=lambda c: -c["w"]):
        row = {"smi": c["smi"], "w": round(c["w"], 2), "n": c["n"], "dist": c["best"], "names": sorted(c["names"])[:3],
               "pats": list(c["pats"].items())[:5]}
        if Chem:
            mol = Chem.MolFromSmiles(c["smi"])
            row["formula"] = Formula(mol)
            row["mw"] = round(MolWt(mol), 2)
            row["ik"] = Chem.MolToInchiKey(mol)
        out.append(row)
    res = {"code": code, "sponsor": sponsor, "patents": [dict(d, hits=d["n_hits"]) for d, _ in found], "cands": out[:8]}
    if verbose:
        show(res)
    return res


def show(r):
    print(f"\n### {r['code']}  ({r.get('sponsor') or '-'})")
    for d in r["patents"][:6]:
        print(f"  {'*' if d['sp'] else ' '} {d['ucid']:<20} {d['pd']}  hits={d['hits']:<3} score={d['score']:<4} {d['pa'][:30]} | {d['title'][:80]}")
    for c in r["cands"][:5]:
        print(f"    -> w={c['w']:<6} n={c['n']:<3} dist={c['dist']:<5} {c.get('formula', '')} {c['smi'][:110]}")
        print(f"       {c['names'][0][:110]}  [{', '.join(p for p, _ in c['pats'][:3])}]")


def missing_codes():
    """靶点项目里、小分子/降解剂、还没有结构的研发代号 → [(代号, 申办方, 靶点)]。"""
    from molecules import dkeys, core_keys
    d = json.load(open(os.path.join(ROOT, "data", "trials.json"), encoding="utf-8"))
    ts = [t for v in d["sets"].values() for t in v] + d.get("early", [])
    p = os.path.join(ROOT, "docs", "active.json")
    if os.path.exists(p):
        ts += json.load(open(p, encoding="utf-8")).get("trials", [])
    have = set(json.load(open(os.path.join(ROOT, "docs", "structures.json"), encoding="utf-8")))
    out = collections.OrderedDict()
    for t in ts:
        for e in t.get("tgm") or []:
            n = e.get("n")
            m = e.get("m") or t.get("mod") or ""
            if not n or not re.search("小分子|降解剂", m):
                continue
            ks = dkeys(n)
            if not ks or any(k in have for k in ks + core_keys(n)[:1]):
                continue
            # 只要代号本身：「TQB3909 Tablets」→ TQB3909，「QLC1101+docetaxel」→ QLC1101
            head = re.split(r"[(（\[+,;/]| and | with ", n)[0]
            head = re.sub(r"\b(tablets?|capsules?|injection|oral|gel|salt|dose.*|cohort.*|\d+\s*mg.*)$", "", head, flags=re.I).strip()
            if not CODE.match(head):
                continue
            k = head.upper()
            if k not in out or not out[k][0]:
                out[k] = (t.get("sponsor") or "", e.get("g") or "")
    return [(k, v[0], v[1]) for k, v in out.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    ap.add_argument("--sponsor")
    ap.add_argument("--missing", action="store_true")
    ap.add_argument("--max-docs", type=int, default=MAX_DOCS)
    ap.add_argument("--out", help="把候选写成 JSON（人工核对用）")
    a = ap.parse_args()
    jobs = [(c, a.sponsor, "") for c in a.codes]
    if a.missing:
        jobs += missing_codes()
        print(f"{len(jobs)} codes", file=sys.stderr)
    res = []
    for code, sp, tg in jobs:
        try:
            r = analyse(code, sp, a.max_docs)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] {code}: {e}", file=sys.stderr)
            continue
        r["target"] = tg
        res.append(r)
    if a.out:
        json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"wrote {a.out}: {len(res)} codes, {sum(1 for r in res if r['cands'])} with candidates", file=sys.stderr)


if __name__ == "__main__":
    main()
