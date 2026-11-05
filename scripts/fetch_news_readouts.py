#!/usr/bin/env python3
"""每周抓取「新闻稿读出」：公司新闻稿和行业媒体里的 topline / 主要终点结果，中英文都抓。

注册库结果通常比新闻稿晚半年到一年，这一层补上最快的信号。来源是 Google News RSS（和 fetch_feeds.py 同一个
入口），按一组读出关键词检索最近 N 天。每条标题按规则判定（达到 / 未达到 / 混合 / 终止 / 待判定），抽出分期、
药名、公司，再用本站已有的试验数据（trials.json、docs/active.json、docs/early.json）对上 NCT 号、治疗领域、
靶点和药物形式。同一个药同一个结论在 14 天内的多篇报道合并成一条。

文件：
  data/news_readouts.json   累积库（保留 365 天，每周合并新条目，不覆盖旧条目的首次出现日期）
  data/news_overrides.json  人工修正，按条目 id：{"v": 判定, "hide": true, "note": 点评, "nct": ..., "drug": ..., "tg": [...]}
                            重新抓取不会覆盖这个文件；build_site.py 构建时套用
  docs/news.json            页面用（构建时由 export() 生成）
  weekly_news.md            本周新增条目清单（工作流用它开 GitHub issue，方便逐条核对）

只用 Python 标准库。整体失败时保留旧文件，退出码 0，不影响后面的构建。

用法：
  python scripts/fetch_news_readouts.py --days 8                 # 每周更新
  python scripts/fetch_news_readouts.py --from-xml a.xml b.xml   # 离线测试：读本地 RSS 文件
  python scripts/fetch_news_readouts.py --export-only            # 只按 overrides 重新生成 docs/news.json
"""
import argparse, datetime as dt, hashlib, json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import modality  # noqa: E402
import targets as tgmod  # noqa: E402
from fetch_trials import TA_RULES, SPONSOR_GROUPS, sponsor_group  # noqa: E402

UA = {"User-Agent": "hit-or-miss/1.0 (https://github.com/yangsong0626/hit-or-miss)"}
KEEP_DAYS = 365
MERGE_DAYS = 14

# ---------- 检索词 ----------
EN_Q = [
    '"topline" ("phase 3" OR "phase III" OR "phase 2" OR "phase II" OR pivotal)',
    '"primary endpoint" (met OR meets OR achieved OR achieves)',
    '"primary endpoint" ("did not meet" OR "failed to meet" OR missed OR "not met")',
    '("phase 3" OR "phase III") ("positive results" OR "statistically significant")',
    '("phase 2" OR "phase II") ("positive results" OR "positive data" OR "proof of concept")',
    '("phase 3" OR "phase 2" OR pivotal) trial (fails OR failed OR flop OR "falls short")',
    '("phase 3" OR "phase 2") (discontinue OR discontinues OR halts OR terminates OR scraps) trial',
    '("overall survival" OR "progression-free survival") ("phase 3" OR "phase III") results',
    '("late-breaking" OR "data presented" OR "presents data") ("phase 3" OR "phase 2") trial',
]
ZH_Q = [
    '"达到主要终点"',
    '"未达到主要终点" OR "未达主要终点"',
    '"III期" ("积极结果" OR "顶线结果" OR "主要终点")',
    '"II期" ("积极结果" OR "顶线结果" OR "主要终点")',
    '"临床试验" ("失败" OR "终止") ("III期" OR "II期")',
    '"读出" ("III期" OR "II期" OR "关键")',
]

# ---------- 过滤 ----------
SIGNAL = re.compile(r"endpoint|topline|top-line|results?\b|data\b|\bmet\b|\bmeets?\b|miss|fail|positive|negative|discontinu|halt|"
                    r"terminat|surviv|response|efficacy|significan|superior|non-?inferior|improv|reduc|flop|falls? short|beat|"
                    r"终点|结果|数据|达到|未达|终止|积极|阳性|失败|成功|显著|优效|读出|缓解|生存", re.I)
