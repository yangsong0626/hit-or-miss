"""药物形式（modality）分类。

只给受试药分类，不算对照药和背景用药。判断依据按可靠程度依次是：
人工对照表（data/modality_map.json）、注册库的干预类型、药名和别名（INN 词干）、干预描述里的关键词。
"""
import json
import os
import re

# 细类 → 大类。顺序也是网站上的展示顺序。
GROUPS = {
    "小分子": "小分子",
    "降解剂（PROTAC / 分子胶）": "小分子",
    "多肽 / 蛋白激素": "多肽",
    "单抗": "蛋白 / 抗体",
    "双抗 / 多抗": "蛋白 / 抗体",
    "ADC / 偶联药物": "蛋白 / 抗体",
    "融合蛋白": "蛋白 / 抗体",
    "酶 / 重组蛋白": "蛋白 / 抗体",
    "血浆制品 / 免疫球蛋白": "蛋白 / 抗体",
    "siRNA": "核酸",
    "反义寡核苷酸": "核酸",
    "mRNA 疗法": "核酸",
    "细胞治疗": "细胞 / 基因",
    "基因治疗 / 基因编辑": "细胞 / 基因",
    "溶瘤病毒": "细胞 / 基因",
    "疫苗": "疫苗",
    "放射性药物": "放射性药物",
    "过敏原免疫治疗": "其他",
    "活菌 / 微生物组": "其他",
    "中药 / 植物药": "其他",
    "器械 / 非药物": "其他",
    "生物制品（未细分）": "未识别",
    "未识别": "未识别",
}
ORDER = list(GROUPS)

