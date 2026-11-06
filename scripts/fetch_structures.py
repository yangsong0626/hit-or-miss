#!/usr/bin/env python3
"""给小分子药物查结构（PubChem），每周增量更新。

候选药名来自新闻稿读出库和注册库试验（新结果、待公布、即将完成、提前终止、在研），只查小分子和降解剂；
抗体、细胞、核酸这类没有可画的单一结构，跳过。查到的写进 data/structures.json，查不到的记下日期，
120 天后再试。每次最多查 MAX_LOOKUPS 个，PubChem 限速每秒 5 次以内。

页面用 docs/structures.json：{药名键: [CID, SMILES, 分子量]}，药名键是小写字母数字（通用名和研发代号都收）。
结构图直接用 PubChem 的图片地址，不在本站渲染。

用法：
  python scripts/fetch_structures.py              # 增量查询并导出
  python scripts/fetch_structures.py --export-only
"""
import argparse, datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import modality  # noqa: E402

UA = {"User-Agent": "hit-or-miss/1.0 (https://github.com/yangsong0626/hit-or-miss)"}
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/property/{}/JSON"
PROPS = ["SMILES,InChIKey,MolecularWeight", "CanonicalSMILES,InChIKey,MolecularWeight"]
MAX_LOOKUPS = 600
RETRY_DAYS = 120
SMALL = re.compile(r"小分子|降解剂")
NOT_SMALL = re.compile(r"(mab|cept|ase|cel|leucel|gene|vec|siran|rsen|sen|tide|glutide|kin|ermin|plasmin)$", re.I)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _clean(name):
    name = re.split(r"[(\[]", name or "")[0]
    name = re.sub(r"\b(tablets?|capsules?|oral|injection|hydrochloride|hcl|mesylate|maleate|sodium|potassium|tosylate|citrate|"
                  r"fumarate|succinate|tartrate|besylate|phosphate|sulfate|monohydrate|free base|\d+\s*mg)\b", " ", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" ,;-")


def candidates():
    """返回 {查询名: 别名集合}。"""
    out = {}

    def add(name, aliases=(), mod=""):
        q = _clean(name)
        if len(_norm(q)) < 4 or NOT_SMALL.search(q) or re.search(r"[+/&]| and | with |MDI|HFA|liposom|vaccine|placebo", q, re.I):
            return
        if mod and not SMALL.search(mod):
            return
        if not mod:
            m = modality.classify_one({"n": q, "ty": "DRUG"})
            if not SMALL.search(m or ""):
                return
        out.setdefault(q, set()).update(_norm(a) for a in aliases if len(_norm(a)) >= 4)

    tp = os.path.join(ROOT, "data", "trials.json")
    if os.path.exists(tp):
        for s, v in json.load(open(tp, encoding="utf-8")).get("sets", {}).items():
            for t in v:
                for iv in t.get("iv") or []:
                    if (iv.get("ty") or "DRUG") not in ("DRUG", "COMBINATION_PRODUCT") or modality.PLACEBO.search(iv.get("n", "")):
                        continue
                    if modality.BACKBONE.match((iv.get("n") or "").strip()):
                        continue
                    add(iv["n"], iv.get("on") or [], t.get("mod", "") if len(t.get("iv") or []) == 1 else "")
    for f in ("active.json",):
        p = os.path.join(ROOT, "docs", f)
        if os.path.exists(p):
            for t in json.load(open(p, encoding="utf-8")).get("trials", []):
                for iv in t.get("iv") or []:
                    add(iv.get("n", ""), iv.get("on") or [], t.get("mod", "") if len(t.get("iv") or []) == 1 else "")
    np_ = os.path.join(ROOT, "data", "news_readouts.json")
    if os.path.exists(np_):
        for x in json.load(open(np_, encoding="utf-8")).get("items", []):
            d = x.get("drug") or ""
            m = re.search(r"\(([^)]+)\)", d)
            en = m.group(1) if m else d
            if en and not re.search(r"[一-鿿]", en):
                add(en, [d], x.get("mod", ""))
    return out


def lookup(name):
    for props in PROPS:
        url = PUG.format(urllib.parse.quote(name), props)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                p = json.load(r)["PropertyTable"]["Properties"][0]
            smi = p.get("SMILES") or p.get("CanonicalSMILES") or p.get("IsomericSMILES") or ""
            return {"cid": p["CID"], "smi": smi, "ik": p.get("InChIKey", ""), "mw": round(float(p.get("MolecularWeight") or 0), 1)}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 400:
                continue  # 属性名不认，换旧名字再试
            raise
    return None


def export(cache_path, out_path):
    if not os.path.exists(cache_path):
        return 0
    c = json.load(open(cache_path, encoding="utf-8")).get("items", {})
    m = {}
    for k, v in c.items():
        if not v.get("cid") or (v.get("mw") or 0) > 1500:
            continue
        row = [v["cid"], v.get("smi", ""), v.get("mw")]
        for a in [k] + (v.get("al") or []):
            m.setdefault(a, row)
    json.dump(m, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return len(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "structures.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "structures.json"))
    ap.add_argument("--max", type=int, default=MAX_LOOKUPS)
    ap.add_argument("--export-only", action="store_true")
    a = ap.parse_args()
    if not a.export_only:
        cache = json.load(open(a.cache, encoding="utf-8")) if os.path.exists(a.cache) else {"items": {}}
        items = cache["items"]
        today = dt.date.today()
        todo = []
        for q, al in candidates().items():
            k = _norm(q)
            v = items.get(k)
            if v and v.get("cid"):
                v["al"] = sorted(set(v.get("al") or []) | (al - {k}))
                continue
            if v and v.get("miss") and (today - dt.date.fromisoformat(v["miss"])).days < RETRY_DAYS:
                continue
            todo.append((q, k, al))
        n = hit = fails = 0
        for q, k, al in todo[: a.max]:
            n += 1
            try:
                r = lookup(q)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"  [warn] PubChem {q}: {e}", file=sys.stderr)
                if fails >= 10:
                    print("  [warn] too many PubChem errors, stopping this run", file=sys.stderr)
                    break
                continue
            if r:
                items[k] = {"n": q, **r, "al": sorted(al - {k}), "d": today.isoformat()}
                hit += 1
            else:
                items[k] = {"n": q, "miss": today.isoformat()}
            time.sleep(0.25)
        json.dump(cache, open(a.cache, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print(f"structures: looked up {n} (found {hit}), pending {max(0, len(todo) - a.max)}, cached {sum(1 for v in items.values() if v.get('cid'))}")
    print(f"docs/structures.json: {export(a.cache, a.out)} keys")


if __name__ == "__main__":
    main()