TRIAL = re.compile(r"phase|\bph\.?\s*[1-3]|trial|study|pivotal|registrational|cohort|[I1-3Ⅰ-Ⅲ一二三]+[ab]?期|临床|研究|试验", re.I)
JUNK = re.compile(r"market (size|report|research|analysis|insight|outlook|forecast|share|trends?)|\bCAGR\b|pipeline (report|insight|analysis)|"
                  r"pipeline:? emerging|competitive landscape|DelveInsight|shareholder|class action|investors? (alert|who)|lawsuit|"
                  r"securities fraud|law firm|\bINVESTOR ALERT\b|deadline reminder|stock (is|was) (up|down)|shares? (jump|soar|plunge|tumble|sink|rise|fall|surge|slide)|"
                  r"price target|analyst|\bETF\b|how to buy|vs\.? .* stock|top \d+ (stocks|biotech)|webinar|to (host|present) .* (call|webcast|conference)|"
                  r"to present (at|new)|will present|to report|announces? (date|timing)|conference call|earnings|quarter(ly)? (results|financial)|"
                  r"\bQ[1-4]\b .*(results|financial)|financial results|business update|"
                  r"retrospective|real-world|real world|meta-analysis|systematic review|review finds|cohort study|case report|"
                  r"registry|survey|first patient|initiat(es|ed) (a |the )?(phase|trial|study|dosing)|enrol(l)?s first|doses first|"
                  r"市场规模|行业报告|研究报告|股价|涨停|跌停|港股|A股|美股|财报|季度|业绩|回顾性|真实世界|荟萃|系统综述|病例报告|首例(患者)?给药|启动", re.I)
# 监管、预告类：标题里同时有明确的达到 / 未达到字眼才保留
SOFT_JUNK = re.compile(r"\bFDA\b.*(clears?|approv\w*|accepts?|grants?)|approval|\bIND\b|fast track|breakthrough therapy|orphan drug|"
                       r"\bto present\b|will present|to be presented|to share|to unveil|获批|批准|受理|突破性疗法|将公布|将在.*(公布|展示|发布|报告)|亮相|将携|入选.*(口头报告|LBA)", re.I)
JUNK_SRC = re.compile(r"openPR|Bioengineer|生物通|EIN Presswire|MarketBeat|Zacks|Benzinga Ratings|Simply Wall|Insider Monkey|TipRanks|Seeking Alpha|"
                      r"Motley Fool|Nasdaq\.com|Yahoo Finance Video|AInvest|Stock Titan", re.I)

# ---------- 判定 ----------
MISS = re.compile(r"did ?n[o']t (meet|achieve|reach|hit|show|demonstrate)|didn't (meet|achieve|reach|hit)|not (meet|met|achieve)|"
                  r"failed? to (meet|achieve|reach|show|demonstrate|beat|improve|hit)|\bfails?\b|\bfailed\b|failure|\bmiss(es|ed)?\b|"
                  r"falls? short|fell short|not statistically significant|no (statistically )?significant|non-?significant|"
                  r"negative (results?|data|trial|outcome|readout)|\bflops?\b|disappoint\w*|underwhelm\w*|setback|"
                  r"未达到|未达|未能达到|失败|折戟|不及预期|未显示|无显著", re.I)
STOP = re.compile(r"discontinu\w*|\bhalt(s|ed|ing)?\b|terminat\w*|\bstops?\b|\bstopped\b|\bscraps?\b|\bscrapped\b|shelv\w*|"
                  r"pull(s|ed)? the plug|ends? (development|program|trial)|drops? (program|drug|candidate)|futility|"
                  r"终止|暂停|放弃|砍掉|叫停|停止开发", re.I)
HIT = re.compile(r"\bmet\b|\bmeets?\b|achiev(ed|es|ing)|\bpositive\b|statistically significant|significant(ly)? (improv|reduc|extend|lower|prolong|increas)|"
                 r"succe(ss|ed|eds|eded)|\bbeats?\b|superior\w*|non-?inferior\w*|outperform\w*|improv(es|ed) (overall |progression-free )?survival|"
                 r"extends? survival|survival benefit|strong (phase|data|results?)|delivers? (strong|positive)|reduc(es|ed) (the )?risk|胜出|\bwins?\b|\bhits?\b(?! with)|clinically meaningful|"
                 r"达到主要终点|达到|积极|成功|显著改善|显著延长|显著降低|优效|阳性结果|非劣效", re.I)
MIXED = re.compile(r"\bmixed\b|\bbut\b|however|\bdespite\b|one of (two|the two)|partial(ly)?|only (one|in)|secondary endpoints? only|"
                   r"喜忧参半|但|部分达到", re.I)
