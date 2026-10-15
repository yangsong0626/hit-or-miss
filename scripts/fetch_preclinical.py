#!/usr/bin/env python3
"""临床前靶点自动打分：从 Open Targets Platform（已汇总 ChEMBL、DepMap / Project Score、COSMIC、IntOGen、
gnomAD、可成药性分档、化学探针和安全性数据）拉取与「癌症」相关的靶点，去掉已有临床项目的，按四个维度打分。

  证据 E   体细胞驱动（Cancer Gene Census、IntOGen、ClinVar 体细胞、肿瘤标志物）、功能依赖（CRISPR 筛选、
           Project Score）、胚系遗传学；三者按「至少有一类强证据」合并，0–1
  可成药 D 按 Open Targets 可成药性分档：小分子（配体、结构、口袋、可成药家族）、抗体（膜定位 / 分泌）、
           降解剂（泛素化证据、小分子结合）；核酸药物对任何基因都可做，给 0.2 保底
  热度     Europe PMC 文献共现分，越高越多人研究
  风险     DepMap 核心必需基因、已知安全事件、gnomAD 功能缺失不耐受

「临床前」= 该靶点所有药物和候选药的最高阶段都低于 IND（Open Targets 的 drugAndClinicalCandidates）。
失败时不覆盖旧文件、返回 0，免得拖垮每周更新。

用法：python scripts/fetch_preclinical.py [--out data/preclinical_auto.json] [--max-age-days 25] [--top 200]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request

API = "https://api.platform.opentargets.org/api/v4/graphql"
CANCER_IDS = ["MONDO_0004992", "EFO_0000311"]  # cancer；旧版本用 EFO
STAGE_IDX = {"UNKNOWN": 0, "PRECLINICAL": 1, "IND": 2, "EARLY_PHASE_1": 3, "PHASE_1": 4, "PHASE_1_2": 5, "PHASE_2": 6,
             "PHASE_2_3": 7, "PHASE_3": 8, "PREAPPROVAL": 9, "APPROVAL": 10, "PHASE_4": 11, "WITHDRAWAL": 12}
SOMATIC = ("cancer_gene_census", "intogen", "eva_somatic", "cancer_biomarkers")
DEPEND = ("crispr", "crispr_screen", "ot_crispr")
GERMLINE = ("gwas_credible_sets", "gene_burden", "eva", "genomics_england", "orphanet", "gene2phenotype",
            "uniprot_literature", "uniprot_variants", "clingen")
SM_W = {"high-quality ligand": .9, "structure with ligand": .8, "high-quality pocket": .7, "med-quality pocket": .5,
        "druggable family": .5}
AB_W = {"uniprot loc high conf": .7, "go cc high conf": .6, "uniprot loc med conf": .5, "uniprot sigp or tmhmm": .5,
        "go cc med conf": .4, "human protein atlas loc": .4}
PR_W = {"small molecule binder": .5, "literature": .4, "uniprot ubiquitination": .4, "database ubiquitination": .3,
        "half-life data": .3}
MOD_NAME = {"SM": "小分子", "AB": "抗体", "PR": "降解剂", "OC": "核酸"}

Q_ASSOC = """query($id:String!,$i:Int!,$n:Int!){disease(efoId:$id){id name
 associatedTargets(page:{index:$i,size:$n},enableIndirect:true){count rows{score target{id approvedSymbol}
 datasourceScores{id score}}}}}"""
T_FIELDS = """id approvedSymbol approvedName biotype isEssential
 tractability{label modality value} chemicalProbes{isHighQuality}
 safetyLiabilities{event} geneticConstraint{constraintType oe upperBin6}
 drugAndClinicalCandidates{count rows{maxClinicalStage}}"""


def post(query, variables=None, tries=4):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for k in range(tries):
        try:
            req = urllib.request.Request(API, body, {"Content-Type": "application/json", "User-Agent": "hit-or-miss/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                out = json.load(r)
            if out.get("errors") and not out.get("data"):
                raise RuntimeError(out["errors"][0].get("message", "graphql error"))
            return out["data"]
        except Exception as e:  # noqa: BLE001
            if k == tries - 1:
                raise
            print(f"  retry {k + 1}: {e}", file=sys.stderr)
            time.sleep(3 * (k + 1))


def fetch_assoc(post_fn, limit):
    last = None
    for did in CANCER_IDS:
        rows, i, n = [], 0, 500
        try:
            while len(rows) < limit:
                d = post_fn(Q_ASSOC, {"id": did, "i": i, "n": n})["disease"]
                if not d:
                    break
                page = d["associatedTargets"]["rows"]
                rows += page
                if len(page) < n or len(rows) >= d["associatedTargets"]["count"]:
                    break
                i += 1
        except Exception as e:  # noqa: BLE001
            last = e
            continue
        if rows:
            return did, rows[:limit]
    raise RuntimeError(f"no association data ({last})")


def fetch_targets(post_fn, ids, batch=20):
    out = {}
    for s in range(0, len(ids), batch):
        chunk = ids[s:s + batch]
        q = "query{" + " ".join(f't{j}:target(ensemblId:"{e}"){{{T_FIELDS}}}' for j, e in enumerate(chunk)) + "}"
        d = post_fn(q)
        for j, e in enumerate(chunk):
            if d.get(f"t{j}"):
                out[e] = d[f"t{j}"]
    return out


def ds(row, keys):
    m = {x["id"]: x["score"] for x in row.get("datasourceScores") or []}
    return max([m.get(k, 0) or 0 for k in keys] + [0])


def score(assoc_row, t):
    som, dep, gen = ds(assoc_row, SOMATIC), ds(assoc_row, DEPEND), ds(assoc_row, GERMLINE)
    lit = ds(assoc_row, ("europepmc",))
    E = 1 - (1 - som) * (1 - dep) * (1 - 0.5 * gen)
    best = {"SM": 0.0, "AB": 0.0, "PR": 0.0, "OC": 0.2}
    labels = []
    for x in t.get("tractability") or []:
        if not x.get("value"):
            continue
        lab, mo = (x.get("label") or "").lower(), x.get("modality")
        w = {"SM": SM_W, "AB": AB_W, "PR": PR_W}.get(mo, {}).get(lab)
        if w:
            best[mo] = max(best[mo], w)
            labels.append(f"{mo}:{x['label']}")
    mod = max(best, key=best.get)
    D = best[mod]
    probe = any(p.get("isHighQuality") for p in t.get("chemicalProbes") or [])
    ligand = any(l.lower() in ("sm:high-quality ligand", "sm:structure with ligand") for l in labels) or probe
    gc = next((g for g in t.get("geneticConstraint") or [] if g.get("constraintType") == "lof"), None)
    flags = []
    if t.get("isEssential"):
        flags.append("核心必需基因")
    nsafe = len({s.get("event") for s in t.get("safetyLiabilities") or []})
    if nsafe:
        flags.append(f"安全事件 {nsafe}")
    if gc and gc.get("upperBin6") is not None and gc["upperBin6"] <= 1:
        flags.append("功能缺失不耐受")
    if E >= 0.5 and ligand:
        tag = "化学成熟 · 待验证"
    elif E >= 0.5 and best["SM"] >= 0.5:
        tag = "证据强 · 化学空白"
    elif E >= 0.5 and best["AB"] >= 0.6:
        tag = "证据强 · 抗体可及"
    elif E >= 0.5:
        tag = "证据强 · 难成药"
    else:
        tag = "证据一般"
    S = 0.6 * E + 0.4 * max(best["SM"], best["AB"], best["PR"]) - (0.3 if t.get("isEssential") else 0) - 0.05 * min(nsafe, 3)
    r3 = lambda v: round(v, 3)  # noqa: E731
    return {"sym": t.get("approvedSymbol"), "name": t.get("approvedName"), "ens": t.get("id"),
            "S": r3(S), "E": r3(E), "som": r3(som), "dep": r3(dep), "gen": r3(gen), "lit": r3(lit),
            "D": r3(D), "sm": r3(best["SM"]), "ab": r3(best["AB"]), "pr": r3(best["PR"]), "mod": MOD_NAME[mod],
            "probe": probe, "lig": ligand, "tract": labels[:8], "flags": flags, "tag": tag}


def is_preclinical(t):
    rows = (t.get("drugAndClinicalCandidates") or {}).get("rows") or []
    return all(STAGE_IDX.get(r.get("maxClinicalStage") or "UNKNOWN", 0) == 1 for r in rows)


def run(post_fn, limit=3000, top=200, min_e=0.3):
    did, assoc = fetch_assoc(post_fn, limit)
    byid = {r["target"]["id"]: r for r in assoc}
    pre_e = {e: r for e, r in byid.items()
             if 1 - (1 - ds(r, SOMATIC)) * (1 - ds(r, DEPEND)) * (1 - 0.5 * ds(r, GERMLINE)) >= min_e}
    print(f"{did}: {len(assoc)} associated targets, {len(pre_e)} with evidence ≥ {min_e}")
    tdata = fetch_targets(post_fn, list(pre_e))
    rows, clinical = [], 0
    for e, t in tdata.items():
        if t.get("biotype") and t["biotype"] != "protein_coding":
            continue
        if not is_preclinical(t):
            clinical += 1
            continue
        rows.append(score(pre_e[e], t))
    rows.sort(key=lambda r: -r["S"])
    print(f"{clinical} already clinical, {len(rows)} preclinical scored")
    return {"asof": dt.date.today().isoformat(), "source": "Open Targets Platform", "disease": did,
            "scanned": len(assoc), "evidence_pass": len(pre_e), "clinical_removed": clinical,
            "n": len(rows), "rows": rows[:top]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "preclinical_auto.json"))
    ap.add_argument("--max-age-days", type=int, default=25, help="已有文件比这更新就跳过（Open Targets 每季度才发版）")
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--limit", type=int, default=3000)
    a = ap.parse_args()
    if os.path.exists(a.out) and a.max_age_days > 0:
        try:
            old = json.load(open(a.out, encoding="utf-8"))
            age = (dt.date.today() - dt.date.fromisoformat(old["asof"])).days
            if age < a.max_age_days:
                print(f"{a.out} is {age} days old, skip")
                return 0
        except Exception:  # noqa: BLE001
            pass
    try:
        res = run(post, a.limit, a.top)
        if res["n"] < 30:
            raise RuntimeError(f"only {res['n']} rows, refusing to overwrite")
    except Exception as e:  # noqa: BLE001
        print(f"preclinical fetch failed, keeping previous file: {e}", file=sys.stderr)
        return 0
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out} · {res['n']} preclinical targets, top {len(res['rows'])} kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
