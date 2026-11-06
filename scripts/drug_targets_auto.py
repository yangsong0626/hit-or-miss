#!/usr/bin/env python3
"""自动学「研发代号 → 靶点」：不用人工维护药名表。

做法：在试验简介、受试药描述、新闻稿标题、摘要和正文、欧盟注册库标题里，找同一句话里代号和靶点挨着出现、
而且是机制写法的地方（"ARV-102, an oral PROTAC LRRK2 degrader"、"NEU-411, a LRRK2 inhibitor"），记一次证据。
同一个代号在多处出现时证据累加；最多的靶点占到一半以上、证据够多才采用。

  data/drug_target_evidence.json   新闻稿里攒下的证据（每周抓新闻时累加，长期保留）
  data/auto_drug_targets.json      构建时合并新闻证据和试验文本证据生成的最终对应表，targets.py 会读它

试验文本的证据每次构建重新算，不落盘。
"""
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import targets as tgmod  # noqa: E402

EVIDENCE = os.path.join(ROOT, "data", "drug_target_evidence.json")
AUTO = os.path.join(ROOT, "data", "auto_drug_targets.json")

CODE = re.compile(r"(?<![A-Za-z0-9-])([A-Z]{1,6}(?:-[A-Z]{1,3})?[- ]?\d{2,7}[A-Za-z]?)(?![A-Za-z0-9])")
NOT_CODE = re.compile(r"^(COVID|SARS|ASCO|ESMO|AACR|EASL|AASLD|ASH|ADA|EASD|ACC|AHA|ESC|NCT|ISO|ICD|ISRCTN|EUCT|CTIS|IND|NDA|BLA|MAA|"
                      r"FDA|EMA|NMPA|PMDA|CDE|Q|H|FY|ECOG|NYHA|BMI|HbA1c|A1C|TNM|AJCC|MDS|ISTH|SITC|WCLC|ATS|ERS|EULAR|ACR|AAN|"
                      r"CTAD|AAD|DDW|UEGW|CSCO|ELCC|EHA|EORTC|IDWeek|CROI|ENDO|PHASE|STEP|SURMOUNT|SELECT|CHAPTER|ARTICLE|FORM|"
                      r"RULE|SECTION|ITEM|TABLE|FIGURE|PART|COHORT|ARM|DAY|WEEK|MONTH|STAGE|GRADE|TYPE|CLASS|LEVEL|VERSION|V|"
                      r"[A-Z]{1,3}\d{4}$)", re.I)
SENT = re.compile(r"(?<=[。！？；])|(?<=[.!?;])\s+|\n+")
WIN = 110       # 代号前后多少字符内的靶点算数
MIN_SCORE = 1.5  # 证据分数达到多少才采用：一篇公司新闻稿摘要（1.5）或正文（2）、或两处试验文本
_TARGET_TOKEN = {}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def is_target_name(tok):
    """CD19、IL-23、HER2 这类本身是靶点名，不当代号。"""
    if tok not in _TARGET_TOKEN:
        D = tgmod.load()
        m = D["big"].fullmatch(tok) if hasattr(D["big"], "fullmatch") else None
        _TARGET_TOKEN[tok] = bool(m) or bool(tgmod._hits(tok, strict=False))
    return _TARGET_TOKEN[tok]


def codes_in(text):
    out = []
    for m in CODE.finditer(text or ""):
        tok = m.group(1)
        k = _norm(tok)
        if len(k) < 4 or NOT_CODE.match(tok.replace(" ", "")) or re.fullmatch(r"[a-z]+\d{4}", k) and int(k[-4:]) in range(1990, 2040):
            continue
        if sum(c.isdigit() for c in k) < 2 or is_target_name(tok):
            continue
        out.append((m.start(), m.end(), k, tok))
    return out


def mine(text, weight=1.0):
    """返回 [(代号键, 原写法, [靶点…], 权重)]。"""
    out = []
    for sent in SENT.split(text or ""):
        if len(sent) < 12:
            continue
        cs = codes_in(sent)
        if not cs:
            continue
        hits = tgmod._hits(sent, strict=True)
        if not hits:
            continue
        for s, e, k, tok in cs:
            near = [h for h in hits if abs(h[0] - s) <= WIN or abs(h[0] - e) <= WIN]
            if not near:
                continue
            # 句子里有几个代号时，靶点只归最近的那个代号
            mine_ = [h for h in near if min(cs, key=lambda c: min(abs(h[0] - c[0]), abs(h[0] - c[1])))[2] == k]
            tg = tgmod._uniq(mine_ or near, 2)
            if tg:
                out.append((k, tok, tg, weight / len(tg)))
    return out


def add(ev, pairs, today=None):
    today = today or dt.date.today().isoformat()
    for k, tok, tgs, w in pairs:
        e = ev.setdefault(k, {"n": tok, "tg": {}, "last": today})
        for g in tgs:
            e["tg"][g] = round(e["tg"].get(g, 0) + w, 2)
        e["last"] = today
    return ev


def load_evidence():
    try:
        return json.load(open(EVIDENCE, encoding="utf-8")).get("codes", {})
    except Exception:  # noqa: BLE001
        return {}


def save_evidence(ev):
    json.dump({"generated": dt.date.today().isoformat(), "codes": ev}, open(EVIDENCE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def trial_texts(t):
    """一条试验里可以学的文本：受试药描述（带上药名）、简介、标题。"""
    names = []
    for iv in t.get("iv") or []:
        nm = " / ".join([iv.get("n", "")] + list(iv.get("on") or []))
        names.append(nm)
        if iv.get("ds"):
            yield f"{nm}: {iv['ds']}", 1.0
    if t.get("sum"):
        yield t["sum"], 1.0
    if t.get("title"):
        yield t["title"], 1.0


def build_map(news_ev, trials, extra_texts=()):
    """合并新闻证据和试验文本证据，写 data/auto_drug_targets.json，返回对应表。"""
    ev = {k: {"n": v.get("n"), "tg": dict(v.get("tg", {}))} for k, v in news_ev.items()}
    for t in trials:
        seen = set()
        for text, w in trial_texts(t):
            for k, tok, tgs, ww in mine(text, w):
                if (k, tuple(tgs)) in seen:  # 同一条试验里重复说同一件事只算一次
                    continue
                seen.add((k, tuple(tgs)))
                add(ev, [(k, tok, tgs, ww)])
    for text, w in extra_texts:
        add(ev, mine(text, w))
    D = tgmod.load()
    out = {}
    for k, e in ev.items():
        if k in D["drugs"]:
            continue
        tg = sorted(e["tg"].items(), key=lambda x: -x[1])
        if not tg:
            continue
        total, top = sum(v for _, v in tg), tg[0][1]
        if top < MIN_SCORE or top / total < 0.5:
            continue
        keep = [g for g, v in tg if v >= max(MIN_SCORE, 0.5 * top)][:2]
        out[k] = {"n": e.get("n"), "tg": keep, "s": round(top, 1)}
    json.dump({"generated": dt.date.today().isoformat(), "map": out}, open(AUTO, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return out
