#!/usr/bin/env python3
"""给已经查到结构的小分子补 ChEMBL 数据：理化性质、作用机制（含是否共价）、活性和选择性。每周增量更新。

候选来自 data/structures.json（fetch_structures.py 维护，有 InChIKey 的才查），按 InChIKey 精确匹配 ChEMBL 分子，
不靠药名，避免同名混淆。每个分子查 4 次：分子（性质）、机制、活性（pChEMBL 不为空）、活性涉及的靶点类型。
结果缓存在 data/chembl.json；查不到的记日期，90 天后再试；查到的 180 天后刷新。ChEMBL 接口慢（每次 5–15 秒），
所以并发查询，每次运行有数量和时间上限。

活性怎么汇总：
- 主靶点 = ChEMBL 机制表里的靶点；没有机制记录时，取单一蛋白里活性最强的那个。
- 生化活性：主靶点上各次测定 pChEMBL 的中位数（只算 IC50 / Ki / Kd / EC50，pChEMBL = -log10 摩尔浓度），附测定次数。
- 细胞活性：细胞系上 pChEMBL 中位数最高的那个。
- 选择性：除主靶点外，pChEMBL ≥ 6（≤ 1 µM）的人源单一蛋白个数，以及测过的单一蛋白总数。
  ChEMBL 只收录发表过的数据，测过的靶点少不代表选择性好，页面上要一起显示「测过几个」。

用法：
  python scripts/fetch_chembl.py                 # 增量查询
  python scripts/fetch_chembl.py --max 400 --minutes 60 --workers 6
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
API = "https://www.ebi.ac.uk/chembl/api/data/"
UA = {"User-Agent": "hit-or-miss/1.0 (https://github.com/yangsong0626/hit-or-miss)", "Accept": "application/json"}
RETRY_MISS_DAYS = 90
REFRESH_DAYS = 180
POT_TYPES = {"IC50", "Ki", "Kd", "EC50"}   # 不用 HTS 的 Potency、体内的 ED50


def get(path, params, tries=3):
    url = API + path + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=150) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))
            last = e  # noqa: F841


def fnum(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def lookup(ik):
    """按 InChIKey 查一个分子，返回缓存条目（不含日期）；ChEMBL 没有这个分子时返回 None。"""
    ms = get("molecule.json", {"molecule_structures__standard_inchi_key": ik,
                               "only": "molecule_chembl_id,pref_name,max_phase,molecule_properties,molecule_type,first_approval"}).get("molecules") or []
    if not ms:
        return None
    m = ms[0]
    cid = m["molecule_chembl_id"]
    p = m.get("molecule_properties") or {}
    out = {"id": cid, "pn": m.get("pref_name"), "ph": fnum(m.get("max_phase")), "fa": m.get("first_approval"),
           "p": {k: v for k, v in {"alogp": fnum(p.get("alogp")), "psa": fnum(p.get("psa")), "hbd": p.get("hbd"), "hba": p.get("hba"),
                                   "rtb": p.get("rtb"), "ro5": p.get("num_ro5_violations"), "qed": fnum(p.get("qed_weighted")),
                                   "ar": p.get("aromatic_rings"), "mf": p.get("full_molformula")}.items() if v is not None}}
    mech = get("mechanism.json", {"molecule_chembl_id": cid,
                                  "only": "action_type,mechanism_of_action,target_chembl_id,direct_interaction,mechanism_comment"}).get("mechanisms") or []
    out["mech"] = [{k: v for k, v in {"a": x.get("action_type"), "moa": x.get("mechanism_of_action"), "t": x.get("target_chembl_id"),
                                      "c": x.get("mechanism_comment")}.items() if v} for x in mech[:4]]
    acts = get("activity.json", {"molecule_chembl_id": cid, "pchembl_value__isnull": "false", "limit": 1000,
                                 "only": "target_chembl_id,target_pref_name,target_organism,pchembl_value,standard_type"}).get("activities") or []
    best = {}
    for a in acts:
        t, v = a.get("target_chembl_id"), fnum(a.get("pchembl_value"))
        if not t or v is None or a.get("standard_type") not in POT_TYPES:
            continue
        b = best.setdefault(t, {"vals": [], "tys": {}, "n": a.get("target_pref_name"), "o": a.get("target_organism")})
        b["vals"].append(v)
        b["tys"][a.get("standard_type")] = b["tys"].get(a.get("standard_type"), 0) + 1
    for b in best.values():
        vs = sorted(b["vals"])
        b["v"] = vs[-1]                                    # 最强的一次：选靶点、算脱靶用（脱靶宁可报多）
        b["med"] = round(vs[len(vs) // 2] if len(vs) % 2 else (vs[len(vs) // 2 - 1] + vs[len(vs) // 2]) / 2, 2)
        b["k"] = len(vs)
        b["ty"] = max(b["tys"], key=b["tys"].get)
    ttype = {}
    ids = list(best)
    for i in range(0, len(ids), 50):
        for t in get("target.json", {"target_chembl_id__in": ",".join(ids[i:i + 50]), "limit": 50,
                                     "only": "target_chembl_id,target_type"}).get("targets") or []:
            ttype[t["target_chembl_id"]] = t.get("target_type")
    prim = [x["t"] for x in out["mech"] if x.get("t")]
    prot = {t: b for t, b in best.items() if ttype.get(t) in ("SINGLE PROTEIN", "PROTEIN COMPLEX", "PROTEIN FAMILY", "PROTEIN COMPLEX GROUP")}
    human = {t: b for t, b in prot.items() if ttype.get(t) == "SINGLE PROTEIN" and (b.get("o") or "Homo sapiens") == "Homo sapiens"}
    pt = next((t for t in prim if t in prot), None) or (max(human, key=lambda t: human[t]["v"]) if human else None)
    if pt:
        b = prot[pt]
        out["bio"] = {"t": pt, "n": b["n"], "v": b["med"], "max": b["v"], "k": b["k"], "ty": b["ty"]}
    cells = [b for t, b in best.items() if ttype.get(t) == "CELL-LINE"]
    if cells:
        c = max(cells, key=lambda b: b["med"])
        out["cell"] = {"n": c["n"], "v": c["med"], "ty": c["ty"]}
    others = [t for t in human if t != pt and t not in prim]
    out["sel"] = {"off": sum(1 for t in others if human[t]["v"] >= 6), "tested": len(human),
                  "top": [human[t]["n"] for t in sorted(others, key=lambda t: -human[t]["v"]) if human[t]["v"] >= 6][:5]}
    return out


def mention_counts():
    """药名键在注册库试验里出现的次数，用来决定先查哪些。"""
    cnt = {}

    def add(n):
        k = re.sub(r"[^a-z0-9]", "", re.split(r"[(\[（]", n or "")[0].lower())
        if len(k) >= 4:
            cnt[k] = cnt.get(k, 0) + 1
    tp = os.path.join(ROOT, "data", "trials.json")
    if os.path.exists(tp):
        d = json.load(open(tp, encoding="utf-8"))
        for t in [t for v in d.get("sets", {}).values() for t in v] + d.get("early", []):
            for iv in t.get("iv") or []:
                add(iv.get("n"))
    for fn in ("docs/active.json", "docs/news.json"):
        p = os.path.join(ROOT, fn)
        if os.path.exists(p):
            j = json.load(open(p, encoding="utf-8"))
            for t in j.get("trials") or []:
                for iv in t.get("iv") or []:
                    add(iv.get("n"))
            for x in j.get("items") or []:
                add(x.get("drug"))
                add(x.get("drug"))
    return cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures", default=os.path.join(ROOT, "data", "structures.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "chembl.json"))
    ap.add_argument("--max", type=int, default=250, help="每次最多查多少个分子")
    ap.add_argument("--minutes", type=float, default=35, help="运行时间上限，到时间就保存退出")
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    items = json.load(open(a.structures, encoding="utf-8")).get("items", {})
    cache = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {"items": {}}
    C = cache.setdefault("items", {})
    today = dt.date.today()
    cnt = mention_counts()
    # 先查出现在靶点项目里的分子（上次构建的 docs/molecules.json）；化疗药之类没有靶点的排后面
    try:
        targeted = set(json.load(open(os.path.join(ROOT, "docs", "molecules.json"), encoding="utf-8")).get("drugs", {}))
    except (OSError, ValueError):
        targeted = set()
    todo, seen = [], set()
    for k, x in items.items():
        ik = x.get("ik")
        if not ik or ik in seen:
            continue
        seen.add(ik)
        c = C.get(ik)
        if c:
            age = (today - dt.date.fromisoformat(c.get("d", "2000-01-01"))).days
            if (c.get("miss") and age < RETRY_MISS_DAYS) or (not c.get("miss") and age < REFRESH_DAYS):
                continue
        keys = {k} | set(x.get("al") or [])
        todo.append((0 if keys & targeted else 1, -(sum(cnt.get(kk, 0) for kk in keys)), 0 if c is None else 1, ik, x.get("n")))
    todo.sort()
    todo = todo[: a.max]
    print(f"chembl: {len(todo)} molecules to look up ({len(C)} cached)", file=sys.stderr)

    lock, deadline, done = threading.Lock(), time.time() + a.minutes * 60, [0, 0, 0]

    def save():
        cache["generated"] = today.isoformat()
        tmp = a.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, a.out)

    def work(job):
        ik, name = job[-2], job[-1]
        if time.time() > deadline:
            return
        try:
            r = lookup(ik)
        except Exception as e:  # noqa: BLE001
            with lock:
                done[2] += 1
            print(f"  [err] {name}: {e}", file=sys.stderr)
            return
        with lock:
            C[ik] = dict(r, n=name, d=today.isoformat()) if r else {"n": name, "miss": True, "d": today.isoformat()}
            done[0 if r else 1] += 1
            if sum(done) % 20 == 0:
                save()
                print(f"  {sum(done)}/{len(todo)} · found {done[0]} · not in ChEMBL {done[1]} · errors {done[2]}", file=sys.stderr)

    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, todo))
    save()
    print(f"chembl: found {done[0]}, not in ChEMBL {done[1]}, errors {done[2]}; cache {len(C)}", file=sys.stderr)


if __name__ == "__main__":
    main()