PROMISING = re.compile(r"promising|encouraging|durable|deep (and durable )?|\b\d{2,3}(\.\d)?% (objective |overall |complete )?(response|ORR|CR|reduction|remission)|"
                       r"(response|remission) rate|responses?\b.*\b(all|every)|reduc(es|ed|tion) .{0,40}\bby \d|鼓舞|缓解率|全部应答|完全缓解|显著减轻|初步疗效", re.I)
NEUTRAL_DATA = re.compile(r"results?|data|readout|presents?|reported|unveil|读出|数据|结果", re.I)


def verdict(title):
    """返回（判定，是否同时有终止信号）。先把否定短语拿掉再找阳性词，避免 not statistically significant 判成达到。"""
    miss = MISS.search(title)
    rest = MISS.sub(" ", title)
    hit = HIT.search(rest)
    stop = bool(STOP.search(title))
    if miss and hit:
        return "混合", stop
    if miss:
        return "未达到", stop
    if hit:
        return ("混合" if MIXED.search(rest) and re.search(r"\b(but|however|despite)\b|但", rest, re.I) else "达到"), stop
    if stop:
        return "终止", True
    if PROMISING.search(title):
        return "积极信号", False
    return "待判定", False


PHASE = [
    (re.compile(r"phase\s*(3|III)\b|ph\.?\s*3\b|pivotal|registrational|III期|Ⅲ期|3期|三期|关键(性)?(临床|研究|试验)", re.I), "3"),
    (re.compile(r"phase\s*(2|II)\s*/\s*(3|III)|II/III期|2/3期", re.I), "2/3"),
    (re.compile(r"phase\s*(2|II)[ab]?\b|ph\.?\s*2\b|II期|Ⅱ期|2期|二期", re.I), "2"),
    (re.compile(r"phase\s*(1|I)[ab]?(/2|/II)?\b|first-in-human|I期|Ⅰ期|1期|一期", re.I), "1"),
]


def phase_of(title):
    m = PHASE[1][0].search(title)
    if m:
        return "2/3"
    for i in (0, 2, 3):
        if PHASE[i][0].search(title):
            return PHASE[i][1]
    return ""


# ---------- 药名词典（来自本站已有的试验数据） ----------
GENERIC = re.compile(r"^(standard|control|placebo|vehicle|tablets?|capsules?|injection|infusion|solution|therapy|treatment|"
                     r"chemotherapy|surgery|regimen|combination|monotherapy|adjuvant|neoadjuvant|cohort|dose|study|trial|phase|"
                     r"results|positive|negative|patients|cancer|disease|primary|endpoint|biosimilar|vaccine|insulin|"
                     r"pembrolizumab\+|nivolumab\+|carboplatin|cisplatin|paclitaxel|docetaxel|gemcitabine|metformin|"
                     r"prednisone|dexamethasone|methotrexate|oxaliplatin|capecitabine|fluorouracil|leucovorin|"
                     r"semaglutide\s*\+|covid19|sarscov2|influenza|announces|company|pharmaceuticals?|therapeutics)$", re.I)
SET_RANK = {"results": 0, "completed": 1, "stopped": 2, "upcoming": 3, "active": 4, "early": 5}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _tokens_of_iv(name, other):
    out = []
    main = re.split(r"[(\[]", name)[0].strip()
    out.append(main)
    for inner in re.findall(r"[(\[]([^)\]]+)[)\]]", name):
        out += re.split(r"[,;/]|\bor\b|\balso known as\b|\baka\b", inner)
    out += list(other or [])
    keep = []
    for tok in out:
        tok = tok.strip()
        k = _norm(tok)
        if not k or GENERIC.match(tok) or GENERIC.match(k):
            continue
        has_d, has_a = bool(re.search(r"\d", k)), bool(re.search(r"[a-z]", k))
        if has_d and has_a and 4 <= len(k) <= 14:
            keep.append((k, tok))
        elif not has_d and len(k) >= 6 and " " not in tok.strip() and modality.inn_like(tok):
            keep.append((k, tok))
    return keep


