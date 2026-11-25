#!/usr/bin/env python3
"""药物别名表和研发代号前缀表，写到 data/drug_aliases.json，build_static.py 用它把同一个药的不同写法并成一页。

三个来源：
1. ClinicalTrials.gov 登记的 Other Names（受试药的官方别名，如 Giredestrant ↔ GDC-9545 / RO7197597）。确定性规则，不调用模型。
2. 研发代号前缀 → 公司：从试验里统计代号前缀和申办方的共现（SHR- 多半是恒瑞），一个前缀下至少 3 个不同代号、
   八成以上来自同一家公司才收。
3. 自由文本里的「药名 (代号)」配对（受试药描述、试验标题、新闻标题）：规则先找出候选，再用本机的 Claude Code
   （claude -p，走 claude.ai 订阅额度）逐条判断是不是同一个药——「Semaglutide Implant (NPM-139)」里的 NPM-139 是
   植入剂产品，不是 semaglutide 的别名。只有这一步需要 --llm，CI 不跑；判断结果缓存在输出文件里，不会重复问。

每条别名都带来源（NCT 号或新闻链接）和原文片段。旧文件里的条目会保留（本地没有 data/active.json 时不至于丢掉
CI 里收集到的别名）。

用法：
    python3 scripts/drug_aliases.py                 # 只做 1、2，CI 里每周跑
    python3 scripts/drug_aliases.py --llm           # 再用 claude -p 判断新的自由文本候选
    python3 scripts/drug_aliases.py --llm --dry-run # 只列出候选，不调用
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from molecules import core_names, nk  # noqa: E402
from modality import BACKBONE  # noqa: E402

OUT = os.path.join(ROOT, "data", "drug_aliases.json")
CJK = re.compile(r"[㐀-鿿]")
CODE = re.compile(r"^[a-z]{1,6}\d{2,}[a-z0-9]{0,4}$")
# 只用来防止把两个不同的药并到一起：带典型 INN 词干的名字基本就是一个独立的药
INN_STEM = re.compile(r"(mab|cept|tinib|rafenib|ciclib|parib|lisib|degib|zomib|metinib|sertib|nib|tide|glutide|siran|rsen|"
                      r"stat|previr|asvir|buvir|navir|tegravir|vir|tecan|vedotin|xaban|gatran|gliflozin|gliptin|platin|taxel|"
                      r"rubicin|citabine|trexed|lukast|setron|prazole|sartan|pril|dipine|olol|cycline|mycin|cillin|floxacin|"
                      r"plase|kinra|leukin|cel|gene|vec|degrade|bart|tug|stim|lutamide|relix|fungin|azole|mustine)$")
CTL = re.compile(r"placebo|standard of care|best supportive|saline|vehicle|sham|usual care|matching|dummy|"
                 r"investigator'?s? choice|physician'?s? choice|chemotherapy|radiotherapy|control", re.I)
COMBO = re.compile(r"\+|\band\b|\bplus\b|\bwith\b|combination|combined|regimen|/|;", re.I)
JUNK = re.compile(r"^(drug|study drug|investigational product|ip|test product|active|tablet|capsule|injection|infusion|"
                  r"solution|placebo|vaccine|treatment|arm [a-z0-9]|cohort|part|dose|low dose|high dose|reference|"
                  r"test|t|r|a|b|c|d|none|n/?a|not applicable|other names?|none other names?)$", re.I)

# 代号前缀统计：大写字母前缀 + 可选连字符 + 可选一个字母 + 至少两位数字
CODE_TOK = re.compile(r"\b([A-Z]{2,6})[- ]?([A-Z]{0,2}\d{2,}[A-Z0-9]*)\b")
PREFIX_STOP = {
    "CD", "IL", "PD", "HER", "GLP", "GIP", "FGF", "VEGF", "EGFR", "CAR", "TCR", "ADC", "NCT", "COVID", "SARS", "HPV",
    "HIV", "HBV", "HCV", "RSV", "CMV", "EBV", "AAV", "PET", "MRI", "CT", "BCMA", "TNF", "IFN", "PSMA", "FAP", "KRAS",
    "DLL", "TIGIT", "LAG", "CLDN", "GPRC", "FGFR", "CDK", "PARP", "BTK", "JAK", "TYK", "IGF", "PCSK", "APO", "ANG",
    "DNA", "RNA", "MRNA", "IU", "USP", "QD", "BID", "TID", "CYP", "OATP", "ISO", "ICH", "WHO", "FDA", "EU", "UK", "US",
    "USA", "GMP", "PK", "PD", "AE", "SAE", "MTD", "RP", "RPD", "DL", "TEAE", "PFS", "OS", "ORR", "DOR", "CR", "PR",
    "NSCLC", "SCLC", "HCC", "CRC", "AML", "ALL", "CLL", "MM", "DLBCL", "RCC", "TNBC", "MASH", "NASH", "CKD", "COPD",
    "HLA", "MHC", "NK", "CTLA", "TIM", "OX", "ICOS", "GITR", "TROP", "MET", "ALK", "ROS", "RET", "NTRK", "BRAF", "MEK",
    "ERK", "AKT", "MTOR", "PI", "ATR", "ATM", "WEE", "PLK", "AURKA", "BCL", "MCL", "IDH", "FLT", "KIT", "PDGFR", "SHP",
    "SOS", "TEAD", "YAP", "MAT", "PRMT", "EZH", "BET", "HDAC", "DNMT", "LSD", "MDM", "TP", "STING", "TLR", "NLRP",
    "GLS", "CCR", "CXCR", "CSF", "SIRP", "NKG", "LILRB", "TGF", "BMP", "ACVR", "ALK", "APOC", "LPA", "ANGPTL", "MC",
    "NPY", "OXT", "GHRH", "PTH", "FSH", "LH", "GNRH", "HSD", "AR", "ER", "PR", "GR", "MR", "SGLT", "DPP", "AMPK",
    "THR", "FXR", "PPAR", "ACC", "FASN", "SCD", "DGAT", "KHK", "GPR", "HCAR", "TRPV", "TRPA", "NAV", "KV", "CAV", "P2X",
    "MRGPRX", "HTR", "DRD", "NMDA", "AMPA", "GABA", "MGLU", "MAO", "COMT", "LRRK", "GBA", "SNCA", "MAPT", "APP",
    "BACE", "TREM", "CGRP", "TSLP", "ST", "OSM", "TL", "BAFF", "APRIL", "FCRN", "C", "MASP", "CFB", "CFD", "FXI",
    "FXIA", "FXII", "KLK", "PKK", "TTR", "HAO", "AGT", "INHBE", "ACTRII", "MSTN", "GDF", "UK", "PAH", "OTC",
    "PHASE", "STUDY", "COHORT", "PART", "ARM", "DOSE", "GROUP", "DAY", "WEEK", "CYCLE", "VISIT", "SCREEN", "LEVEL",
}


def clean(s):
    s = re.sub(r"[®™©]", "", str(s or "")).strip()
    s = re.sub(r"\s+(for|of|in)$", "", s, flags=re.I)
    return s.strip(" ,;:-.")


def single_name(s):
    """一个干预名 / 别名里只含一个药时返回干净的药名，否则 None。"""
    s = clean(s)
    if not s or CJK.search(s) or CTL.search(s):
        return None
    cs = [clean(x) for x in core_names(s)]
    cs = [x for x in cs if x and not JUNK.match(x) and len(nk(x)) >= 4]
    if len(cs) != 1:
        return None
    return cs[0]


def kind(name):
    """code：研发代号；inn：带 INN 词干的名字；word：其他单个名字（商品名、未带词干的通用名）；other：描述性短语。"""
    k = nk(name)
    if CODE.match(k):
        return "code"
    words = str(name).split()
    first = nk(words[0]) if words else ""
    if re.fullmatch(r"[a-z]{6,}", first) and len(words) <= 3 and all(re.fullmatch(r"[A-Za-z][A-Za-z\-]*", w) for w in words):
        return "inn" if INN_STEM.search(first) or INN_STEM.search(k) else "word"
    return "other"


def load_trials():
    trials = []
    try:
        t = json.load(open(os.path.join(ROOT, "data", "trials.json"), encoding="utf-8"))
        trials += list(t.get("early") or [])
        for v in (t.get("sets") or {}).values():
            trials += v
    except (OSError, ValueError) as e:
        print(f"[warn] data/trials.json: {e}", file=sys.stderr)
    try:
        trials += json.load(open(os.path.join(ROOT, "data", "active.json"), encoding="utf-8")).get("trials") or []
    except (OSError, ValueError):
        pass  # 只在 CI 里有（fetch_trials.py --active 生成，不入库）
    seen, out = set(), []
    for t in trials:
        if t.get("nct") and t["nct"] not in seen:
            seen.add(t["nct"])
            out.append(t)
    return out


def load_out():
    try:
        return json.load(open(OUT, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_out(d):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, OUT)


def pkey(a, b):
    return "|".join(sorted((nk(a), nk(b))))


GENERIC = re.compile(r"platinum|antihistamine|steroid|vaccine|antibiotic|anticoagulant|antiemetic|premedication|"
                     r"investigational|medicinal|supportive|analgesic|anesthetic|contrast|diuretic|vitamin|supplement|"
                     r"immunoglobulin|albumin|hormone|probiotic|nutrition", re.I)


def ok_pair(a, b, n, trials=None):
    """trials：出现过这对别名的不同试验数（旧数据没有时用 n）。"""
    ka, kb = kind(a), kind(b)
    t = n if trials is None else trials
    if "other" in (ka, kb) or nk(a) == nk(b) or JUNK.match(a) or JUNK.match(b) or GENERIC.search(a) or GENERIC.search(b):
        return False
    # 化疗、内分泌等骨干药被填进别名，多半是联用方案
    if (bool(BACKBONE.match(a)) or bool(BACKBONE.match(b))) and "code" in (ka, kb):
        return False
    if ka == kb == "inn" and nk(a)[:5] != nk(b)[:5]:
        return False
    # 两边都不是代号（通用名 ↔ 商品名，也可能是把联用药填成了别名）至少要在两个不同试验里出现
    if "code" not in (ka, kb):
        return t >= 2
    # 同一家公司前缀下的两个不同代号（ABX196 / ABX464）只凭一个试验不收，常见的是填错了代号
    if ka == kb == "code":
        pa, pb = re.match(r"[a-z]+", nk(a)).group(0), re.match(r"[a-z]+", nk(b)).group(0)
        if pa == pb and t < 2:
            return False
    return True


# ---------------- 1. CT.gov Other Names ----------------
def harvest_ctgov(trials):
    pairs = {}
    for t in trials:
        for iv in t.get("iv") or []:
            n = iv.get("n") or ""
            ons = iv.get("on") or []
            if not ons or iv.get("r") == "c" or COMBO.search(n) or len(ons) > 6:
                continue
            main = single_name(n)
            if not main:
                continue
            names = [main]
            for o in ons:
                if COMBO.search(o):
                    continue
                x = single_name(o)
                if x and nk(x) not in {nk(y) for y in names}:
                    names.append(x)
            if len(names) < 2:
                continue
            # 别名里有两个以上不同的 INN，多半是把方案里的几个药都列进来了
            if len({nk(x) for x in names if kind(x) == "inn"}) > 1:
                continue
            for o in names[1:]:
                if "other" in (kind(main), kind(o)):
                    continue
                k = pkey(main, o)
                p = pairs.setdefault(k, {"a": main, "b": o, "src": "ctgov", "n": 0, "t": 0, "ev": [], "_ncts": set()})
                p["n"] += 1
                if t["nct"] not in p["_ncts"]:
                    p["_ncts"].add(t["nct"])
                    p["t"] += 1
                if t["nct"] not in p["ev"] and len(p["ev"]) < 3:
                    p["ev"].append(t["nct"])
    return pairs


# ---------------- 2. 代号前缀 → 公司 ----------------
GEO = re.compile(r"^(jiangsu|shanghai|beijing|zhejiang|suzhou|guangzhou|shenzhen|hangzhou|sichuan|chengdu|nanjing|wuhan|"
                 r"tianjin|shandong|hunan|hubei|guangdong|fujian|anhui|chongqing|xiamen|hainan|hebei|henan|jiangxi|"
                 r"liaoning|jilin|yunnan|shaanxi|xian|ningbo|wuxi|changzhou|taizhou|lianyungang|zhuhai|dongguan|qingdao)$", re.I)


def co_key(co):
    """同一家公司的不同写法（Jiangsu Hansoh / Hansoh BioMedical）归到一个键：去掉地名后的第一个词。"""
    ws = [w for w in re.findall(r"[A-Za-z0-9]+", co or "") if not GEO.match(w)]
    return ws[0].lower() if ws else nk(co)


def learn_prefixes(trials, min_codes=3, min_share=0.7):
    by = collections.defaultdict(lambda: collections.defaultdict(set))
    names = collections.defaultdict(collections.Counter)
    for t in trials:
        co_full = (t.get("group") or t.get("sponsor") or "").strip()
        if not co_full:
            continue
        co = co_key(co_full)
        names[co][co_full] += 1
        for iv in t.get("iv") or []:
            if iv.get("r") == "c":
                continue
            for nm in [iv.get("n") or ""] + list(iv.get("on") or []):
                for m in CODE_TOK.finditer(nm):
                    pre = m.group(1)
                    if pre in PREFIX_STOP:
                        continue
                    by[pre][co].add(m.group(0))
    out = {}
    for pre, cos in by.items():
        allc = {re.sub(r"[- ]", "", c) for c in set().union(*cos.values())}
        if len(allc) < min_codes:
            continue
        co, codes = max(cos.items(), key=lambda kv: len(kv[1]))
        mine = {re.sub(r"[- ]", "", c) for c in codes}
        share = len(mine) / len(allc)
        if share < min_share:
            continue
        out[pre] = {"co": names[co].most_common(1)[0][0], "codes": len(allc), "share": round(share, 2),
                    "ex": sorted({re.sub(r"[- ]", "", c): c for c in codes}.values(), key=lambda c: (len(c), c))[:8]}
    return dict(sorted(out.items(), key=lambda kv: (-kv[1]["codes"], kv[0])))


# ---------------- 3. 自由文本候选 + claude -p 判断 ----------------
PAIR_RX = re.compile(r"([A-Za-z][A-Za-z0-9\-]{2,40}(?:\s[A-Za-z][A-Za-z0-9\-]{2,30}){0,2})\s*[(（]([^()（）]{3,60})[)）]")


def snippet(text, m, width=220):
    a, b = max(0, m.start() - width // 2), min(len(text), m.end() + width // 2)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


LEAD = {"a", "an", "the", "of", "to", "and", "or", "with", "drug", "drugs", "compare", "comparing", "evaluate", "evaluating",
        "investigational", "investigative", "study", "trial", "antibody", "monoclonal", "product", "novel", "new", "oral",
        "injection", "recombinant", "human", "humanized", "fully", "anti", "bispecific", "conjugate", "candidate",
        "inhibitor", "agonist", "antagonist", "vaccine", "therapy", "treatment", "dose", "doses", "safety", "efficacy",
        "without", "how", "evaluation", "for", "versus", "vs", "plus", "after", "before", "assess", "assessing", "determine",
        "test", "testing", "learn", "effect", "effects", "using", "use", "intravenous", "subcutaneous", "inhaled", "topical"}


def strip_lead(x):
    ws = str(x or "").split()
    while len(ws) > 1 and ws[0].lower() in LEAD:
        ws = ws[1:]
    return " ".join(ws)
TRIAL_CODE = re.compile(r"^[A-Za-z]{1,6}-?\d{2,}[A-Za-z]?-\d{3}$|^[A-Z]+-\d{3}$")


def left_name(s):
    """「A Study of XmAb20717」「Compare Sacituzumab Tirumotecan」→ 取最后一两个词里像药名的那部分。"""
    ws = s.split()
    for n in (2, 1):
        if len(ws) >= n:
            cand = ws[-n:]
            if n == 2 and cand[0].lower().strip(",.:;") in LEAD:
                continue
            x = " ".join(cand)
            if kind(x) != "other":
                return x
    return None


def common_words(trials, min_titles=15):
    c = collections.Counter()
    for t in trials:
        c.update({w.lower() for w in re.findall(r"[A-Za-z]{6,}", t.get("title") or "")})
    return {w for w, n in c.items() if n >= min_titles}


def find_candidates(trials, news, known):
    """known：已经由 CT.gov 别名或括号写法连起来的键对。返回 {pair_key: {a, b, snips:[{q, src}]}}。"""
    cands = {}
    common = common_words(trials)

    def add(a, b, text, m, src):
        if not a or TRIAL_CODE.match(b.strip()):
            return
        a, b = single_name(a), single_name(b)
        if not a or not b or nk(a) == nk(b):
            return
        ka, kb = kind(a), kind(b)
        if "code" not in (ka, kb) or "other" in (ka, kb):
            return
        if any(k == "word" and nk(x.split()[0]) in common for x, k in ((a, ka), (b, kb))):
            return
        k = pkey(a, b)
        if k in known:
            return
        c = cands.setdefault(k, {"a": a, "b": b, "snips": []})
        if len(c["snips"]) < 2 and all(s["src"] != src for s in c["snips"]):
            c["snips"].append({"q": snippet(text, m), "src": src})

    for t in trials:
        texts = [t.get("title") or ""] + [iv.get("ds") or "" for iv in t.get("iv") or [] if iv.get("r") != "c"]
        for text in texts:
            for m in PAIR_RX.finditer(text):
                inner = re.split(r"[,;]", m.group(2))[0]
                add(left_name(m.group(1)), inner, text, m, t["nct"])
    for x in news:
        text = x.get("t") or ""
        for m in PAIR_RX.finditer(text):
            inner = re.split(r"[,;]", m.group(2))[0]
            add(left_name(m.group(1)), inner, text, m, x.get("u") or "")
    return cands


LLM_SYSTEM = """You check candidate drug-name pairs for a clinical-trial tracker. Each candidate is two names (a, b) seen \
together in registry text or a news headline, usually written as "name (other name)". Decide for each whether a and b \
are the same drug substance, using only the quoted text plus well-established knowledge.

