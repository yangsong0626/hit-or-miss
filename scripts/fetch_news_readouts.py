#!/usr/bin/env python3
"""每周抓取「新闻稿读出」：公司新闻稿和行业媒体里的 topline / 主要终点结果，中英文都抓。

注册库结果通常比新闻稿晚半年到一年，这一层补上最快的信号。来源是 Google News RSS（和 fetch_feeds.py 同一个
入口），按一组读出关键词检索最近 N 天。每条标题按规则判定（达到 / 未达到 / 混合 / 终止 / 待判定），抽出分期、
药名、公司，再用本站已有的试验数据（trials.json、docs/active.json、docs/early.json）对上 NCT 号、治疗领域、
靶点和药物形式。同一个药同一个结论在 14 天内的多篇报道合并成一条。

文件：
  data/news_readouts.json   累积库（保留 365 天，每周合并新条目，不覆盖旧条目的首次出现日期）
  data/news_guidance.json   公司指引的读出时间（"预计 2027 年一季度公布顶线数据"之类），读出日历用
  data/news_overrides.json  人工修正，按条目 id：{"v": 判定, "hide": true, "note": 点评, "nct": ..., "drug": ..., "tg": [...]}
                            重新抓取不会覆盖这个文件；build_site.py 构建时套用
  docs/news.json            页面用（构建时由 export() 生成）
  weekly_news.md            本周新增条目清单（工作流用它开 GitHub issue，方便逐条核对）

来源分两类：Google News（中英文媒体 + 转载的新闻稿，只有标题）和新闻稿通讯社 RSS（PR Newswire、GlobeNewswire、
Newsfile，带摘要，必要时再取正文）。有正文的条目会抽出 HR / 置信区间 / p 值 / ORR / 中位 PFS、OS / 减重幅度等关键数字，
并找出"预计何时公布数据"的指引。会议期间（data/conferences.json）额外按会议名检索。

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
MAX_BODIES = 80          # 每次最多取多少篇新闻稿正文
GUIDE_KEEP_DAYS = 30     # 指引窗口过去多少天后从日历里拿掉

ZH_INN = {k: v for k, v in json.load(open(os.path.join(ROOT, "data", "zh_inn.json"), encoding="utf-8")).items() if not k.startswith("_")}
ZH_INN_KEYS = sorted(ZH_INN, key=len, reverse=True)
try:
    CONFS = json.load(open(os.path.join(ROOT, "data", "conferences.json"), encoding="utf-8"))["items"]
except Exception:  # noqa: BLE001
    CONFS = []

# 新闻稿通讯社：直接拿到公司原文和摘要。地址失效时只记一条警告，不影响其他来源
WIRE_FEEDS = [
    ("PR Newswire", "https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss"),
    ("GlobeNewswire", "https://www.globenewswire.com/RssFeed/industry/4573-Biotechnology/feedTitle/GlobeNewswire%20-%20Industry%20News%20on%20Biotechnology"),
    ("GlobeNewswire", "https://www.globenewswire.com/RssFeed/industry/4577-Pharmaceuticals/feedTitle/GlobeNewswire%20-%20Industry%20News%20on%20Pharmaceuticals"),
    ("Newsfile", "https://feeds.newsfilecorp.com/industry/biotechnology"),
]
WIRE_DOMAINS = re.compile(r"^https?://(www\.)?(prnewswire\.com|globenewswire\.com|newsfilecorp\.com|businesswire\.com|accesswire\.com|prnewswire\.co\.uk)/", re.I)
WIRE_SRC = re.compile(r"PR Newswire|GlobeNewswire|Globe Newswire|Business Wire|Newsfile|ACCESSWIRE|美通社|公司公告|官网|官方", re.I)

GUIDE_Q_EN = ['"topline data" (expected OR anticipated OR "on track")', '("data readout" OR "topline results") (expected OR anticipated) 2027']
GUIDE_Q_ZH = ['"预计" ("公布" OR "读出") ("III期" OR "顶线" OR "关键")']

CONF_RE = re.compile(r"\b(ASCO(?: GI| GU)?|ESMO Congress|ESMO(?: Asia| GI| Breast| IO)?|ASH|AACR|SABCS|EHA|ADA|EASD|ObesityWeek|AASLD|EASL|ACR Convergence|"
                     r"AAD|AAN|CTAD|AD/PD|ESC Congress|AHA|ACC\.?\d{0,2}|WCLC|ELCC|CSCO|DDW|ECCO|UEGW|ATS|ERS|IDWeek|CROI|EULAR|SITC|ISTH|"
                     r"ENDO|Kidney Week|TCT|ASTRO|AUA|ESMO Congress)\b(?:\s*(20\d{2}))?|(CSCO|ASCO|ESMO|ASH|AACR)(?:年会|大会)")

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


# ---------- 关键数字 ----------
_F = r"(\d{1,3}(?:\.\d{1,2})?)"
_R = r"([01]?\.\d{1,3}|[01]\.\d{1,3})"
NUMS = [
    ("HR", re.compile(r"(?:(?<![A-Za-z])HR(?![A-Za-z])|hazard ratio|风险比)\s*(?:of|was|is|=|:|为|是|：)?\s*[=:]?\s*" + _R +
                      r"(?:\s*[;,]?\s*[(\[（]?\s*(?:95\s*%\s*(?:CI|置信区间)|CI)?\s*[:：,]?\s*" + _R + r"\s*(?:-|–|—|to|,|~|至)\s*" + _R + r")?", re.I)),
    ("p", re.compile(r"\bp\s*(?:-?value)?\s*([<=≤]|&lt;)\s*(0?\.\d+|\d(?:\.\d+)?\s*[x×]\s*10\s*\^?\s*-\s*\d+)", re.I)),
    ("ORR", re.compile(r"(?:(?<![A-Za-z])ORR(?![A-Za-z])|objective response rate|overall response rate|客观缓解率|客观应答率)[^\d%]{0,40}?" + _F + r"\s*%", re.I)),
    ("CR", re.compile(r"(?:complete (?:response|remission) rate|\bCR rate\b|完全缓解率)[^\d%]{0,30}?" + _F + r"\s*%", re.I)),
    ("mPFS", re.compile(r"(?:median (?:progression-free survival|PFS)|(?<![A-Za-z])mPFS(?![A-Za-z])|中位(?:无进展生存期?|PFS))[^\d]{0,40}?" + _F + r"\s*(?:months?|mos?\b|个月)", re.I)),
    ("mOS", re.compile(r"(?:median (?:overall survival|OS)|(?<![A-Za-z])mOS(?![A-Za-z])|中位(?:总生存期?|OS))[^\d]{0,40}?" + _F + r"\s*(?:months?|mos?\b|个月)", re.I)),
    ("减重", re.compile(r"" + _F + r"\s*%\s*(?:mean |average )?(?:weight loss|reduction in (?:body )?weight|body weight reduction)|(?:体重|减重)[^\d]{0,12}" + _F + r"\s*%", re.I)),
    ("降低", re.compile(r"(?:reduc\w*|lower\w*|decreas\w*)\s+(?:the\s+)?(?:risk of [\w ,-]{0,40}?|[\w-]+\s+){0,3}?by\s+" + _F + r"\s*%|"
                       + _F + r"\s*%\s*(?:relative )?(?:risk )?reduction in|降低(?:了)?[\u4e00-\u9fff]{0,10}?" + _F + r"\s*%", re.I)),
]


def extract_nums(text):
    """从标题、摘要或正文里抽关键数字，每类只留第一个。返回 [{"k": "HR", "v": "0.68", "lo": "0.55", "hi": "0.84"}, ...]。"""
    out, seen = [], set()
    if not text:
        return out
    for k, rx in NUMS:
        if k in seen:
            continue
        m = rx.search(text)
        if not m:
            continue
        g = [x for x in m.groups() if x]
        if k == "HR":
            try:
                v = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if not (0.05 <= v <= 3):
                continue
            e = {"k": "HR", "v": m.group(1)}
            if m.group(2) and m.group(3):
                e.update(lo=m.group(2), hi=m.group(3))
        elif k == "p":
            op = "<" if m.group(1) in ("<", "&lt;", "≤") else "="
            e = {"k": "p", "v": op + re.sub(r"\s+", "", m.group(2))}
        else:
            if not g:
                continue
            v = g[-1] if k in ("减重", "降低") else g[0]
            try:
                fv = float(v)
            except ValueError:
                continue
            if k in ("ORR", "CR", "减重", "降低") and not (0 < fv <= 100):
                continue
            if k in ("mPFS", "mOS") and not (0 < fv <= 240):
                continue
            e = {"k": k, "v": v}
        out.append(e)
        seen.add(k)
    return out


def merge_nums(a, b):
    have = {x["k"] for x in a or []}
    return (a or []) + [x for x in b or [] if x["k"] not in have]


# ---------- 读出时间指引 ----------
GUIDE_VERB = re.compile(r"expect\w*|anticipat\w*|\bplan\w*|on track|guid\w*|slated|scheduled|intends? to|预计|计划|有望|将于|拟于", re.I)
GUIDE_OBJ = re.compile(r"topline|top-line|data|results?|readout|read-out|report|顶线|数据|结果|读出|揭盲", re.I)
WHEN_EN = re.compile(r"(?:\b(Q[1-4])|\b([1-4])Q)\s*['’]?(20\d{2}|\d{2})\b|\b(first|second|1st|2nd)[- ]half\s*(?:of\s*)?(20\d{2})|\b([12]H|H[12])\s*['’]?(20\d{2}|\d{2})\b|"
                     r"\b(mid|year-end|end of|early|late)[- ](20\d{2})|\b(first|second|third|fourth) quarter of (20\d{2})|\bby (?:the )?end of (20\d{2})|\b(?:in|during) (20\d{2})\b", re.I)
WHEN_ZH = re.compile(r"(20\d{2})\s*年\s*(上半年|下半年|第?[一二三四1-4]\s*季度|Q[1-4]|年中|年底|底|年末|初|内)?")


def _window(y, part):
    y = int(y) if len(str(y)) == 4 else 2000 + int(y)
    part = (part or "").lower()
    q = {"q1": 1, "1": 1, "一": 1, "first": 1, "q2": 2, "2": 2, "二": 2, "second": 2, "q3": 3, "3": 3, "三": 3, "third": 3, "q4": 4, "4": 4, "四": 4, "fourth": 4}
    if part in ("h1", "1h", "first", "1st", "上半年"):
        return f"{y}-01-01", f"{y}-06-30", f"{y} H1"
    if part in ("h2", "2h", "second", "2nd", "下半年"):
        return f"{y}-07-01", f"{y}-12-31", f"{y} H2"
    if part.startswith("quarter:") or part.startswith("q") or "季度" in part:
        n = q.get(part.replace("quarter:", "").replace("第", "").replace("季度", "").strip())
        if n:
            return f"{y}-{3 * n - 2:02d}-01", f"{y}-{3 * n:02d}-{30 if n in (2, 3) else 31}", f"{y} Q{n}"
    if part in ("mid", "年中"):
        return f"{y}-05-01", f"{y}-08-31", f"{y} 年中"
    if part in ("early", "初"):
        return f"{y}-01-01", f"{y}-04-30", f"{y} 年初"
    if part in ("late", "year-end", "end of", "年底", "底", "年末", "by-end"):
        return f"{y}-09-01", f"{y}-12-31", f"{y} 年底"
    return f"{y}-01-01", f"{y}-12-31", f"{y}"


def parse_when(sent):
    m = WHEN_EN.search(sent)
    if m:
        g = m.groups()
        if g[0] or g[1]:
            return _window(g[2], "q" + (g[0] or "q" + g[1])[1:].lower())
        if g[3]:
            return _window(g[4], g[3])
        if g[5]:
            return _window(g[6], g[5])
        if g[7]:
            return _window(g[8], g[7])
        if g[9]:
            return _window(g[10], "quarter:" + g[9].lower())
        if g[11]:
            return _window(g[11], "by-end")
        if g[12]:
            return _window(g[12], "")
    m = WHEN_ZH.search(sent)
    if m:
        return _window(m.group(1), (m.group(2) or "").replace(" ", ""))
    return None


def extract_guidance(text, pub):
    """找"预计 2027 年一季度公布顶线数据"这类句子。返回 [(start, end, label, 句子)]，只留还没过去的窗口。"""
    out = []
    for sent in re.split(r"(?<=[。！？；])|(?<=[.!?;])\s+|\n+", text or ""):
        if len(sent) < 15 or len(sent) > 600:
            continue
        if not (GUIDE_VERB.search(sent) and GUIDE_OBJ.search(sent)):
            continue
        w = parse_when(sent)
        if not w or (pub and w[1] < pub):
            continue
        snip = re.sub(r"\s+", " ", sent).strip()
        out.append((w[0], w[1], w[2], snip[:200] + ("…" if len(snip) > 200 else "")))
    return out


def conf_of(text, d=""):
    """会议名统一成「ESMO 2026」这种写法；标题没写年份就用新闻日期的年份。"""
    m = CONF_RE.search(text or "")
    if not m:
        return ""
    name = (m.group(3) or m.group(1)).replace(" Congress", "").strip()
    yr = m.group(2) or (d or "")[:4]
    return f"{name} {yr}".strip()


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
    for zh in ZH_INN_KEYS:
        i = title.find(zh)
        if i >= 0 and not any(c[0] <= i < c[0] + len(c[1]) for c in cands):
            en = ZH_INN[zh]
            k = _norm(en)
            if not re.search(r"[\u4e00-\u9fff]", zh):  # T-DXd 这类英文简称
                cands.append((i, zh, k if k in lex else None, en))
            else:
                cands.append((i, zh, k if k in lex else None, en))
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9-]{2,}", title):
        w = m.group(0)
        k = _norm(w)
        if k in lex and not GENERIC.match(k) and k not in STOPWORDS and w.lower() not in STOPWORDS:
            if not any(c[0] <= m.start() < c[0] + len(c[1]) for c in cands):
                cands.append((m.start(), w, k, None))
    for rx in (CODE, INN_STEM):
        for m in rx.finditer(title):
            if m.group(0).lower() in STOPWORDS:
                continue
            k = _norm(m.group(0))
            if not any(c[0] <= m.start() < c[0] + max(len(c[1]), 1) for c in cands):
                cands.append((m.start(), m.group(0), k if k in lex else None, None))
    if not cands:
        return None, []
    cands.sort()
    primary = [c for c in cands if not COMPARATOR_BEFORE.search(title[max(0, c[0] - 40):c[0]])] or cands
    pos, shown, k, en = primary[0]
    # 研发代号保留原写法；通用名首字母大写；中文名后面带上英文通用名
    cap = lambda z: z[:1].upper() + z[1:].lower()
    if en:
        disp = f"{shown} ({cap(en)})" if re.search(r"[\u4e00-\u9fff]", shown) else cap(en)
    else:
        disp = shown if re.search(r"\d", shown) else cap(shown)
    if not k:
        return {"nct": None, "ph": "", "set": "", "co": "", "ta": "", "tg": [], "mod": "", "inn": en or "", "name": disp}, []
    recs = sorted(lex[k], key=lambda r: (0 if (ph and ph in (r["ph"] or "")) else 1, SET_RANK.get(r["set"], 9)))
    best = dict(recs[0])
    inn = best.get("inn") or ""
    if not en and re.search(r"\d", shown) and inn and not re.search(r"\d", inn) and _norm(inn) != k:
        disp = f"{cap(inn)} ({shown})"
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
        desc = it.findtext("description") or ""
        summ = html_text(desc)
        if summ and summ.lower().startswith(title.lower()[:40]):  # Google News 的描述就是标题本身
            summ = ""
        out.append({"t": re.sub(r"\s+", " ", title)[:240], "s": src[:60], "d": d, "u": (it.findtext("link") or "").strip(),
                    "lang": lang, "sum": summ[:1500]})
    return out


def html_text(h):
    h = re.sub(r"(?is)<(script|style|noscript|nav|header|footer|aside)[^>]*>.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&rsquo;", "’"), ("&ndash;", "–"), ("&mdash;", "—")):
        h = h.replace(a, b)
    h = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))) if int(m.group(1)) < 0x110000 else " ", h)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", h)).strip()


def fetch_body(url):
    """只取新闻稿通讯社原文（不是 Google News 跳转链接），返回正文前 8000 字。"""
    if not WIRE_DOMAINS.match(url or ""):
        return ""
    raw = get(url, timeout=25, tries=2).decode("utf-8", "replace")
    m = re.search(r"(?is)<(article|div)[^>]+(?:class|id)=\"[^\"]*(release-body|article-body|main-body-container|news-release|bw-release-story|release-content)[^\"]*\"[^>]*>(.*)", raw)
    text = html_text(m.group(3) if m else raw)
    return text[:8000]


def active_confs(today=None):
    today = today or dt.date.today()
    out = []
    for c in CONFS:
        try:
            a, b = dt.date.fromisoformat(c["start"]), dt.date.fromisoformat(c["end"])
        except (KeyError, ValueError):
            continue
        if a - dt.timedelta(days=5) <= today <= b + dt.timedelta(days=3):
            out.append(c)
    return out


def fetch(days):
    items, errs, total = [], 0, 0
    conf_q = [f'"{c["q"]}" (data OR results OR "late-breaking" OR abstract)' for c in active_confs()]
    conf_zh = [f'"{c["q"]}" (数据 OR 结果 OR 口头报告)' for c in active_confs()]
    for lang, qs in (("en", EN_Q + GUIDE_Q_EN + conf_q), ("zh", ZH_Q + GUIDE_Q_ZH + conf_zh)):
        loc = "hl=en-US&gl=US&ceid=US:en" if lang == "en" else "hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        for q in qs:
            total += 1
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q + f' when:{days}d')}&{loc}"
            try:
                items += parse_rss(get(url), lang)
            except Exception as e:  # noqa: BLE001
                errs += 1
                print(f"  [warn] {lang} query failed: {q[:50]}… {e}", file=sys.stderr)
            time.sleep(1.0)
    cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    for name, url in WIRE_FEEDS:
        total += 1
        try:
            got = parse_rss(get(url), "en")
            for x in got:
                x["s"] = x["s"] or name
            items += [x for x in got if not x["d"] or x["d"] >= cut]
        except Exception as e:  # noqa: BLE001
            errs += 1
            print(f"  [warn] wire feed failed: {name} {url[:60]}… {e}", file=sys.stderr)
        time.sleep(1.0)
    return items, errs, total


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
    en_name = (rec or {}).get("inn") or ""
    if not en_name:
        mm = re.search(r"\(([^)]+)\)", drug)
        en_name = mm.group(1) if (mm and re.search(r"[\u4e00-\u9fff]", drug)) else drug
    if not tg and en_name:
        tg = tgmod._drug_map([en_name])
    if not tg:
        tg = tgmod._uniq(tgmod._hits(t, strict=True), 2)
    mod = (rec or {}).get("mod", "")
    if not mod and en_name:
        mod = modality.classify_one({"n": en_name, "ty": "DRUG"})
        if mod == "未识别":
            mod = ""
    ta = (rec or {}).get("ta") or ta_of(t)
    text = " ".join(z for z in (t, x.get("sum", ""), x.get("body", "")) if z)
    tier = "pr" if (WIRE_DOMAINS.match(x["u"] or "") or WIRE_SRC.search(x["s"] or "")
                    or (co and len(_norm(co)) >= 4 and _norm(co) in _norm(x["s"]))) else "media"
    if mod == "未识别":
        mod = ""
    nct = (rec or {}).get("nct")
    m = re.search(r"\bNCT\d{8}\b", text)
    if m:
        nct = m.group(0)
    return {"d": x["d"], "t": t, "s": x["s"], "u": x["u"], "lang": x["lang"], "v": v, "stop": stop, "ph": ph,
            "drug": drug, "co": co, "tg": tg, "mod": mod, "ta": ta, "tier": tier, "conf": conf_of(text, x["d"]),
            "nums": extract_nums(text), "nct": nct, "ncts": others[:5]}


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
            tgt["nums"] = merge_nums(tgt.get("nums"), e.get("nums"))
            if e.get("tier") == "pr":
                tgt["tier"] = "pr"
            for f in ("drug", "co", "ph", "ta", "mod", "nct", "conf"):
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


def merge_guidance(old, new, today=None):
    today = today or dt.date.today()
    cut = (today - dt.timedelta(days=GUIDE_KEEP_DAYS)).isoformat()
    items = [g for g in old if g.get("end", "") >= cut]
    key = lambda g: (_norm(g.get("drug")) or _norm(g.get("co")), g.get("when"))
    have = {key(g): g for g in items}
    n = 0
    for g in sorted(new, key=lambda z: z["d"], reverse=True):
        if g["end"] < cut:
            continue
        k = key(g)
        if k in have:
            if g["d"] > have[k]["d"]:  # 更新的说法覆盖旧的
                have[k].update({f: g[f] for f in ("d", "u", "s", "t", "snip")})
            continue
        g["id"] = "g" + hashlib.sha1(f"{k[0]}|{k[1]}".encode()).hexdigest()[:9]
        items.append(g)
        have[k] = g
        n += 1
    items.sort(key=lambda g: g["start"])
    return items, n


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
    gp = os.path.join(os.path.dirname(data_path), "news_guidance.json")
    guide = json.load(open(gp, encoding="utf-8")).get("items", []) if os.path.exists(gp) else []
    guide = [g for g in guide if not ov.get(g.get("id"), {}).get("hide")]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump({"generated": d.get("generated"), "items": out, "guidance": guide,
               "conf": [{k: c.get(k) for k in ("n", "full", "start", "end", "where", "ta", "src")} for c in CONFS]},
              open(out_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
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
            errs, total_q = 0, 0
        else:
            raw, errs, total_q = fetch(a.days)
        if not a.from_xml and errs == total_q:
            raise RuntimeError("all queries failed")
        lex = build_lexicon(a.trials, a.docs)
        groups_re = company_regex(lex)
        cands = [x for x in raw if is_readout(x)]
        # 新闻稿正文：读出类和带指引字眼的条目，只取通讯社原文
        want = [x for x in raw if WIRE_DOMAINS.match(x["u"] or "") and (x in cands or GUIDE_VERB.search(x["t"] + " " + x.get("sum", "")))]
        nb = 0
        for x in want[:MAX_BODIES]:
            if a.from_xml:
                break
            try:
                x["body"] = fetch_body(x["u"])
                nb += 1
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] body failed: {x['u'][:70]} {e}", file=sys.stderr)
            time.sleep(0.5)
        guide_new = []
        for x in raw:
            for st, en, lab, snip in extract_guidance(" ".join(z for z in (x["t"], x.get("sum", ""), x.get("body", "")) if z), x["d"]):
                rec, _ = find_drug(x["t"] + " " + snip, lex, phase_of(snip))
                co = find_company(x["t"] + " " + snip, groups_re) or (rec or {}).get("co", "")
                if not (rec or co):
                    continue
                guide_new.append({"d": x["d"], "u": x["u"], "s": x["s"], "t": x["t"], "lang": x["lang"], "when": lab, "start": st, "end": en,
                                  "snip": snip, "drug": (rec or {}).get("name", ""), "co": co, "tg": list((rec or {}).get("tg") or []),
                                  "ta": (rec or {}).get("ta") or ta_of(x["t"] + " " + snip), "nct": (rec or {}).get("nct"), "ph": phase_of(snip) or phase_of(x["t"])})
        new = [e for e in (enrich(x, lex, groups_re) for x in cands)
               if not (e["v"] == "待判定" and not (e["ph"] or e["drug"] or e["co"]))]
        items, added = merge(old.get("items", []), new)
        items = prune(items)
        json.dump({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), "items": items},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        weekly_md(added, a.weekly_md)
        gpath = os.path.join(os.path.dirname(a.out), "news_guidance.json")
        gold = json.load(open(gpath, encoding="utf-8")).get("items", []) if os.path.exists(gpath) else []
        gall, gadd = merge_guidance(gold, guide_new)
        json.dump({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), "items": gall},
                  open(gpath, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print(f"guidance: +{gadd} (calendar {len(gall)}); bodies fetched {nb}")
        from collections import Counter
        print(f"raw {len(raw)} → readout-like {len(cands)} → new {len(added)} (library {len(items)}); "
              f"verdicts {dict(Counter(e['v'] for e in added))}; linked NCT {sum(1 for e in added if e.get('nct'))}; query errors {errs}")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] news readouts not updated, keeping old file: {e}", file=sys.stderr)
    print(f"docs/news.json: {export(a.out, a.overrides, a.export)} items")


if __name__ == "__main__":
    main()