def build_lexicon(trials_path, docs_dir):
    lex = {}

    def add(t, set_name):
        cands = modality.candidates(t) if t.get("iv") and isinstance(t["iv"][0], dict) and "ty" in t["iv"][0] else [
            {"n": iv.get("n", ""), "on": iv.get("on") or []} for iv in (t.get("iv") or [])]
        inn = ""
        toks = []
        for iv in cands:
            nm = iv.get("n") or ""
            if modality.PLACEBO.search(nm) or modality.BACKBONE.match(nm.strip()):
                continue
            tk = _tokens_of_iv(nm, iv.get("on"))
            toks += tk
            for k, tok in tk:
                if not inn and not re.search(r"\d", k):
                    inn = tok
        if not toks:
            return
        rec = {"nct": t.get("nct"), "ph": t.get("phase", ""), "set": set_name, "co": t.get("group") or t.get("sponsor") or "",
               "ta": t.get("ta", ""), "tg": t.get("tg") or [], "mod": t.get("mod", ""), "inn": inn,
               "d": t.get("results") or t.get("pcd") or t.get("fp") or ""}
        for k, tok in toks:
            lex.setdefault(k, []).append(dict(rec, name=inn or tok))

    if os.path.exists(trials_path):
        d = json.load(open(trials_path, encoding="utf-8"))
        for s, v in d.get("sets", {}).items():
            for t in v:
                add(t, s)
    for f, s in (("active.json", "active"), ("early.json", "early")):
        p = os.path.join(docs_dir, f)
        if os.path.exists(p):
            for t in json.load(open(p, encoding="utf-8")).get("trials", []):
                add(t, s)
    # 靶点名本身（DLL3、TROP2…）不是药名
    tdict = json.load(open(os.path.join(ROOT, "data", "target_dict.json"), encoding="utf-8"))["targets"]
    tnames = {_norm(n) for n in tdict if not n.startswith("_")}
    tnames |= {_norm(a) for v in tdict.values() if isinstance(v, list) for a in v if not a.startswith(("re:", "cs:"))}
    tnames |= {_norm(a[3:]) for v in tdict.values() if isinstance(v, list) for a in v if a.startswith("cs:")}
    for k in list(lex):
        if k in tnames:
            del lex[k]
    # 靶点词典里的常见药名也收进来（没有试验记录，只给靶点）
    for k, tg in tgmod.load()["drugs"].items():
        if len(k) >= 5:
            lex.setdefault(k, []).append({"nct": None, "ph": "", "set": "dict", "co": "", "ta": "", "tg": [tg] if isinstance(tg, str) else list(tg),
                                          "mod": "", "inn": k, "name": k.capitalize(), "d": ""})
    return lex


INN_STEM = re.compile(r"(?<![A-Za-z])[A-Za-z]{3,}(?:mab|tinib|ciclib|parib|rasib|degib|lisib|sertib|rafenib|metinib|zomib|tide|glutide|cept|siran|"
                      r"rsen|tecan|vedotin|leucel|xaban|gliflozin|gliptin|sartan|caftor|tug|kinra|sentan|cel|zumab|ximab)(?![A-Za-z])", re.I)
CODE = re.compile(r"(?<![A-Za-z0-9-])(?!COVID|SARS|ASCO|ESMO|AACR|EASL|AASLD|ASH|ADA|ACC|AHA|ERA|ATS|ENDO|CTAD|EULAR|ISO|ICD)[A-Z]{1,5}-?\d{3,6}[A-Za-z]?(?![A-Za-z0-9])")
COMPARATOR_BEFORE = re.compile(r"(compared (to|with)|versus|\bvs\.?|against|\bover|than|beats?|beat|plus|\+|with|combined with|"
                               r"added to|on top of|after|switch(ing)? from|对比|联合|优于)\W*(\w+\W+){0,2}$", re.I)
STOPWORDS = set("""immunotherapy response responses durable antibody conjugate bispecific inhibitor inhibitors agonist antagonist
therapy therapies patients lymphoma melanoma myeloma leukemia results interim updated analysis primary secondary overall survival
positive negative announces reports presents demonstrates significant clinical trial trials cohort efficacy safety tolerability
treatment treatments combination standard placebo vaccine vaccines biologic biologics infusion injection subcutaneous intravenous
oral tablet capsule chemotherapy radiotherapy surgery induction maintenance consolidation adjuvant neoadjuvant monotherapy
investigational experimental dose doses dosing regimen arms control""".split())