verdict:
- same: two names for one drug substance (development code and INN, old and new code, code and brand name of that drug).
- product: one name is a specific formulation, device or product that contains the other (an implant, a fixed-dose \
pill, a new formulation code), so they should not be merged.
- different: the parenthesis holds something else (a combination partner, a target, a trial or study code, a dose \
group, a sponsor, a comparator).
- unsure: the text does not settle it.

Answer "same" only when the text shows the equivalence (for example "atirmociclib (PF-07220060)") or you are certain \
from established knowledge. When in doubt, answer unsure. Keep note under 15 words."""

LLM_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "verdict", "note"],
                               "properties": {"id": {"type": "string"},
                                              "verdict": {"type": "string", "enum": ["same", "product", "different", "unsure"]},
                                              "note": {"type": "string"}}}}}}


def run_llm(cands, model, effort, jobs, chunk=40):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    cmd = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(LLM_SCHEMA), "--system-prompt", LLM_SYSTEM,
           "--tools", "", "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
           "--model", model, "--effort", effort]
    keys = sorted(cands)
    ids = {"c" + hashlib.md5(k.encode()).hexdigest()[:8]: k for k in keys}
    rid = {v: k for k, v in ids.items()}
    chunks = [keys[i:i + chunk] for i in range(0, len(keys), chunk)]
    out, lock, stop = {}, threading.Lock(), threading.Event()

    def one(i, ks):
        if stop.is_set():
            return
        payload = [{"id": rid[k], "a": cands[k]["a"], "b": cands[k]["b"], "quotes": [s["q"] for s in cands[k]["snips"]]} for k in ks]
        try:
            r = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
                               env=env, cwd=tempfile.gettempdir(), timeout=1200)
            res = json.loads(r.stdout or "{}")
        except (subprocess.TimeoutExpired, ValueError) as e:
            res = {"is_error": True, "result": type(e).__name__}
        with lock:
            so = res.get("structured_output")
            if res.get("is_error") or not isinstance(so, dict):
                why = str(res.get("result") or res.get("subtype") or "no output")[:200]
                print(f"[{i + 1}/{len(chunks)}] FAILED {why}", file=sys.stderr)
                if res.get("api_error_status") == 429 or re.search(r"limit|quota", why, re.I):
                    stop.set()
                return
            n = 0
            for it in so.get("items") or []:
                k = ids.get(it.get("id"))
                if k in cands:
                    out[k] = {"verdict": it.get("verdict"), "note": (it.get("note") or "")[:120]}
                    n += 1
            print(f"[{i + 1}/{len(chunks)}] {n}/{len(ks)} judged", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        list(ex.map(lambda a: one(*a), enumerate(chunks)))
    return out


def load_news():
    out = []
    for fn in ("news_readouts.json", "news_early.json"):
        try:
            out += json.load(open(os.path.join(ROOT, "data", fn), encoding="utf-8")).get("items") or []
        except (OSError, ValueError):
            pass
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--llm", action="store_true", help="judge new free-text candidates with claude -p (claude.ai plan)")
    ap.add_argument("--dry-run", action="store_true", help="with --llm: list candidates, do not call the model")
    ap.add_argument("--limit", type=int, default=0, help="with --llm: judge at most this many candidates")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--jobs", type=int, default=3)
    args = ap.parse_args()

    trials = load_trials()
    old = load_out()
    today = datetime.date.today().isoformat()

    pairs = harvest_ctgov(trials)
    for k, p in (old.get("pairs") or {}).items():   # 保留旧条目（本地没有 active.json 时不丢 CI 收集的）
        if p.get("src") != "ctgov":
            continue
        q = pairs.get(k)
        if q is None:
            pairs[k] = p
        else:
            q["n"] = max(q["n"], p.get("n", 0))
            q["ev"] = list(dict.fromkeys(q["ev"] + (p.get("ev") or [])))[:3]
            q["t"] = max(q["t"], p.get("t", 0))
    for p in pairs.values():
        p.pop("_ncts", None)
    pairs = {k: p for k, p in pairs.items() if ok_pair(p["a"], p["b"], p["n"], p.get("t"))}
    prefixes = learn_prefixes(trials)
    llm = {}
    for k, v in (old.get("llm") or {}).items():   # 旧判断：名字前面多带的词（Without / How …）顺手清掉
        v = dict(v, a=strip_lead(v.get("a")), b=strip_lead(v.get("b")))
        llm[pkey(v["a"], v["b"])] = v

    if args.llm:
        known = set(pairs) | set(llm)
        # 受试药名本身写成「通用名 (代号)」的，build_static 已经会合并，不必再问
        for t in trials:
            for iv in t.get("iv") or []:
                m = re.match(r"\s*([^()（）]+?)\s*[(（]([^()（）]+)[)）]", iv.get("n") or "")
                if m and single_name(m.group(1)) and single_name(m.group(2)):
                    known.add(pkey(single_name(m.group(1)), single_name(m.group(2))))
        cands = find_candidates(trials, load_news(), known)
        if args.limit:
            cands = dict(sorted(cands.items())[: args.limit])
        print(f"{len(cands)} new free-text candidates", file=sys.stderr)
        if args.dry_run:
            for k, c in sorted(cands.items()):
                print(f"{c['a']}  ⇄  {c['b']}   ·  {c['snips'][0]['src'][:40]}  ·  {c['snips'][0]['q'][:140]}")
            return
        if cands:
            got = run_llm(cands, args.model, args.effort, args.jobs)
            for k, v in got.items():
                c = cands[k]
                llm[k] = {"a": c["a"], "b": c["b"], "verdict": v["verdict"], "note": v["note"],
                          "q": c["snips"][0]["q"], "ev": [s["src"] for s in c["snips"]], "model": args.model, "date": today}

    d = {"generated": today,
         "_about": "药物别名（pairs：CT.gov 登记的 Other Names；llm：自由文本里的配对，经 claude -p 判断，verdict=same 的才用于合并）"
                   "和研发代号前缀（prefixes：前缀 → 最常见的申办方）。由 scripts/drug_aliases.py 生成。",
         "pairs": dict(sorted(pairs.items())), "llm": dict(sorted(llm.items())), "prefixes": prefixes}
    save_out(d)
    nsame = sum(1 for v in llm.values() if v.get("verdict") == "same")
    print(f"{len(pairs)} CT.gov alias pairs · {len(prefixes)} code prefixes · {len(llm)} free-text pairs judged ({nsame} same) → {OUT}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
