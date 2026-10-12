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
import argparse, json, re, sys, time, urllib.parse, urllib.request
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
    (r"Merck Sharp|\bMSD\b|Merck & Co|Organon", "MSD"),
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
WHY_RULES = [
    # 明确的商业 / 战略措辞，以及「与安全性、疗效无关」的否定句，优先判定
    (r"non-safety|other than safety|not as a result of|(not|unrelated|no)\W+(\w+\W+){0,4}(safety|efficacy)|business|strateg|portfolio|"
     r"commercial|corporate|priorit|pipeline|development (program|plan|policy)|stop the development|redirect|focus (its )?resources|"
     r"wind down|acquisition|acquired|merger|licens", "申办方决定 / 战略"),
    (r"safety|adverse|toxicit|tolerab|death", "安全性"),
    (r"futil|efficacy|lack of (\w+ )?(benefit|effect|response)|limited ([\w-]+ )?activity|lack of (\w+ )?activity|did not meet|not met|interim|"
     r"unlikely to|not demonstrat|benefit.risk|clinical benefit|DSMB|DMC|data monitoring", "疗效 / 无效性"),
    (r"enrol|recruit|accru|feasib|eligible|event rate|operational", "入组 / 运营"),
    (r"fund|resources|financ", "资金"),
    (r"regulat|FDA|EMA|health authority|clinical hold", "监管"),
    # 只说「申办方决定」而没有具体原因的，最后兜底
    (r"sponsor('s)? (decision|request)|sponsor decided|request of the sponsor|by (the )?sponsor|sponsor cancel|company decision|"
     r"decided not to|not to (proceed|continue|initiate)|administrative", "申办方决定 / 战略"),
]


def why_cat(why, status):
    if not why:
        return "未填写"
    for pat, label in WHY_RULES:
        if re.search(pat, why, re.I):
            return label
    return "其他"


PLACEBO = re.compile(r"^(placebo|vehicle|saline|sham|standard of care|best supportive care|matching placebo)", re.I)


def classify(text, rules, default):
    for pat, label in rules:
        if re.search(pat, text, re.I):
            return label
    return default


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
        "mod": classify(" ".join(interventions), MOD_RULES, "其他"),
        "ta": classify(" ".join(conditions) + " " + ident.get("briefTitle", ""), TA_RULES, "其他"),
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
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    counts = ", ".join(f"{k} {len(v)}" for k, v in out["sets"].items())
    print(f"完成：{counts} → {a.out}", file=sys.stderr)


def reclassify(path):
    """不重新联网，只按最新规则重算已有 trials.json 的领域和药物形式。"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    for v in d["sets"].values():
        for t in v:
            t["interventions"] = [x for x in t["interventions"] if not PLACEBO.match(x.strip())]
            t["mod"] = classify(" ".join(t["interventions"]), MOD_RULES, "其他")
            t["ta"] = classify(" ".join(t["conditions"]) + " " + t["title"], TA_RULES, "其他")
            t["group"] = sponsor_group(t["sponsor"])
            t["why_cat"] = why_cat(t.get("why", ""), t["status"]) if t["status"] in ("TERMINATED", "SUSPENDED", "WITHDRAWN") else ""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--reclassify":
        reclassify(sys.argv[2])
    else:
        main()