def find_drug(title, lex, ph):
    """返回（试验记录或仅药名，同药其他 NCT）。候选来自药名词典、INN 词干和研发代号；跳过对照药（versus / plus 后面的）。"""
    cands = []  # (位置, 显示名, 词典键或 None)
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9-]{2,}", title):
        w = m.group(0)
        k = _norm(w)
        if k in lex and not GENERIC.match(k) and k not in STOPWORDS and w.lower() not in STOPWORDS:
            cands.append((m.start(), w, k))
    for rx in (CODE, INN_STEM):
        for m in rx.finditer(title):
            if m.group(0).lower() in STOPWORDS:
                continue
            k = _norm(m.group(0))
            if not any(c[0] <= m.start() < c[0] + max(len(c[1]), 1) for c in cands):
                cands.append((m.start(), m.group(0), k if k in lex else None))
    if not cands:
        return None, []
    cands.sort()
    primary = [c for c in cands if not COMPARATOR_BEFORE.search(title[max(0, c[0] - 40):c[0]])] or cands
    pos, shown, k = primary[0]
    # 研发代号保留原写法；通用名首字母大写
    disp = shown if re.search(r"\d", shown) else shown[:1].upper() + shown[1:].lower()
    if not k:
        return {"nct": None, "ph": "", "set": "", "co": "", "ta": "", "tg": [], "mod": "", "inn": "", "name": disp}, []
    recs = sorted(lex[k], key=lambda r: (0 if (ph and ph in (r["ph"] or "")) else 1, SET_RANK.get(r["set"], 9)))
    best = dict(recs[0])
    inn = best.get("inn") or ""
    if re.search(r"\d", shown) and inn and not re.search(r"\d", inn) and _norm(inn) != k:
        disp = f"{inn[:1].upper() + inn[1:].lower()} ({shown})"
    best["name"] = disp
    return best, sorted({r["nct"] for r in recs if r["nct"]})


# ---------- 公司 ----------
ZH_CO = [
    (r"基石", "CStone"), (r"恒瑞", "Hengrui"), (r"百济|百济神州", "BeOne (BeiGene)"), (r"信达", "Innovent"), (r"君实", "Junshi"), (r"和黄|和记黄埔", "HUTCHMED"),
    (r"康方", "Akeso"), (r"科伦", "Kelun-Biotech"), (r"翰森", "Hansoh"), (r"石药", "CSPC"), (r"复星", "Fosun Pharma"),
    (r"正大天晴", "CTTQ"), (r"再鼎", "Zai Lab"), (r"荣昌", "RemeGen"), (r"传奇", "Legend Biotech"), (r"亚盛", "Ascentage"),
    (r"迪哲", "Dizal"), (r"泽璟", "Zelgen"), (r"诺诚健华", "InnoCare"), (r"贝达", "Betta"), (r"齐鲁", "Qilu"),
    (r"豪森", "Hansoh"), (r"先声", "Simcere"), (r"华东医药", "Huadong Medicine"), (r"开拓", "Kintor"), (r"康诺亚", "Keymed"),
    (r"映恩", "Duality Bio"), (r"宜联", "MediLink"), (r"百利天恒", "Biokin"), (r"科济", "CARsgen"), (r"甘李", "Gan & Lee"),
    (r"通化东宝", "Tonghua Dongbao"), (r"歌礼", "Ascletis"), (r"华领", "Hua Medicine"), (r"药明", "WuXi"), (r"海思科", "Haisco"),
    (r"阿斯利康", "AstraZeneca"), (r"辉瑞", "Pfizer"), (r"默沙东", "MSD"), (r"诺华", "Novartis"), (r"罗氏", "Roche"),
    (r"礼来", "Eli Lilly"), (r"诺和诺德", "Novo Nordisk"), (r"赛诺菲", "Sanofi"), (r"强生|杨森", "Johnson & Johnson"),
    (r"百时美施贵宝|百时美", "Bristol Myers Squibb"), (r"葛兰素史克", "GSK"), (r"艾伯维", "AbbVie"), (r"安进", "Amgen"),
    (r"吉利德", "Gilead"), (r"拜耳", "Bayer"), (r"武田", "Takeda"), (r"第一三共", "Daiichi Sankyo"), (r"安斯泰来", "Astellas"),
    (r"勃林格", "Boehringer Ingelheim"), (r"再生元", "Regeneron"), (r"福泰", "Vertex"), (r"渤健", "Biogen"),
]
EN_CO_EXTRA = [(r"\bJ&J\b", "Johnson & Johnson"), (r"\bBMS\b", "Bristol Myers Squibb"), (r"\bMerck\b(?! KGaA)", "MSD"),
               (r"\bLilly\b", "Eli Lilly"), (r"\bNovo\b", "Novo Nordisk"), (r"\bAZ\b", "AstraZeneca")]


