"""从试验记录里自动抽取受试药的靶点。

只认机制写法，避免把入组生物标志物当成靶点：
  - anti-XX、XX inhibitor / agonist / degrader / antibody / ADC / CAR-T …
  - targeting / inhibitor of / binds to … XX
  - 紧跟 mutant / positive / expressing / amplified 等词的 XX 视为生物标志物，不计
  - 前面是 prior / after / refractory to 等（既往治疗）的 XX 不计
文本来源按可靠程度：药名（含 data/target_dict.json 的药名 → 靶点表）、受试药描述、标题、简介、关键词，
取第一个有命中的来源。人工标注（data/targets.json）优先于自动抽取。
"""
import json
import os
import re

_DICT = None

MECH = (r"(?:inhibitors?|inhibiting|antagonists?|agonists?|inverse agonists?|degraders?|PROTACs?|molecular glues?|"
        r"modulators?|blockers?|blocking|neutrali[sz]ing|antibod(?:y|ies)|mAbs?|nanobod(?:y|ies)|ADCs?|"
        r"antibody[- ]drug conjugates?|conjugates?|bispecifics?|tri-?specifics?|binders?|activators?|potentiators?|"
        r"correctors?|stabili[sz]ers?|silencers?|siRNAs?|RNAi|antisense|ASOs?|oligonucleotides?|CAR[- ]?T|CAR[- ]?NK|"
        r"CAR\b|TCR[- ]?T|T[- ]?cell engagers?|engagers?|ligands?|radioligands?|radioconjugates?|traps?|decoys?|"
        r"targeted|targeting|directed|specific|selective|allosteric|covalent|mutant[- ]selective|gene therapy|"
        r"vaccines?|knockdown|lowering|silencing|editing|fusion proteins?|-Fc|Fc[- ]fusion|immunotoxins?)")
VERB_BEFORE = (r"(?:targeting|targets?|against|inhibits?|inhibition of|inhibitors? of|antagonists? of|agonists? of|"
               r"degraders? of|degrades?|degradation of|binds?(?: to)?|binding to|blocks?|blockade of|directed (?:against|at|to)|"
               r"specific (?:for|to)|selective (?:for|to)|antibod(?:y|ies) (?:to|against)|silenc(?:es|ing)|knock(?:s)? down|"
               r"activat(?:es|ing|or of)|modulat(?:es|ing|or of)|recogni[sz](?:es|ing))")
BIOMARKER_AFTER = re.compile(
    r"^[\s-]*(?:\(?\+\)?|mutant|mutated|mutations?|mut\b|positive|pos\b|amplified|amplification|over-?express\w*|expressing|"
    r"expression|deleted|deletion|deficien\w*|loss|negative|low\b|high\b|fusions?|rearrang\w*|altered|alterations?|"
    r"driven|dependent|wild[- ]type|wt\b|status|pretreated|refractory|resistant|exon|variants?|"
    r"(?:inhibitor|antibody|therapy|TKI)s?[- ](?:pretreated|naive|na[iï]ve|refractory|resistant|experienced|failed))", re.I)
PRIOR_BEFORE = re.compile(
    r"(?:prior|previous(?:ly)?|after|following|progress(?:ed|ion) (?:on|after)|failure of|failed|refractory to|resistant to|"
    r"pretreated with|treated with|received|receiving|ineligible for|intolerant (?:of|to)|na[iï]ve to|naive|post|standard|"
    r"standard of care|approved|including|such as|e\.g\.|"
    r"combination with|combined with|plus|with or without|in combination with)\W+(?:\w+\W+){0,3}$", re.I)
MECH_AFTER_RE = re.compile(r"[^.;:()]{0,32}?(?<![A-Za-z])" + MECH + r"(?![A-Za-z])", re.I)
VERB_BEFORE_RE = re.compile(VERB_BEFORE + r"[^.;:]{0,28}$", re.I)
EFFECTOR = {"CD3", "CD28", "CD16A", "4-1BB", "NKG2D", "CD47"}  # 双抗里的效应臂；有其他靶点时不计（CD47 单独出现时保留）


def _alias_re(a):
    cs = a.startswith("cs:")
    if cs:
        a = a[3:]
    if a.startswith("re:"):
        body = a[3:]
    else:
        body = re.escape(a).replace(r"\-", "[- ]?").replace(r"\ ", r"[\s-]?")
    body = body + r"(?![A-Za-z0-9])"
    return "(?-i:" + body + ")" if cs else body