# (正则, 细类)；按特异性从高到低排列，先命中先返回
RULES = [
    (r"vedotin|deruxtecan|govitecan|rezetecan|exatecan|\w+mab\s+\w+tecan\b|ozogamicin|mafodotin|emtansine|tesirine|soravtansine|duocarmazine|"
     r"antibody[- ]drug conjugate|\bADC\b|drug conjugate|bicycle toxin", "ADC / 偶联药物"),
    (r"radioligand|radiopharm|radiolabel|\b(177)?Lu[- ]?(177|PSMA|DOTA)|lutetium|actinium|\b225Ac|\bAc[- ]225|radium[- ]223|"
     r"iodine[- ]131|\b131I\b|yttrium[- ]90|\bpentixather|\bvipivotide|\[\s?(18F|68Ga|64Cu|89Zr|99mTc|11C|O-15|15O)\s?\]|"
     r"\b(18F|68Ga|64Cu|89Zr|99mTc|177Lu|225Ac)[- ]|\bPSMA[- ]?\d|radioactive", "放射性药物"),
    (r"\w+leucel\b|\w+cel\b|\bCAR[- ]?T\b|chimeric antigen|\bTCR[- ]?T\b|tumou?r[- ]infiltrating lymph|\bTIL\b|"
     r"\bNK cells?\b|natural killer cells|stem cells?|stromal cells|MSCs?\b|T lymphocytes?|cells/kg|cells per kg|\bCAR\d|autologous .*cells|allogeneic .*cells|"
     r"cell therapy|T[- ]cell therapy|dendritic cell|[- ]derived cells|\bMultiStem\b|progenitor cells|\bexosomes?\b", "细胞治疗"),
    (r"oncolytic|vaccinia|JX-594|pexa-?vec|\w+repvec\b|\w+vec\b.*(herpes|HSV)|talimogene", "溶瘤病毒"),
    (r"gene therapy|gene transfer|\bAAV\d*\b|adeno[- ]associated|lentivir|\w+parvovec\b|\w+vec\b|gene editing|CRISPR|"
     r"base edit|prime edit|\bzinc finger nuclease|\bplasmid\b", "基因治疗 / 基因编辑"),
    (r"\w+siran\b|\bARO-[A-Z]|\bsiRNA\b|small interfering RNA|RNA interference|\bRNAi\b", "siRNA"),
    (r"\w+rsen\b|\w+ersen\b|antisense|oligonucleotide|\bASO\b|\bION[- ]?\d{3}\b", "反义寡核苷酸"),
    (r"vaccin(?!ia)|\bTdap\b|\bDTaP\b|Adacel|Pentacel|Quadracel|Boostrix|\b(flu|influenza|RSV|COVID|CMV|hMPV)[- ]?mRNA|\bmRNA-1\d{3}\b|\w+vac\b|\w+vax\b|vacgen|\bPCV\d+|\bV\d{3}[A-Z]?\b|toxoid|immuni[sz]ation|\bVLP\b|virus[- ]like particle|conjugate vaccine", "疫苗"),
    (r"\bmRNA\b|messenger RNA", "mRNA 疗法"),
    (r"\w+mig\b|amivantamab|teclistamab|talquetamab|elranatamab|linvoseltamab|glofitamab|epcoritamab|mosunetuzumab|"
     r"odronextamab|blinatumomab|tarlatamab|zanidatamab|ivonescimab|cadonilimab|zenocutuzumab|faricimab|emicizumab|"
     r"catumaxomab|erfonrilimab|acasunlimab|navicixizumab|tebotelimab|vudalimab|lorigerlimab|izalontamab|xaluritamig|"
     r"pasritamig|cevostamab|etentamig|alnuctamab|bispecific|bi-specific|trispecific|tri-specific|\bBiTE\b|T[- ]cell engager|"
     r"dual[- ]targeting antibody", "双抗 / 多抗"),
    (r"PROTAC|degrader|molecular glue|iberdomide|mezigdomide|golcadomide|cemsidomide|luxdegalutamide|\bARV-\d{3}\b|"
     r"\bNX-[25]\d{3}\b|\bBGB-16673\b|\bCC-94676\b|\bBMS-986365\b|\bDT2216\b|\w+degrant\b|vepdegestrant|\w+degestrant\b", "降解剂（PROTAC / 分子胶）"),
    (r"\w+cept\b|\w+fusp\b|fusion protein|Fc[- ]fusion|-Fc\b|\bFc\b.*fusion", "融合蛋白"),
    (r"\w+mab\b|\w+tug\b|\w+bart\b|HexaBody|monoclonal antibod|\bmAb\b|humani[sz]ed antibod|fully human antibod|\bantibody\b|nanobod|\bIgG\d?\b|anti-PD-?L?1|PD-L?1 inhibitor|checkpoint inhibitor|\bFab\b",
     "单抗"),
    (r"immune globulin|immunoglobulin|\bIVIG\b|\bSCIG\b|albumin|plasma[- ]derived|plasma protein|antithrombin|"
     r"C1[- ]?(esterase )?inhibitor|fibrinogen|prothrombin complex|\(human\)|alpha[- ]?1[- ]?(proteinase|antitrypsin)|C1-?INH|\bPCC\b|fibrin sealant", "血浆制品 / 免疫球蛋白"),
    (r"\w+ase alfa\b|\w+ase beta\b|\w+ase\b alfa|enzyme replacement|recombinant (human )?\w*(ase|factor|protein)|"
     r"factor (VIII|IX|VIIa?|X)\b|\w+(nonacog|octocog|turoctocog|eftrenonacog|efmoroctocog|damoctocog)\b|"
     r"botulinum|toxin type|interferon|interleukin|\w+leukin\b|\w+kinra\b|erythropoietin|epoetin|filgrastim|\w+grastim\b|"
     r"collagenase|hyaluronidase|asparaginase|\w+plase\b|\w+ermin\b|peg\w+ase\b|\w+ase alfa|\w+ \balfa\b|\w+ \bbeta\b(?! ?-)|"
     r"recombinant human|\brh[A-Z]|\brecombinant\b|G-CSF|\benzymes?\b", "酶 / 重组蛋白"),
    (r"insulin|\w+glutide\b|\w+tide\b|\w+pressin\b|\w+relin\b|\w+relix\b|\w+tocin\b|tirzepatide|retatrutide|"
     r"\bpeptide\b|parathyroid|teriparatide|abaloparatide|somatropin|somapacitan|\w+trop(in)?\b|glucagon|amylin|"
     r"calcitonin|\w+lutide\b|\w+natide\b|\w+paratide\b|\bGLP-1\b.*(analog|agonist)", "多肽 / 蛋白激素"),
    (r"allergen|allergoid|\bViaskin\b|immunotherapy tablet|pollen extract|\bgrass\b.*(extract|immunotherapy|SLIT|SCIT)|\bPQ Grass\b", "过敏原免疫治疗"),
    (r"probiotic|microbiome|microbiota|fecal|faecal|bacterial strain|live biotherapeutic|\bspores?\b|bacteriophage|"
     r"\bphage\b|lactobacillus|bifidobacter", "活菌 / 微生物组"),
    (r"traditional chinese|chinese medicine|chinese herbal|\bherbal\b|botanical|decoction|granules?\b.*(TCM|herb)|"
     r"\w+ (wan|tang|san|pian|keli|jiaonang|koufuye)\b|extract\b|\bTCM\b", "中药 / 植物药"),
    (r"small[- ]molecule|\w+tinib\b|\w+ciclib\b|\w+rafenib\b|\w+parib\b|\w+lisib\b|\w+degib\b|\w+tegrast\b|\w+lukast\b|"
     r"\w+conazole\b|\w+azole\b|\w+sartan\b|\w+statin\b|\w+pril\b|\w+olol\b|\w+gliflozin\b|\w+gliptin\b|\w+dipine\b|"
     r"\w+prazole\b|\w+vir\b|\w+buvir\b|\w+previr\b|\w+mycin\b|\w+cillin\b|\w+floxacin\b|\w+cycline\b|\w+platin\b|"
     r"\w+taxel\b|\w+tidine\b|\w+setron\b|\w+triptan\b|\w+gepant\b|\w+xaban\b|\w+gatran\b|\w+pam\b|\w+lam\b|"
     r"\w+zolam\b|\w+done\b|\w+pine\b|\w+sone\b|\w+lone\b|\w+nide\b|\w+mide\b|\w+stat\b|\w+zomib\b|"
     r"\w+rubicin\b|\w+citabine\b|irinotecan|topotecan|belotecan|\w+fenib\b|\w+lutamide\b|\w+terone\b|\w+estrant\b|\w+fiban\b|\w+grel\b|"
     r"\w+oxacin\b|\w+azepam\b|\w+oxetine\b|\w+aline\b|\w+tadine\b|\w+profen\b|\w+coxib\b|\w+dronate\b|"
     r"\w+imod\b|\w+citinib\b|"
     r"\bcream\b|ointment|\bgel\b|\btablets?\b|capsules?\b|\boral\b|ophthalmic solution|eye drops|inhal\w+ powder|"
     r"\bpatch\b|transdermal|nasal spray|\bprodrug\b|\blotion\b|\bfilm\b|eye drops?|ophthalmic suspension|ophthalmic emulsion|"
     r"\bHFA\b|inhalation aerosol|metered[- ]dose|\borally\b|by mouth|\bper os\b|gado\w+|\bGBCA\b|contrast agent|"
     r"aminolevulinic|\bALA\b|\bALA[- ]PDT\b|toothpaste|dentifrice|\bSnF\b|fluoride|\bINCB\d|\b(BTK|JAK|TKI|CDK4/6|EGFR-TKI) inhibitor|"
     r"hydrochloride|\bHCl\b|mesylate|maleate|tartrate|succinate|citrate|"
     r"sodium\b|potassium\b|besylate|fumarate|tosylate|acetate|phosphate|sulfate|bromide", "小分子"),
]