GEO_WORD = re.compile(r"^(Beijing|Shanghai|Suzhou|Jiangsu|Zhejiang|Guangzhou|Guangdong|Shenzhen|Hangzhou|Nanjing|Chengdu|Wuhan|Tianjin|"
                      r"Shandong|Sichuan|China|Chinese|Korea|Japan|Taiwan|Hong Kong|Netherlands|Response|Global|International|Medical)$", re.I)


def find_company(title, groups_re):
    for pat, g in SPONSOR_GROUPS + EN_CO_EXTRA + ZH_CO:
        if re.search(pat, title, re.I if not re.search(r"[一-鿿]", pat) else 0):
            return g
    if groups_re:
        m = groups_re.search(title)
        if m:
            return m.group(0)
    return ""


def company_regex(lex):
    names = set()
    for recs in lex.values():
        for r in recs:
            g = (r.get("co") or "").strip()
            if len(g) >= 5 and not GEO_WORD.match(g) and g.lower() not in STOPWORDS and not re.search(r"University|Hospital|Institute|Center|Centre|Group|Cancer|Foundation|National", g, re.I):
                names.add(g)
    if not names:
        return None
    names = sorted(names, key=len, reverse=True)[:4000]
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z])")


ZH_TA = [
    (r"癌|肿瘤|淋巴瘤|白血病|骨髓瘤|黑色素瘤|实体瘤", "肿瘤"),
    (r"糖尿病|肥胖|减重|体重|高血压|心衰|心力衰竭|血脂|胆固醇|肾病|慢性肾", "心血管 / 代谢 / 肾"),
    (r"阿尔茨海默|帕金森|癫痫|抑郁|精神分裂|偏头痛|疼痛|渐冻|肌萎缩", "神经 / 精神 / 疼痛"),
    (r"银屑病|特应性皮炎|湿疹|哮喘|类风湿|红斑狼疮|克罗恩|结肠炎|荨麻疹|慢阻肺", "免疫 / 炎症"),
    (r"乙肝|艾滋|流感|新冠|感染|疫苗|RSV", "感染 / 疫苗"),
    (r"黄斑|视网膜|青光眼|眼", "眼科"),
    (r"肝硬化|脂肪肝|胃|肠", "消化 / 肝"),
    (r"贫血|血友病|血小板", "血液"),
]


def ta_of(title):
    for pat, lab in TA_RULES:
        if re.search(pat, title, re.I):
            return lab
    for pat, lab in ZH_TA:
        if re.search(pat, title):
            return lab
    return ""