def load(path=None):
    global _DICT
    if _DICT is not None and path is None:
        return _DICT
    path = path or os.path.join(os.path.dirname(__file__), "..", "data", "target_dict.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    pats = []
    for name, aliases in raw["targets"].items():
        if name.startswith("_"):
            continue
        alt = "|".join(_alias_re(a) for a in aliases)
        pats.append((name, alt))
    # 一个大正则：命名组 g0..gN 对应靶点
    names = [n for n, _ in pats]
    big = re.compile(r"(?<![A-Za-z0-9])(?=[\w(\[])(?:" + "|".join(f"(?P<g{i}>{alt})" for i, (_, alt) in enumerate(pats)) + ")", re.I)
    drugs = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in raw.get("drugs", {}).items() if not k.startswith("_")}
    _DICT = {"names": names, "big": big, "drugs": drugs}
    return _DICT


def _hits(text, strict=True):
    """返回 [(位置, 靶点)]；strict 时要求机制语境。"""
    if not text:
        return []
    D = load()
    out = []
    for m in D["big"].finditer(text):
        name = D["names"][int(m.lastgroup[1:])]
        s, e = m.start(), m.end()
        before, after = text[max(0, s - 60):s], text[e:e + 60]
        if strict:
            if BIOMARKER_AFTER.match(after):
                continue
            anti = re.search(r"anti[- ]?(?:human[- ])?$", before, re.I)
            mech_after = MECH_AFTER_RE.match(after[:45])
            verb_before = VERB_BEFORE_RE.search(before[-50:])
            if not (anti or mech_after or verb_before):
                continue
            if PRIOR_BEFORE.search(before[:-6] if anti else before) and not verb_before:
                continue
        out.append((s, name, text[max(0, s - 40):e + 40]))
    return out


def _uniq(hits, limit=3):
    seen = []
    for h in sorted(hits):
        n = h[1]
        if n not in seen:
            seen.append(n)
    if len(seen) > 1:
        seen = [n for n in seen if n not in EFFECTOR] or seen
    return seen[:limit]


def _drug_map(names):
    D = load()
    for nm in names:
        k = re.sub(r"[^a-z0-9]", "", (nm or "").lower())
        if not k:
            continue
        for drug, tg in D["drugs"].items():
            if k == drug or (len(drug) >= 6 and k.startswith(drug)):
                return [tg] if isinstance(tg, str) else list(tg)
    return []


def extract_pairs(t, cands=None):
    """返回 [(干预或 None, [靶点…])]。先逐个受试药找（药名表、药名、该药的描述），这样靶点和药物形式对得上；
    都找不到时再用标题、简介里提到受试药的句子和关键词，此时干预为 None。"""
    cands = cands if cands is not None else (t.get("iv") or [])
    pairs = []
    for iv in cands:
        names = [iv.get("n", "")] + list(iv.get("on") or [])
        tg = _drug_map(names)
        if not tg:
            h = _hits(" ; ".join(names)) or _hits(iv.get("ds", ""))
            tg = _uniq(h) if h else []
        if tg:
            pairs.append((iv, tg))
    if pairs:
        return pairs
    names = [x for iv in cands for x in [iv.get("n", "")] + list(iv.get("on") or [])]
    toks = {w.lower() for nm in names for w in re.findall(r"[A-Za-z][\w-]{2,}", nm)
            if not re.fullmatch(r"(?i)injection|tablets?|capsules?|dose|low|high|mg|placebo|infusion|for|and|the|oral|cohort|part|arm", w)}
    sents = [x for x in re.split(r"(?<=[.;])\s+", t.get("sum", "")) if any(k in x.lower() for k in toks)]
    for src in (t.get("title", ""), " ".join(sents)):
        h = _hits(src)
        if h:
            return [(None, _uniq(h))]
    for kw in t.get("kw") or []:
        h = _hits(kw, strict=False)
        if h and len(kw) <= 30 and not re.search(r"mutat|positive|amplif|express|fusion|deleted|negative|deficien", kw, re.I):
            return [(None, _uniq(h, 2))]
    return []


def extract(t, cands=None):
    """返回靶点列表（可能为空）。"""
    out = []
    for _, tg in extract_pairs(t, cands):
        for g in tg:
            if g not in out:
                out.append(g)
    return out[:4]


def canonical(label):
    """把人工标注的靶点名映射到词典里的规范名，返回列表（「PD-1 × VEGF」→ 两个靶点）；映射不到就原样返回。"""
    if not label:
        return []
    D = load()
    if label in D["names"]:
        return [label]
    h = _hits(label, strict=False)
    return _uniq(h, 4) if h else [label]