NONDRUG_TYPES = {"DEVICE", "PROCEDURE", "BEHAVIORAL", "DIAGNOSTIC_TEST", "RADIATION"}
PLACEBO = re.compile(r"placebo|^sham\b|^vehicle\b|^saline\b|^normal saline\b|^dummy\b", re.I)
COMPARATOR_ARMS = {"ACTIVE_COMPARATOR", "PLACEBO_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION"}

# 常见的背景 / 联用标准治疗：有其他受试药时不拿它们来决定药物形式
BACKBONE = re.compile(
    r"^(pembrolizumab|nivolumab|atezolizumab|durvalumab|cemiplimab|tislelizumab|toripalimab|sintilimab|camrelizumab|"
    r"serplulimab|ipilimumab|bevacizumab|trastuzumab|pertuzumab|rituximab|cetuximab|panitumumab|daratumumab|"
    r"carboplatin|cisplatin|oxaliplatin|paclitaxel|nab-paclitaxel|docetaxel|pemetrexed|gemcitabine|capecitabine|"
    r"fluorouracil|5-fu|5-fluorouracil|leucovorin|folinic acid|irinotecan|etoposide|cyclophosphamide|doxorubicin|"
    r"dexamethasone|prednisone|prednisolone|methylprednisolone|lenalidomide|pomalidomide|bortezomib|carfilzomib|"
    r"metformin|methotrexate|letrozole|anastrozole|exemestane|fulvestrant|tamoxifen|enzalutamide|abiraterone|"
    r"azacitidine|cytarabine|temozolomide|insulin glargine|aspirin|standard of care|best supportive care|"
    r"fludarabine|bendamustine|vincristine|mesna|lymphodeplet\w*|conditioning|tocilizumab|rosuvastatin|atorvastatin|"
    r"chemotherapy|physician'?s choice|investigator'?s choice|background therapy|androgen deprivation therapy|"
    r"\badt\b|leuprolide|goserelin)\b", re.I)

