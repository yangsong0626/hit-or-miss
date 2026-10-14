#!/usr/bin/env python3
"""
Hit or Miss · ClinicalTrials.gov 全量抓取脚本

用官方 API v2 (https://clinicaltrials.gov/data-api/api) 拉四类数据，输出 trials.json：
  results   最近公布结果的 II/III 期试验（含主要终点 p 值）
  completed 主要完成日刚过、结果尚未公布的试验（读出即将到来）
  upcoming  未来半年内到达主要完成日的 III 期试验（催化剂日历）
  stopped   最近被终止 / 暂停 / 撤回的 II/III 期试验（含停止原因）

只用 Python 标准库，Mac 和 Windows 通用：
    python fetch_trials.py                # 默认：仅企业申办
    python fetch_trials.py --all-sponsors # 包含学术、政府申办
    python fetch_trials.py --days 365     # 回看窗口（默认 180 天）
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import date, timedelta

API = "https://clinicaltrials.gov/api/v2/studies"
UA = "HitOrMiss/1.0 (+https://github.com/yangsong0626/hit-or-miss) (personal research use)"


def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # 网络抖动或限流时退避重试
            if attempt == 3:
                raise
            wait = 2 ** attempt * 3
            print(f"  请求失败（{e}），{wait}s 后重试…", file=sys.stderr)
            time.sleep(wait)


def fetch_all(advanced, status=None, cap=3000, label=""):
    params = {"filter.advanced": advanced, "pageSize": 200, "format": "json"}
    if status:
        params["filter.overallStatus"] = ",".join(status)
    out, token = [], None
    while True:
        if token:
            params["pageToken"] = token
        data = get(params)
        out.extend(data.get("studies", []))
        print(f"  {label}: 已取 {len(out)} 条", file=sys.stderr)
        token = data.get("nextPageToken")
        if not token or len(out) >= cap:
            return out
        time.sleep(0.4)


# ---------- 分类启发式（可自行扩充） ----------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modality  # noqa: E402

# 旧版药物形式规则，已由 scripts/modality.py 取代，保留作参考
MOD_RULES = [
    (r"vedotin|deruxtecan|govitecan|tecan\b|rezetecan|pelitecan|ozogamicin|mafodotin|emtansine|tesirine|soravtansine|\bADC\b", "ADC"),
    (r"leucel|autoleucel|CAR[- ]?T|cabtagene|\w+cel\b|cell therapy|stem cell|T[- ]cells?\b|NK cells?\b", "细胞治疗"),
    (r"siran\b|siRNA", "siRNA"),
    (r"rsen\b|ersen\b|antisense", "反义寡核苷酸"),
    (r"gene therapy|AAV|vec\b|parvovec|gene editing|CRISPR|base edit", "基因 / 编辑治疗"),
    (r"tamab\b|tamig\b|bispecific|bi-specific", "双抗"),
    (r"mab\b|cept\b|antibody|immunoglobulin|\bIgG\b|IVIG", "抗体 / 融合蛋白"),
    (r"glutide|tide\b|tirzepatide|insulin|peptide|parathyroid|somatropin|hormone", "多肽 / 蛋白激素"),
    (r"vaccine|mRNA-|toxoid", "疫苗"),
    (r"ase alfa|ase beta|enzyme|botulinum|toxin|factor (VIII|IX|VII)", "酶 / 蛋白"),
    (r"radioligand|\b(177Lu|Lu-177|225Ac|Ac-225|68Ga|Ga-68|64Cu|Cu-64|18F|F-18)\b|lutetium|actinium|PSMA", "放射性药物"),
    (r"tinib\b|ciclib\b|rafenib\b|parib\b|lisib\b|degrader|lukast|azole\b|sartan\b|statin\b|pril\b|olol\b|"
     r"gliflozin\b|gliptin\b|dipine\b|prazole\b|vir\b|mycin\b|cillin\b|floxacin\b|cycline\b|platin\b|taxel\b|"
     r"mide\b|tidine\b|setron\b|triptan\b|gepant\b|pam\b|lam\b|done\b|pine\b|xaban\b|steroid|sone\b|lone\b|"
     r"cream|ointment|\bgel\b|tablet|capsule|\boral\b|ophthalmic", "小分子"),
    (r"\b[A-Z]{2,6}[- ]?\d{2,}", "代号分子（形式待定）"),
]
TA_RULES = [
    (r"cancer|carcinoma|tumou?r|lymphoma|leukemia|leukaemia|myeloma|melanoma|sarcoma|glioma|glioblastoma|neoplasm|\bNSCLC\b|oncolog|metasta|myelodysplas", "肿瘤"),
    (r"anemia|anaemia|hemophilia|haemophilia|sickle|thalass|thrombocytop|polycythemia|myelofibrosis|\bPNH\b|hemoglobinuria|neutropenia|von willebrand", "血液"),
    (r"heart|cardi|hypertension|atrial|coronary|lipid|cholesterol|triglycer|obesity|overweight|diabetes|kidney|renal|\bNASH\b|\bMASH\b|steatohepatitis|"
     r"stroke|thromb|embolism|vascular|arter|aortic|hyperkal|gout|uric|weight|thyroid|graves|acromegal|cushing|adrenal|hypoglyc", "心血管 / 代谢 / 肾"),
    (r"alzheimer|parkinson|epilep|seizure|multiple sclerosis|amyotrophic|migraine|neuropath|dystroph|\bALS\b|huntington|depress|schizophren|"
     r"bipolar|anxiety|autism|angelman|dementia|\bADHD\b|insomnia|sleep|\bpain\b|neuralgia|spinal muscular|ataxia|myotonic|tremor|narcolep|\bPTSD\b|substance|opioid|alcohol|smoking", "神经 / 精神 / 疼痛"),
    (r"arthritis|psoria|lupus|crohn|colitis|dermatitis|eczema|asthma|\bCOPD\b|urticaria|sj[oö]gren|myasthenia|\bIgA\b|hidradenitis|vitiligo|alopecia|"
     r"angioedema|proctitis|keratos|acne|rosacea|spondyl|sarcoid|vasculitis|eosinophil|rhinitis|allerg|prurigo|pemphig|scleroderma|systemic sclerosis|inflammat|autoimmun|celiac|esophagitis", "免疫 / 炎症"),
    (r"\bHIV\b|hepatitis|influenza|COVID|SARS|\bRSV\b|infection|bacterial|fungal|malaria|tubercul|pneumonia|sepsis|viral|virus|herpes|zoster|"
     r"meningococc|pneumococc|dengue|cytomegalo|\bCMV\b|vaccin|immuniz", "感染 / 疫苗"),
    (r"macular|retin|glaucoma|uveitis|ocular|\beyes?\b|vision|myopia|keratitis|dry eye|presbyopia|conjunctiv", "眼科"),
    (r"pulmonary fibrosis|idiopathic pulmonary|cystic fibrosis|bronchiect|lung disease|respiratory|cough", "呼吸"),
    (r"liver|cirrhosis|cholang|biliary|hepatic|pancreatit|gastro|bowel|\bIBS\b|constipation|reflux|\bGERD\b|dyspepsia|nausea", "消化 / 肝"),
    (r"endometriosis|menopaus|vasomotor|pregnan|contracept|fertility|polycystic ovary|uterine|bladder|prostat|urinar|incontinence|erectile|hypogonad|testosterone", "女性健康 / 泌尿"),
    (r"\brare\b|lysosomal|fabry|gaucher|pompe|mucopolysacch|amyloidosis|phenylketon|hemochrom|porphyri|achondroplas|growth hormone|osteogenesis|hypophosphat", "罕见病 / 遗传"),
]

# ---------- 申办方归并：子公司与历史名称归到母公司 ----------
SPONSOR_GROUPS = [
    (r"Hoffmann-La Roche|Genentech|Chugai|\bRoche\b", "Roche"),
    (r"AstraZeneca|MedImmune|Alexion|Acerta", "AstraZeneca"),
    (r"Merck Sharp|\bMSD\b|Merck & Co", "MSD"),
    (r"Merck KGaA|EMD Serono|SpringWorks", "Merck KGaA"),
    (r"GlaxoSmithKline|\bGSK\b|ViiV", "GSK"),
    (r"Novartis|Sandoz", "Novartis"),
    (r"Eli Lilly|\bLilly\b|Loxo", "Eli Lilly"),
    (r"AbbVie|Allergan|Pharmacyclics|Cerevel", "AbbVie"),
    (r"Pfizer|Seagen|Arena Pharm|Biohaven Pharm|Global Blood", "Pfizer"),
    (r"Janssen|Johnson & Johnson|Actelion|Intra-Cellular", "Johnson & Johnson"),
    (r"Sanofi|Genzyme|Bioverativ", "Sanofi"),
    (r"Bristol|Celgene|Karuna|Mirati|\bBMS\b|Juno", "Bristol Myers Squibb"),
    (r"Amgen|Horizon Therapeutics|ChemoCentryx", "Amgen"),
    (r"Novo Nordisk", "Novo Nordisk"),
    (r"Takeda|Shire|Millennium", "Takeda"),
    (r"Boehringer", "Boehringer Ingelheim"),
    (r"Bayer", "Bayer"),
    (r"Gilead|Kite|CymaBay", "Gilead"),
    (r"Regeneron", "Regeneron"),
    (r"Daiichi", "Daiichi Sankyo"),
    (r"Astellas", "Astellas"),
    (r"Otsuka", "Otsuka"),
    (r"Ipsen|Albireo", "Ipsen"),
    (r"BeiGene|BeOne", "BeOne (BeiGene)"),
    (r"HengRui|Hengrui|Shengdi|Suncadia", "Hengrui"),
    (r"Moderna", "Moderna"),
    (r"BioNTech", "BioNTech"),
    (r"Teva", "Teva"),
    (r"\bUCB\b", "UCB"),
    (r"Vertex", "Vertex"),
    (r"Biogen", "Biogen"),
    (r"Incyte", "Incyte"),
    (r"CSL", "CSL"),
    (r"Innovent", "Innovent"),
    (r"Kelun", "Kelun-Biotech"),
    (r"Chia Tai Tianqing", "CTTQ"),
]
_SUFFIX = re.compile(r"(,|\.|\s)\s*(Inc\.?|Incorporated|LLC|L\.L\.C\.|Ltd\.?|Limited|GmbH|AG|SE|S\.?A\.?S?|S\.p\.A\.?|SRL|B\.V\.|A/S|AB|plc|PLC|"
                     r"Corporation|Corp\.?|Co\.?,?|Company|and Co)\.?$", re.I)


def sponsor_group(name):
    for pat, g in SPONSOR_GROUPS:
        if re.search(pat, name, re.I):
            return g
    s = re.split(r",\s*(a|an)\s+.*(company|subsidiary)", name, flags=re.I)[0]
    for _ in range(3):
        s = _SUFFIX.sub("", s).strip(" ,.")
    s = re.sub(r"\s+(Research (&|and) Development|R&D|Development|Pharmaceuticals?|Pharma|Biopharma(ceuticals)?|"
               r"Therapeutics|Biotherapeutics|Biosciences?|Biotechnology|Biotech|Biologics|Medicine|Holdings?)(\s.*)?$", "", s, flags=re.I)
    return s.strip(" ,.") or name


# ---------- 终止原因归类 ----------
# 先去掉「与安全性 / 疗效无关」这类否定句，避免把否定当成原因
NEGATED = re.compile(r"\b(not|no|unrelated|non)[\s-]+((related|due|driven|based|attributable|linked|associated|because|any|new|or|and|"
                     r"unexpected|to|by|on|of|the|a|an|result|change|changes|in|with)[\s-]+){0,6}(safety|efficacy|benefit.risk)"
                     r"(\s+(concerns?|issues?|reasons?|signals?|risks?|findings?))?|other than safety|not as a result of [^.,;]*", re.I)
WHY_RULES = [
    (r"precaution|PK finding", "安全性"),
    (r"futil|efficacy|lack of (\w+ )?(benefit|effect|response|activity)|limited ([\w-]+ )?activity|did not (meet|improve|demonstrate|achieve)|"
     r"not met|interim|unlikely to|not demonstrat|benefit.risk|clinical benefit|DSMB|DMC|IDMC|IDMEAC|data monitoring|negative results", "疗效 / 无效性"),
    (r"had been demonstrated|objectives? (were |was )?(met|achieved)|completion of (overall )?program objectives|"
     r"sufficient to perform the analysis|no further .*(required|necessary)|no longer (necessary|required|needed)", "目标已达成"),
    (r"safety (concern|signal|issue|risk|finding|evaluation|review)|adverse|toxicit|tolerab|death|\bSAE\b|pericardial|hepatotox", "安全性"),
    (r"enrol|recruit|accru|feasib|eligible|event rate|operational|standard of care|clinical practice", "入组 / 运营"),
    (r"business|strateg|portfolio|commercial|corporate|priorit|pipeline|development (program|plan|policy)|stop the development|"
     r"redirect|focus (its )?resources|wind down|acquisition|acquired|merger|licens|book of business", "申办方决定 / 战略"),
    (r"fund|resources|financ", "资金"),
    (r"regulat|FDA|EMA|health authority|clinical hold", "监管"),
    (r"sponsor('s)? (decision|request)|sponsor decided|request of the sponsor|by (the )?sponsor|sponsor cancel|company decision|"
     r"decided not to|not to (proceed|continue|initiate)|administrative", "申办方决定 / 战略"),
]


def why_cat(why, status):
    if not why:
        return "未填写"
    text = NEGATED.sub(" ", why)
    for pat, label in WHY_RULES:
        if re.search(pat, text, re.I):
            return label
    return "申办方决定 / 战略" if text != why else "其他"


PLACEBO = re.compile(r"^(placebo|vehicle|saline|sham|standard of care|best supportive care|matching placebo)", re.I)


def classify(text, rules, default):
    for pat, label in rules:
        if re.search(pat, text, re.I):
            return label
    return default


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _pval(raw):
    raw = str(raw or "").strip()
    m = re.search(r"\d*\.?\d+(?:[eE]-?\d+)?", raw)
    if not m:
        return None
    try:
        v = float(m.group())
    except ValueError:
        return None
    return v * 0.999 if raw.startswith("<") else v


def details(study):
    """从注册库记录里提取判断成败所需的证据：设计、对照、主要终点的数值与统计分析、严重不良事件。"""
    p = study.get("protocolSection", {})
    design, arms = p.get("designModule", {}), p.get("armsInterventionsModule", {})
    di = design.get("designInfo", {}) or {}
    arm_types = [a.get("type", "") for a in arms.get("armGroups", [])]
    if any(t in ("PLACEBO_COMPARATOR", "SHAM_COMPARATOR") for t in arm_types):
        comp = "placebo"
    elif "ACTIVE_COMPARATOR" in arm_types:
        comp = "active"
    elif di.get("interventionModel") == "SINGLE_GROUP" or len(arm_types) <= 1:
        comp = "none"
    else:
        comp = "other"
    out = {
        "alloc": di.get("allocation", ""), "model": di.get("interventionModel", ""),
        "mask": (di.get("maskingInfo") or {}).get("masking", ""),
        "ntype": (design.get("enrollmentInfo") or {}).get("type", ""),
        "comp": comp, "arms": [{"l": a.get("label", "")[:60], "t": a.get("type", "")} for a in arms.get("armGroups", [])][:5],
    }
    rs = study.get("resultsSection", {})
    prims = []
    for om in rs.get("outcomeMeasuresModule", {}).get("outcomeMeasures", []):
        if om.get("type") != "PRIMARY" or len(prims) >= 2:
            continue
        gt = {g.get("id"): g.get("title", "")[:50] for g in om.get("groups", [])}
        dn = {}
        for d in om.get("denoms", [])[:1]:
            for c in d.get("counts", []):
                dn[c.get("groupId")] = _num(c.get("value"))
        meas = []
        try:
            meas = om["classes"][0]["categories"][0]["measurements"]
        except (KeyError, IndexError):
            pass
        groups = [{"t": gt.get(m.get("groupId"), ""), "v": _num(m.get("value")), "lo": _num(m.get("lowerLimit")),
                   "hi": _num(m.get("upperLimit")), "n": dn.get(m.get("groupId"))} for m in meas[:4]]
        ans = []
        for a in om.get("analyses", [])[:3]:
            ans.append({"pt": a.get("paramType", ""), "est": _num(a.get("paramValue")), "lo": _num(a.get("ciLowerLimit")),
                        "hi": _num(a.get("ciUpperLimit")), "ci": a.get("ciPctValue", ""), "p": _pval(a.get("pValue")),
                        "praw": str(a.get("pValue", ""))[:12], "m": a.get("statisticalMethod", "")[:40],
                        "ni": a.get("nonInferiorityType", ""), "g": [gt.get(g, "") for g in a.get("groupIds", [])][:3]})
        prims.append({"title": om.get("title", "")[:160], "tf": om.get("timeFrame", "")[:80], "unit": om.get("unitOfMeasure", "")[:40],
                      "pm": om.get("paramType", ""), "groups": groups, "an": ans})
    out["prim"] = prims
    sae = []
    for g in rs.get("adverseEventsModule", {}).get("eventGroups", [])[:5]:
        sae.append({"t": g.get("title", "")[:50], "s": g.get("seriousNumAffected"), "r": g.get("seriousNumAtRisk"),
                    "d": g.get("deathsNumAffected")})
    out["sae"] = sae
    return out


RATIO = re.compile(r"ratio|HR|OR\b|RR\b", re.I)


def _fmt(x):
    if x is None:
        return "?"
    return f"{x:.2f}" if abs(x) < 100 else f"{x:.0f}"


def assess(t):
    """按注册库证据给出判定（verdict）、证据要点（ev）和可能原因（why）。都是规则推断，不替代原始数据。"""
    dt = t.get("dt") or {}
    ev, why = [], []
    comp = dt.get("comp", "")
    comp_txt = {"placebo": "安慰剂对照", "active": "活性药物对照", "none": "单臂无对照", "other": "多组对比"}.get(comp, "")
    design = "，".join(x for x in [
        "随机" if dt.get("alloc") == "RANDOMIZED" else ("非随机" if dt.get("alloc") == "NON_RANDOMIZED" else ""),
        {"NONE": "开放标签", "SINGLE": "单盲", "DOUBLE": "双盲", "TRIPLE": "三盲", "QUADRUPLE": "四盲"}.get(dt.get("mask", ""), ""),
        comp_txt] if x)
    if design:
        ev.append(f"设计：{design}")
    if t.get("n"):
        ev.append(f"{'实际' if dt.get('ntype') == 'ACTUAL' else '计划'}入组 {t['n']} 例")

    # 严重不良事件：第一组视为试验组，最后一组视为对照组（注册库按登记顺序，可能不准）
    sae = [g for g in dt.get("sae", []) if g.get("r")]
    sae_gap = None
    if len(sae) >= 2:
        rates = [(g["t"], 100 * (g.get("s") or 0) / g["r"]) for g in sae]
        ev.append("严重不良事件：" + "；".join(f"{a} {b:.0f}%" for a, b in rates[:3]))
        sae_gap = max(r for _, r in rates) - min(r for _, r in rates)

    if t.get("_set") == "stopped" or t.get("status") in ("TERMINATED", "SUSPENDED", "WITHDRAWN"):
        if t.get("_set") == "stopped":
            verdict = "正常结束" if t.get("why_cat") == "目标已达成" else "终止"
            if t.get("why_cat"):
                why.append(f"申办方给出的原因归为「{t['why_cat']}」")
            if t.get("status") == "WITHDRAWN":
                why.append("试验在入组第一位受试者前撤回")
            elif dt.get("ntype") == "ACTUAL" and t.get("n") is not None and t["n"] < 50:
                why.append(f"终止时只入组了 {t['n']} 例，数据不足以判断药物本身")
            return {"verdict": verdict, "ev": ev, "why": why}

    prims = dt.get("prim", [])
    tested = []
    for pr in prims:
        an = [a for a in pr.get("an", []) if a.get("p") is not None]
        if an:
            best = min(an, key=lambda a: a["p"])
            tested.append((pr, best))
    for pr, a in tested:
        null = 1.0 if RATIO.search(a.get("pt", "")) else 0.0
        eff = f"{a['pt'] or '效应'} {_fmt(a['est'])}" if a.get("est") is not None else ""
        ci = f"（{a.get('ci') or 95}% CI {_fmt(a['lo'])}–{_fmt(a['hi'])}）" if a.get("lo") is not None and a.get("hi") is not None else ""
        ev.insert(len([e for e in ev if e.startswith("主要终点")]), f"主要终点「{pr['title'][:60]}」：{eff}{ci}，p={a['praw'] or _fmt(a['p'])}".replace("：，", "："))
        a["_null"] = null
    if not tested:
        g = prims[0]["groups"] if prims else []
        if prims and g:
            ev.insert(0, f"主要终点「{prims[0]['title'][:60]}」：" + "；".join(f"{x['t']} {_fmt(x['v'])}{prims[0]['unit'] and ' ' + prims[0]['unit'][:12]}" for x in g[:3]))
        verdict = "描述性" if comp in ("none", "") or not prims else "无统计检验"
        if verdict == "描述性":
            why.append("单臂或无对照设计，注册库只登记了描述性数据，无法用统计检验判断成败，需要和历史对照或同类药物比较")
        else:
            why.append("有对照组但没有登记主要终点的统计检验，只能看两组数值的差距")
        return {"verdict": verdict, "ev": ev, "why": why}

    sig = [a["p"] < 0.05 for _, a in tested]
    verdict = "达到" if all(sig) else ("未达到" if not any(sig) else "部分达到")
    n = t.get("n") or 0
    for (pr, a), ok in zip(tested, sig):
        null, est, lo, hi = a["_null"], a.get("est"), a.get("lo"), a.get("hi")
        ni = "NON_INFERIORITY" in (a.get("ni") or "") or "EQUIVALENCE" in (a.get("ni") or "")
        if ok:
            if ni:
                why.append("这是非劣效检验，达到意味着不比对照差，不代表更好")
            elif est is not None and lo is not None and hi is not None:
                dist = min(abs(lo - null), abs(hi - null))
                why.append("置信区间离无效线较远，效应稳健" if dist > 0.3 * max(abs(est - null), 1e-9) else "置信区间贴近无效线，效应幅度有限，需看次要终点和亚组是否一致")
        else:
            if est is not None and lo is not None and hi is not None and lo < null < hi:
                width = hi - lo
                if abs(est - null) < 0.25 * width or (null == 1.0 and abs(est - 1) < 0.06):
                    why.append("点估计几乎落在无效线上，两组基本没有差别，更像药物本身无效")
                else:
                    why.append("点估计偏向一侧但置信区间跨过无效线，可能是效应偏小或样本量不足以检出")
            elif a.get("p") is not None and a["p"] < 0.15:
                why.append(f"p={_fmt(a['p'])} 接近显著，可能是把握度不足，而非完全无效")
    if verdict != "达到":
        if comp == "active":
            why.append("对照组是活性药物，要超越现有疗法的门槛高于安慰剂对照")
        if n and n < 100:
            why.append(f"样本量只有 {n} 例，检出中等效应的把握度有限")
        if t.get("status") == "TERMINATED":
            why.append("试验提前终止，实际入组少于计划，统计把握度下降")
        if dt.get("comp") == "placebo":
            g = (tested[0][0].get("groups") or [])
            vals = [x["v"] for x in g if x.get("v") is not None]
            if len(vals) >= 2 and max(abs(v) for v in vals) > 0 and (max(vals) - min(vals)) / max(abs(v) for v in vals) < 0.15:
                why.append("各组数值非常接近，安慰剂组反应可能偏高")
    else:
        if comp == "none":
            why.append("单臂试验，p 值来自与基线或预设阈值的比较，不是与对照组比较，证据强度低于随机对照")
        if comp == "placebo":
            why.append("对照为安慰剂，证明了「有效」，但和现有疗法谁更好还需头对头数据")
        elif comp == "active":
            why.append("在活性药物对照下胜出，临床意义更强")
        if dt.get("mask") == "NONE":
            why.append("开放标签设计，主观终点可能有偏倚")
    if sae_gap is not None and sae_gap >= 5:
        why.append(f"各组严重不良事件率相差 {sae_gap:.0f} 个百分点，安全性需要关注")
    return {"verdict": verdict, "ev": ev, "why": list(dict.fromkeys(why))}


def pick(study):
    p = study.get("protocolSection", {})
    ident, stat = p.get("identificationModule", {}), p.get("statusModule", {})
    spons, cond = p.get("sponsorCollaboratorsModule", {}), p.get("conditionsModule", {})
    design, arms = p.get("designModule", {}), p.get("armsInterventionsModule", {})
    outs = p.get("outcomesModule", {})
    interventions = [i.get("name", "") for i in arms.get("interventions", [])
                     if i.get("type") != "OTHER" and not PLACEBO.match(i.get("name", "").strip())]
    conditions = cond.get("conditions", [])
    prim = outs.get("primaryOutcomes", [])

    # 主要终点的统计分析：取每个主要终点的最小 p 值
    pvals = []
    for om in study.get("resultsSection", {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", []):
        if om.get("type") != "PRIMARY":
            continue
        best = None
        for a in om.get("analyses", []):
            raw = str(a.get("pValue", "")).strip()
            m = re.search(r"[\d.]+(?:[eE]-?\d+)?", raw)
            if not m:
                continue
            try:
                v = float(m.group())
            except ValueError:
                continue
            if raw.startswith("<"):
                v = v * 0.999
            best = v if best is None else min(best, v)
        pvals.append({"title": om.get("title", "")[:160], "p": best})

    def d(key):
        return (stat.get(key) or {}).get("date", "")

    return {
        "nct": ident.get("nctId"),
        "title": ident.get("briefTitle", ""),
        "acronym": ident.get("acronym", ""),
        "sponsor": (spons.get("leadSponsor") or {}).get("name", ""),
        "group": sponsor_group((spons.get("leadSponsor") or {}).get("name", "")),
        "why_cat": why_cat(stat.get("whyStopped", ""), stat.get("overallStatus", "")) if stat.get("overallStatus") in ("TERMINATED", "SUSPENDED", "WITHDRAWN") else "",
        "collab": [c.get("name", "") for c in spons.get("collaborators", [])][:3],
        "phase": "/".join(x.replace("PHASE", "") for x in design.get("phases", [])),
        "n": (design.get("enrollmentInfo") or {}).get("count"),
        "status": stat.get("overallStatus", ""),
        "why": stat.get("whyStopped", ""),
        "pcd": d("primaryCompletionDateStruct"),
        "results": d("resultsFirstPostDateStruct"),
        "updated": d("lastUpdatePostDateStruct"),
        "conditions": conditions[:4],
        "interventions": interventions[:4],
        "primary": [o.get("measure", "")[:160] for o in prim[:2]],
        "pvals": pvals[:3],
        "iv": modality.iv_records(arms),
        "ta": classify(" ".join(conditions) + " " + ident.get("briefTitle", ""), TA_RULES, "其他"),
        "dt": details(study),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180, help="回看窗口天数")
    ap.add_argument("--ahead", type=int, default=180, help="催化剂日历前瞻天数")
    ap.add_argument("--all-sponsors", action="store_true", help="包含非企业申办")
    ap.add_argument("--out", default="trials.json")
    a = ap.parse_args()

    today = date.today()
    back = (today - timedelta(days=a.days)).isoformat()
    near = (today - timedelta(days=120)).isoformat()
    ahead = (today + timedelta(days=a.ahead)).isoformat()
    base = "AREA[StudyType]INTERVENTIONAL"
    if not a.all_sponsors:
        base += " AND AREA[LeadSponsorClass]INDUSTRY"
    p23 = f"{base} AND AREA[Phase](PHASE2 OR PHASE3)"

    print("拉取 ClinicalTrials.gov …", file=sys.stderr)
    sets = {
        "results": fetch_all(f"{p23} AND AREA[ResultsFirstPostDate]RANGE[{back},MAX]", label="新公布结果"),
        "completed": fetch_all(
            f"{p23} AND AREA[PrimaryCompletionDate]RANGE[{near},{today.isoformat()}] AND NOT AREA[ResultsFirstPostDate]RANGE[MIN,MAX]",
            status=["COMPLETED", "ACTIVE_NOT_RECRUITING"], label="刚完成待公布"),
        "upcoming": fetch_all(
            f"{base} AND AREA[Phase]PHASE3 AND AREA[PrimaryCompletionDate]RANGE[{today.isoformat()},{ahead}]",
            status=["ACTIVE_NOT_RECRUITING", "RECRUITING", "ENROLLING_BY_INVITATION"], label="即将完成"),
        "stopped": fetch_all(f"{p23} AND AREA[LastUpdatePostDate]RANGE[{near},MAX]",
                             status=["TERMINATED", "SUSPENDED", "WITHDRAWN"], label="提前终止"),
    }
    out = {"generated": today.isoformat(), "window_days": a.days, "industry_only": not a.all_sponsors,
           "sets": {k: [pick(s) for s in v] for k, v in sets.items()}}
    for k, v in out["sets"].items():
        for t in v:
            set_mod(t)
            t["_set"] = k
            if k in ("results", "stopped"):
                t["as"] = assess(t)
            t.pop("_set")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    counts = ", ".join(f"{k} {len(v)}" for k, v in out["sets"].items())
    print(f"完成：{counts} → {a.out}", file=sys.stderr)


def set_mod(t):
    t["mod"], t["mods"] = modality.classify_trial(t)
    t["modg"] = modality.GROUPS.get(t["mod"], "未识别")


def reclassify(path):
    """不重新联网，只按最新规则重算已有 trials.json 的领域和药物形式。"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    for v in d["sets"].values():
        for t in v:
            t["interventions"] = [x for x in t["interventions"] if not PLACEBO.match(x.strip())]
            set_mod(t)
            t["ta"] = classify(" ".join(t["conditions"]) + " " + t["title"], TA_RULES, "其他")
            t["group"] = sponsor_group(t["sponsor"])
            t["why_cat"] = why_cat(t.get("why", ""), t["status"]) if t["status"] in ("TERMINATED", "SUSPENDED", "WITHDRAWN") else ""
    for k, v in d["sets"].items():
        for t in v:
            if k in ("results", "stopped") and "dt" in t:
                t["_set"] = k
                t["as"] = assess(t)
                t.pop("_set")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--reclassify":
        reclassify(sys.argv[2])
    else:
        main()