# ---------- 抓取 ----------
def get(url, timeout=30, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def parse_rss(raw, lang):
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        pd = it.findtext("pubDate") or ""
        try:
            d = dt.datetime.strptime(pd[:25].strip(), "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
        except ValueError:
            d = ""
        out.append({"t": re.sub(r"\s+", " ", title)[:240], "s": src[:60], "d": d, "u": it.findtext("link") or "", "lang": lang})
    return out


def fetch(days):
    items, errs = [], 0
    for lang, qs in (("en", EN_Q), ("zh", ZH_Q)):
        loc = "hl=en-US&gl=US&ceid=US:en" if lang == "en" else "hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        for q in qs:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q + f' when:{days}d')}&{loc}"
            try:
                items += parse_rss(get(url), lang)
            except Exception as e:  # noqa: BLE001
                errs += 1
                print(f"  [warn] {lang} query failed: {q[:50]}… {e}", file=sys.stderr)
            time.sleep(1.0)
    return items, errs


# ---------- 整理 ----------
def is_readout(x):
    t = x["t"]
    if not t or JUNK.search(t) or JUNK_SRC.search(x.get("s", "")):
        return False
    if not (SIGNAL.search(t) and TRIAL.search(t)):
        return False
    if SOFT_JUNK.search(t) and not (MISS.search(t) or HIT.search(MISS.sub(" ", t))):
        return False
    return True


PREFERRED_SRC = re.compile(r"GlobeNewswire|Business Wire|PR Newswire|Fierce|Endpoints|BioSpace|STAT|Reuters|BioPharma Dive|"
                           r"OncLive|Targeted Oncology|ASCO Post|Evaluate|医药魔方|药明康德|医药观澜|新浪医药|E药经理人|动脉网|丁香园|36氪", re.I)


def enrich(x, lex, groups_re):
    t = x["t"]
    v, stop = verdict(t)
    ph = phase_of(t)
    rec, others = find_drug(t, lex, ph)
    drug = (rec or {}).get("name", "")
    co = find_company(t, groups_re) or (rec or {}).get("co", "")
    if co:
        co = sponsor_group(co) if not re.search(r"[一-鿿]", co) else co
    tg = list((rec or {}).get("tg") or [])
    if not tg and drug:
        tg = tgmod._drug_map([drug])
    if not tg:
        tg = tgmod._uniq(tgmod._hits(t, strict=True), 2)
    mod = (rec or {}).get("mod", "")
    if not mod and drug:
        mod = modality.classify_one({"n": drug, "ty": "DRUG"})
        if mod == "未识别":
            mod = ""
    ta = (rec or {}).get("ta") or ta_of(t)
    return {"d": x["d"], "t": t, "s": x["s"], "u": x["u"], "lang": x["lang"], "v": v, "stop": stop, "ph": ph,
            "drug": drug, "co": co, "tg": tg, "mod": mod, "ta": ta,
            "nct": (rec or {}).get("nct"), "ncts": others[:5]}


def _key(e):
    base = _norm(e["drug"]) or _norm(re.sub(r"\b(phase|trial|study|results?|data|topline|positive|announces?)\b", "", e["t"], flags=re.I))[:40]
    return base


def item_id(e):
    return hashlib.sha1(f"{_key(e)}|{e['v']}|{e['d'][:7]}".encode()).hexdigest()[:10]


def merge(old_items, new_items):
    """新条目和旧库合并：同一个药、同一个判定、14 天内视为同一条读出，补充来源，保留最早日期。"""
    items = [dict(x) for x in old_items]

    def close(a, b):
        try:
            return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days) <= MERGE_DAYS
        except ValueError:
            return False
    added = []
    for e in sorted(new_items, key=lambda z: z["d"]):
        k = _key(e)
        tgt = None
        if k:
            for it in items:
                same_verdict = it["v"] == e["v"] or "待判定" in (it["v"], e["v"])
                if _key(it) == k and same_verdict and close(it["d"], e["d"]):
                    tgt = it
                    break
        if tgt is None:
            for it in items:  # 同一篇文章的不同标题（转载）
                if re.sub(r"\W+", "", it["t"].lower())[:60] == re.sub(r"\W+", "", e["t"].lower())[:60]:
                    tgt = it
                    break
        if tgt is not None:
            srcs = tgt.setdefault("src", [])
            if e["u"] not in {s["u"] for s in srcs} and e["u"] != tgt["u"] and len(srcs) < 6:
                srcs.append({"t": e["t"], "s": e["s"], "u": e["u"], "d": e["d"], "lang": e["lang"]})
            # 更好的来源（新闻稿 / 专业媒体、英文）当标题
            if PREFERRED_SRC.search(e["s"]) and not PREFERRED_SRC.search(tgt["s"]):
                srcs.append({"t": tgt["t"], "s": tgt["s"], "u": tgt["u"], "d": tgt["d"], "lang": tgt["lang"]})
                srcs[:] = [s for s in srcs if s["u"] != e["u"]][:6]
                tgt.update({k2: e[k2] for k2 in ("t", "s", "u", "lang")})
            if tgt["v"] == "待判定" and e["v"] != "待判定":
                tgt["v"] = e["v"]
            for f in ("drug", "co", "ph", "ta", "mod", "nct"):
                if not tgt.get(f) and e.get(f):
                    tgt[f] = e[f]
            if not tgt.get("tg") and e.get("tg"):
                tgt["tg"] = e["tg"]
            tgt["stop"] = tgt.get("stop") or e["stop"]
            tgt["d"] = min(tgt["d"], e["d"]) if tgt["d"] and e["d"] else (tgt["d"] or e["d"])
            continue
        e = dict(e, id=item_id(e), first_seen=dt.date.today().isoformat(), src=[])
        items.append(e)
        added.append(e)
    return items, added


def prune(items, today=None):
    today = today or dt.date.today()
    cut = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    return [x for x in items if (x.get("d") or x.get("first_seen", "")) >= cut]


# ---------- 导出给页面 ----------
def export(data_path, overrides_path, out_path):
    if not os.path.exists(data_path):
        return 0
    d = json.load(open(data_path, encoding="utf-8"))
    ov = json.load(open(overrides_path, encoding="utf-8")) if os.path.exists(overrides_path) else {}
    out = []
    for x in d.get("items", []):
        o = ov.get(x["id"], {})
        if o.get("hide"):
            continue
        y = {**x, **{k: v for k, v in o.items() if k not in ("hide",)}}
        if o:
            y["edited"] = True
        out.append(y)
    out.sort(key=lambda z: (z.get("d") or "", z.get("first_seen") or ""), reverse=True)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump({"generated": d.get("generated"), "items": out}, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    return len(out)


def weekly_md(added, path):
    if not added:
        open(path, "w", encoding="utf-8").write("")
        return
    order = ["未达到", "终止", "混合", "达到", "积极信号", "待判定"]
    lines = [f"本周新抓到 {len(added)} 条新闻稿读出。规则判定只看标题，请逐条核对：判定不对、不是读出或想加点评的，"
             f"按 id 写进 `data/news_overrides.json`，例如 `\"<id>\": {{\"v\": \"未达到\", \"note\": \"…\"}}` 或 `{{\"hide\": true}}`，下次构建生效。", ""]
    for v in order:
        grp = [e for e in added if e["v"] == v]
        if not grp:
            continue
        lines.append(f"### {v}（{len(grp)}）")
        for e in sorted(grp, key=lambda z: z["d"], reverse=True):
            meta = " · ".join(x for x in [e.get("co"), e.get("drug"), (e.get("ph") and f"{e['ph']} 期"), "/".join(e.get("tg") or []),
                                          e.get("ta"), e.get("nct")] if x)
            lines.append(f"- [ ] `{e['id']}` {e['d']} [{e['t']}]({e['u']}) — {e['s']}" + (f"  \n  {meta}" if meta else ""))
        lines.append("")
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--trials", default=os.path.join(ROOT, "data", "trials.json"))
    ap.add_argument("--docs", default=os.path.join(ROOT, "docs"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "news_readouts.json"))
    ap.add_argument("--overrides", default=os.path.join(ROOT, "data", "news_overrides.json"))
    ap.add_argument("--export", default=os.path.join(ROOT, "docs", "news.json"))
    ap.add_argument("--weekly-md", default="weekly_news.md")
    ap.add_argument("--from-xml", nargs="*", help="离线测试：读本地 RSS 文件（文件名含 zh 视为中文）")
    ap.add_argument("--export-only", action="store_true")
    a = ap.parse_args()

    if a.export_only:
        print(f"docs/news.json: {export(a.out, a.overrides, a.export)} items")
        return

    old = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {"items": []}
    try:
        if a.from_xml:
            raw = []
            for f in a.from_xml:
                raw += parse_rss(open(f, "rb").read(), "zh" if "zh" in os.path.basename(f) else "en")
            errs = 0
        else:
            raw, errs = fetch(a.days)
        total_q = len(EN_Q) + len(ZH_Q)
        if not a.from_xml and errs == total_q:
            raise RuntimeError("all queries failed")
        lex = build_lexicon(a.trials, a.docs)
        groups_re = company_regex(lex)
        cands = [x for x in raw if is_readout(x)]
        new = [e for e in (enrich(x, lex, groups_re) for x in cands)
               if not (e["v"] == "待判定" and not (e["ph"] or e["drug"] or e["co"]))]
        items, added = merge(old.get("items", []), new)
        items = prune(items)
        json.dump({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), "items": items},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        weekly_md(added, a.weekly_md)
        from collections import Counter
        print(f"raw {len(raw)} → readout-like {len(cands)} → new {len(added)} (library {len(items)}); "
              f"verdicts {dict(Counter(e['v'] for e in added))}; linked NCT {sum(1 for e in added if e.get('nct'))}; query errors {errs}")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] news readouts not updated, keeping old file: {e}", file=sys.stderr)
    print(f"docs/news.json: {export(a.out, a.overrides, a.export)} items")


if __name__ == "__main__":
    main()