_MAP = None


def _norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def load_map(path=None):
    """data/modality_map.json：{"codes": {代号或药名: 细类}, "nct": {NCT号: 细类}}"""
    global _MAP
    if _MAP is not None and path is None:
        return _MAP
    path = path or os.path.join(os.path.dirname(__file__), "..", "data", "modality_map.json")
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    _MAP = {"codes": {_norm(k): v for k, v in m.get("codes", {}).items() if not k.startswith("_")},
            "nct": m.get("nct", {})}
    return _MAP


def lookup(name):
    """在对照表里找：完全相同；名字以表中词开头（"Riociguat (Adempas)"）；或名字里含表中的代号（"Dose A KER-012"）。"""
    mp = load_map()["codes"]
    k = _norm(name)
    if not k:
        return None
    if k in mp:
        return mp[k]
    for key, lab in mp.items():
        if len(key) >= 4 and k.startswith(key):
            return lab
        if len(key) >= 4 and re.search(r"\d", key) and re.search(r"[A-Z]", key) and key in k:
            return lab
    return None


# INN 风格的单词药名（没有生物药词干）大多是小分子；排除常见的非药名词
_NOT_INN = re.compile(r"^(standard|control|placebo|vehicle|observation|usual|best|routine|treatment|therapy|"
                      r"chemotherapy|surgery|dose|part|arm|group|cohort|experimental|investigational|open|blinded|"
                      r"low|high|medium|active|study|drug|injection|infusion|tablet|capsule|solution|regimen|"
                      r"combination|monotherapy|adjuvant|biosimilar|reference|comparator|matching|new|fixed)$", re.I)


def inn_like(name):
    w = re.split(r"[\s(,/+]", (name or "").strip())[0]
    return bool(re.fullmatch(r"[A-Za-z][a-z]{5,}", w)) and not _NOT_INN.match(w)


def classify_one(iv):
    """单个干预 → 细类。iv: {n 名称, ty 类型, on 别名, ds 描述}"""
    mp = load_map()["codes"]
    names = [iv.get("n", "")] + list(iv.get("on") or [])
    for nm in names:
        hit = lookup(nm)
        if hit:
            return hit
    ty = (iv.get("ty") or "").upper()
    name_txt = " ".join(names)
    full = name_txt + " " + (iv.get("ds") or "")
    if ty == "GENETIC":
        return "细胞治疗" if re.search(RULES[2][0], full, re.I) else (
            "溶瘤病毒" if re.search(RULES[3][0], full, re.I) else "基因治疗 / 基因编辑")
    if ty in NONDRUG_TYPES:
        if ty == "RADIATION" and re.search(RULES[1][0], full, re.I):
            return "放射性药物"
        return "器械 / 非药物"
    # 先只看名字和别名（INN 词干最可靠），按规则顺序
    for txt in names:
        for pat, lab in RULES:
            if re.search(pat, txt, re.I):
                return lab
    # 再看描述：描述里常提到联用药，所以取最先出现的关键词（"X is a small-molecule ..."）
    ds = iv.get("ds") or ""
    best = None
    for i, (pat, lab) in enumerate(RULES):
        m = re.search(pat, ds, re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), lab)
    if best:
        return best[1]
    if ty in ("DRUG", "") and any(inn_like(nm) for nm in names):
        return "小分子"
    if ty == "GENETIC":
        return "基因治疗 / 基因编辑"
    if ty == "BIOLOGICAL":
        return "生物制品（未细分）"
    if ty == "DIETARY_SUPPLEMENT":
        return "器械 / 非药物"
    return "未识别"


def candidates(t):
    """挑出受试药：只在试验组出现的优先，其次试验组与对照组都有的，去掉安慰剂和背景治疗。"""
    ivs = [iv for iv in (t.get("iv") or []) if not PLACEBO.search((iv.get("n") or "").strip())]
    if not ivs:
        return [{"n": n, "ty": "", "on": [], "ds": "", "r": "x"} for n in t.get("interventions", [])
                if not PLACEBO.search(n.strip())]
    pool = [iv for iv in ivs if iv.get("r") == "x"] or [iv for iv in ivs if iv.get("r") != "c"] or ivs
    novel = [iv for iv in pool if not BACKBONE.match((iv.get("n") or "").strip())]
    return novel or pool


def _from_text(t, cands):
    """干预本身认不出时，用标题和简介里提到受试药的句子再判断一次（取最先出现的关键词）。"""
    toks = {w.lower() for iv in cands for w in re.findall(r"[A-Za-z][\w-]{2,}", iv.get("n") or "")
            if not re.fullmatch(r"(?i)injection|tablets?|capsules?|dose|low|high|placebo|infusion|for|and|the|oral|cohort|part|arm", w)}
    sents = [x for x in re.split(r"(?<=[.;])\s+", t.get("sum") or "") if any(k in x.lower() for k in toks)]
    txt = (t.get("title") or "") + " . " + " ".join(sents)
    best = None
    for pat, lab in RULES:
        if lab in _TEXT_SKIP:
            continue
        if lab == "小分子":   # 文本里的药名词干多半是联用药，小分子只认剂型和给药途径
            pat = _SM_TEXT
        for m in re.finditer(pat, txt, re.I):
            # 标题里常写联用药（"… combined with carboplatin"），跳过背景治疗
            if BACKBONE.match(m.group(0)) or re.search(r"(?:with|plus|and|\+)\s*$", txt[max(0, m.start() - 12):m.start()], re.I):
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), lab)
            break
    return best[1] if best else None


_SM_TEXT = (r"\b(?:oral(?:ly)?|tablets?|capsules?|cream|ointment|gel|lotion|topical|eye drops?|ophthalmic|inhal\w*|"
            r"nebuli[sz]\w*|nasal spray|small[- ]molecule|transdermal|patch)\b")
_TEXT_SKIP = {"血浆制品 / 免疫球蛋白", "酶 / 重组蛋白", "过敏原免疫治疗", "活菌 / 微生物组", "中药 / 植物药", "mRNA 疗法"}


def classify_trial(t):
    """返回 (主要细类, 全部细类列表)。"""
    over = load_map()["nct"].get(t.get("nct"))
    cands = candidates(t)
    labs = [classify_one(iv) for iv in cands]
    if labs and all(GROUPS.get(x) == "未识别" for x in labs):
        alt = _from_text(t, cands)
        if alt and alt != "器械 / 非药物":
            labs = [alt] + labs
    if over:
        return over, list(dict.fromkeys([over] + [x for x in labs if x != "器械 / 非药物"]))
    drug = [x for x in labs if x != "器械 / 非药物"]
    known = [x for x in drug if GROUPS.get(x) != "未识别"]
    if known:
        primary = known[0]
    elif drug:
        primary = drug[0]
    elif labs:
        primary = labs[0]
    else:
        primary = "未识别"
    return primary, list(dict.fromkeys(known or drug or labs or [primary]))


def iv_records(arms_module):
    """从 armsInterventionsModule 提取干预明细和角色：x 只在试验组，c 只在对照组，b 两边都有。"""
    arm_type = {a.get("label", ""): a.get("type", "") for a in arms_module.get("armGroups", [])}
    out = []
    for i in arms_module.get("interventions", [])[:8]:
        labels = i.get("armGroupLabels") or []
        types = {arm_type.get(l, "") for l in labels}
        comp = bool(types & COMPARATOR_ARMS)
        exp = bool(types - COMPARATOR_ARMS) or not labels
        role = "b" if comp and exp else ("c" if comp else "x")
        out.append({"n": (i.get("name") or "")[:80], "ty": i.get("type", ""),
                    "on": [x[:60] for x in (i.get("otherNames") or [])[:5]],
                    "ds": re.sub(r"\s+", " ", i.get("description") or "")[:220], "r": role})
    return out
