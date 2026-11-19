#!/usr/bin/env python3
"""给搜索引擎生成可收录的静态页：每个靶点、药物、试验一页（中文 + 英文），外加索引页、sitemap.xml、robots.txt、404.html。

交互版仍是 docs/index.html（单页、靠 # 切换），搜索引擎看不到 # 后面的内容，所以另外生成这些普通 HTML。
build_site.py 构建完会自动调用；也可以单独运行（读已经构建好的 docs/index.html 和旁边的 json）：

    python scripts/build_static.py [docs]

网址：/target/<slug>/、/drug/<key>/、/trial/<NCT>/，英文版加 /en/ 前缀。站点地址取环境变量 SITE_URL。
"""
import collections
import datetime
import hashlib
import html as H
import json
import os
import re
import urllib.parse
import shutil
import sys
import unicodedata
from urllib.parse import quote, urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from molecules import core_names as _core_names  # noqa: E402
from modality import BACKBONE as _BACKBONE  # noqa: E402

DEFAULT_SITE = "https://hit-or-miss-cz5.pages.dev/"
GEN_DIRS = ("target", "drug", "trial", "targets", "drugs", "trials", "failures", "en")
CJK = re.compile(r"[㐀-鿿]")
PL = re.compile(r"placebo|standard of care|best supportive|saline|vehicle|sham|usual care|observation|"
                r"investigator'?s? choice|physician'?s? choice|treatment of physician|\bSOC\b|matching|dummy", re.I)
NOT_DRUG = re.compile(r"^(chemotherapy|radiation|radiotherapy|surgery|blood|biopsy|questionnaire|control|placebo|standard|"
                      r"best|investigator|physician|no intervention|observation|usual|treatment|therapy|drug|study drug|"
                      r"cohort|arm|part|group|dose|regimen|combination|monotherapy|other|sequence)( [A-Z0-9]{1,2})?$", re.I)
PH_ORD = {"1": 1, "1/2": 1.5, "2": 2, "2/3": 2.5, "3": 3}
STATUS = {"RECRUITING": ("招募中", "Recruiting"), "ACTIVE_NOT_RECRUITING": ("进行中，不再招募", "Active, not recruiting"),
          "NOT_YET_RECRUITING": ("尚未招募", "Not yet recruiting"), "COMPLETED": ("已完成", "Completed"),
          "TERMINATED": ("已终止", "Terminated"), "ENROLLING_BY_INVITATION": ("邀请入组", "Enrolling by invitation"),
          "WITHDRAWN": ("已撤回", "Withdrawn"), "SUSPENDED": ("暂停", "Suspended"), "UNKNOWN": ("未知", "Unknown")}
SETS = {"results": ("已公布结果", "Results posted"), "completed": ("已完成，待公布结果", "Completed, awaiting results"),
        "upcoming": ("即将到达主要完成日", "Primary completion due"), "stopped": ("提前终止", "Stopped early"),
        "active": ("在研", "Ongoing"), "early": ("近两年新登记", "Recently registered")}
VCLS = {"达到": "pos", "未达到": "neg", "部分达到": "mix", "终止": "neg", "混合": "mix", "积极信号": "pos"}
V_EN = {"积极信号": "Positive signal", "混合": "Mixed", "待判定": "Pending", "达到": "Met", "未达到": "Missed", "终止": "Stopped"}
NUM_EN = {"减重": "Weight loss", "降低": "Reduction", "完全缓解率": "CR rate"}
OUTV = {"pos": "达到", "neg": "未达到", "mix": "混合"}
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "κ": "kappa", "μ": "mu", "θ": "theta", "ε": "epsilon"}


# ---------------- 工具 ----------------
def esc(s):
    return H.escape(str(s if s is not None else ""), quote=True)


def nk(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def dkeys(name):
    """和页面里的 drugKeys 一致：主名 + 括号里的英文名或代号。"""
    s, out = str(name or ""), []
    main = re.split(r"[(（\[]", s)[0]
    if not CJK.search(main):
        out.append(nk(main))
    for p in re.findall(r"[(（]([^)）]+)[)）]", s):
        out += [k for k in (nk(z) for z in re.split(r"[,;/]", p)) if not JUNK_KEY.search(k)]
    return [k for k in dict.fromkeys(out) if len(k) >= 4]


CODE = re.compile(r"^[a-z]{1,6}\d{2,}[a-z0-9]{0,3}$")
INN = re.compile(r"^[a-z]{6,}$")


# 括号里常见的剂量、分组、设计描述，不是药名，不能拿来把不同的药并成一组
JUNK_KEY = re.compile(r"^\d|dose|^part[a-z]?$|^part[a-z]|blind|openlabel|regimen|^drug$|chemo|combination|monotherapy|"
                      r"^anti|^(low|high|mid|medium|full|split|double|single|selected|intermediate)|treatment|therapy|"
                      r"^cohort|^arm|^group|^sequence|^placebo|^standard|^control|albuminbound|vaccine$|tracer|^with")


def main_name(n):
    return re.split(r"[(（\[]", str(n or ""))[0].strip(" ,;")


def phn(p):
    return PH_ORD.get(str(p or ""), 0)


def cut(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def slugify(s):
    s = "".join(GREEK.get(c, c) for c in str(s))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def is_ctl(iv):
    n = iv.get("n") or ""
    return iv.get("r") == "c" or bool(PL.search(n)) or bool(NOT_DRUG.match(main_name(n)))


# ---------------- 英文翻译（移植页面里的 TR） ----------------
class Tr:
    PUNC = [("，", ", "), ("。", ". "), ("；", "; "), ("：", ": "), ("、", ", "), ("（", " ("), ("）", ") "), ("「", "“"),
            ("」", "”"), ("！", "! "), ("？", "? "), ("～", "~"), ("　", " ")]

    def __init__(self, i18n):
        U = (i18n or {}).get("ui") or {}
        self.ex = U.get("exact") or {}
        self.content = (i18n or {}).get("content") or {}
        self.pats, self.subs = [], []
        for a, b in U.get("patterns") or []:
            try:
                self.pats.append((re.compile(a), b))
            except re.error:
                pass
        for a, b in U.get("subs") or []:
            try:
                self.subs.append((re.compile(a), b))
            except re.error:
                pass
        self.phr = sorted((U.get("phrases") or {}).items(), key=lambda x: -len(x[0]))
        self.cache = {}

    def tidy(self, r):
        for a, b in self.PUNC:
            r = r.replace(a, b)
        r = re.sub(r" {2,}", " ", r)
        r = re.sub(r" ([,.;:)!?])", r"\1", r)
        return r.replace("( ", "(").strip()

    @staticmethod
    def _rep(rep, m, f):
        return re.sub(r"\$(\d)", lambda x: f(m.group(int(x.group(1))) or "") if int(x.group(1)) <= (m.re.groups or 0) else "", rep)

    def phrase(self, core):
        r = core
        for rx, rep in self.subs:
            r = rx.sub(lambda m, rep=rep: self._rep(rep, m, lambda s: s), r)
        for zh, en in self.phr:
            if zh in r:
                r = r.replace(zh, " " + en + " ")
        return self.tidy(r)

    def __call__(self, s):
        if not s or not isinstance(s, str) or not CJK.search(s):
            return s
        if s in self.cache:
            return self.cache[s]
        core = s.strip()
        r = self.ex.get(core)
        if r is None:
            r = self.content.get(core)
        if r is None:
            for rx, rep in self.pats:
                m = rx.search(core)
                if m:
                    r = self._rep(rep, m, self)
                    r = self.phrase(r) if CJK.search(r) else self.tidy(r)
                    break
        if r is None:
            ph = self.phrase(core)
            r = ph if not CJK.search(ph) or len(core) <= 80 else core
        self.cache[s] = r
        return r


# ---------------- 数据整理 ----------------
class Site:
    def __init__(self, d, docs, site_url):
        self.d, self.docs = d, docs
        self.site = site_url.rstrip("/") + "/"
        self.base = urlparse(self.site).path or "/"
        self.tr = Tr(d.get("i18n"))
        self.asof = d.get("generated") or datetime.date.today().isoformat()
        self.cut12 = (datetime.date.fromisoformat(self.asof) - datetime.timedelta(days=365)).isoformat()
        self.h6 = (datetime.date.fromisoformat(self.asof) + datetime.timedelta(days=183)).isoformat()

        def lj(fn, key):
            p = os.path.join(docs, fn)
            try:
                return json.load(open(p, encoding="utf-8")).get(key) or []
            except (OSError, ValueError):
                return []
        news = {}
        try:
            news = json.load(open(os.path.join(docs, "news.json"), encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.news = [x for x in news.get("items") or [] if x.get("v") != "待判定"]
        self.guide = news.get("guidance") or []
        try:
            st = json.load(open(os.path.join(docs, "structures.json"), encoding="utf-8"))
            self.struct = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            self.struct = {}
        try:
            self.mol = json.load(open(os.path.join(docs, "molecules.json"), encoding="utf-8"))
        except (OSError, ValueError):
            self.mol = {"drugs": {}}
        self.curated = (d.get("curated") or {}).get("readouts") or []
        self._load_taxonomy(os.path.join(docs, "..", "data", "target_taxonomy.json"))
        self.alias = (d.get("tgsearch") or {}).get("alias") or {}
        self.known = (d.get("tgsearch") or {}).get("drugs") or {}

        # 全部试验：四套主数据（有详情页）+ 在研 II/III + 早期新登记
        self.trials, seen = [], set()
        for sname, lst in (d.get("sets") or {}).items():
            for t in lst:
                if t.get("nct") and t["nct"] not in seen:
                    seen.add(t["nct"])
                    t["_set"] = sname
                    self.trials.append(t)
        self.main = {t["nct"]: t for t in self.trials}
        for sname, fn in (("active", "active.json"), ("early", "early.json")):
            for t in lj(fn, "trials"):
                if t.get("nct") and t["nct"] not in seen:
                    seen.add(t["nct"])
                    t["_set"] = sname
                    self.trials.append(t)
        self._drugs()
        self._targets()
        self.fail = collect_failures(self)

    # ---- 药物：把同一个药的各种写法（通用名、代号、商品名）并成一组 ----
    def _drugs(self):
        par = {}

        def find(k):
            par.setdefault(k, k)
            while par[k] != k:
                par[k] = par[par[k]]
                k = par[k]
            return k

        def union(ks):
            ks = [k for k in ks if k]
            for k in ks:
                find(k)
            # 只在「研发代号 ↔ 通用名」之间合并（如 IBI362 (mazdutide)），而且括号里同类名字只有一个；
            # 像 AK112 (AK104, cadonilimab) 这种写法分不清谁是谁，不合并
            rest = ks[1:]
            if CODE.match(ks[0]):
                cand = [k for k in rest if INN.match(k)] if not any(CODE.match(k) for k in rest) else []
            elif INN.match(ks[0]):
                cand = [k for k in rest if CODE.match(k)]
            else:
                cand = []
            if len(cand) == 1:
                a, b = find(ks[0]), find(cand[0])
                if a != b:
                    par[b] = a
        prim, names = collections.Counter(), collections.defaultdict(collections.Counter)

        def note(n, w=1):
            ks = dkeys(n)
            if not ks or NOT_DRUG.match(main_name(n)):
                return []
            union(ks)
            prim[ks[0]] += w
            nm = main_name(n)
            if nm and not CJK.search(nm):
                names[ks[0]][nm] += w
            return ks
        for t in self.trials:
            for iv in t.get("iv") or []:
                if not is_ctl(iv):
                    note(iv["n"])
        for x in self.news:
            note(x.get("drug"), 2)
        for c in self.curated:
            note(c.get("drug"), 3)
        groups = collections.defaultdict(list)
        for k in list(par):
            groups[find(k)].append(k)
        self.dcanon = {}
        self.dinfo = {}
        for root, ks in groups.items():
            ks.sort(key=lambda k: (-prim[k], not k.isalpha(), k))
            c = ks[0]
            for k in ks:
                self.dcanon[k] = c
            nm = collections.Counter()
            for k in ks:
                nm.update(names[k])
            self.dinfo[c] = {"key": c, "keys": ks, "name": (nm.most_common(1)[0][0] if nm else c), "trials": [],
                             "news": [], "cur": [], "guide": []}

        def cl(n):
            ks = dkeys(n)
            return self.dcanon.get(ks[0]) if ks else None
        self.dcl = cl
        for t in self.trials:
            got = set()
            for iv in t.get("iv") or []:
                if is_ctl(iv):
                    continue
                c = cl(iv["n"])
                if c and c not in got:
                    got.add(c)
                    self.dinfo[c]["trials"].append(t)
            t["_drugs"] = sorted(got, key=lambda c: [cl(iv["n"]) for iv in t.get("iv") or []].index(c)
                                 if c in [cl(iv["n"]) for iv in t.get("iv") or []] else 99)
        for x in self.news:
            c = cl(x.get("drug"))
            if c:
                self.dinfo[c]["news"].append(x)
        for c_ in self.curated:
            c = cl(c_.get("drug"))
            if c:
                self.dinfo[c]["cur"].append(c_)
        for g in self.guide:
            c = cl(g.get("drug"))
            if c:
                self.dinfo[c]["guide"].append(g)
        # 有详情页的药：出现在主数据里、有新闻稿 / 精选读出，或者至少 3 项试验
        self.dpage = {c for c, x in self.dinfo.items()
                      if x["news"] or x["cur"] or len(x["trials"]) >= 3 or any(t["nct"] in self.main for t in x["trials"])}
        for c in self.dpage:
            x = self.dinfo[c]
            x["trials"].sort(key=lambda t: (-phn(t.get("phase")), str(t.get("results") or t.get("pcd") or "")), reverse=False)

    # ---- 靶点 ----
    def _targets(self):
        self.tinfo = {}
        for t in self.trials:
            for g in t.get("tg") or []:
                self.tinfo.setdefault(g, {"g": g, "trials": [], "news": [], "cur": []})["trials"].append(t)
        for x in self.news:
            for g in x.get("tg") or []:
                if g in self.tinfo:
                    self.tinfo[g]["news"].append(x)
        for c in self.curated:
            for g in c.get("tg") or ([c["tgt"]] if c.get("tgt") else []):
                if g in self.tinfo:
                    self.tinfo[g]["cur"].append(c)
        self.tslug, used = {}, set()
        for g in sorted(self.tinfo, key=lambda g: -len(self.tinfo[g]["trials"])):
            s = slugify(self.tr(g)) or slugify(g)
            if not s or s in used:
                s = (s + "-" if s else "t-") + hashlib.md5(g.encode()).hexdigest()[:6]
            used.add(s)
            self.tslug[g] = s
        for g, x in self.tinfo.items():
            x["progs"] = self._programs(g, x["trials"])

    def _programs(self, g, trials):
        P = {}
        for t in trials:
            ents = [e for e in t.get("tgm") or [] if e.get("g") == g] or [{"g": g, "n": "", "m": t.get("mod"), "k": ""}]
            for e in ents:
                c = self.dcl(e.get("n")) if e.get("n") else None
                pid = c or e.get("k") or ("?" + (t.get("group") or t.get("sponsor") or t["nct"]))
                p = P.setdefault(pid, {"id": pid, "drug": c, "name": "", "cos": collections.Counter(), "mods": collections.Counter(),
                                       "ph": "", "trials": [], "fp": "9999"})
                if c and c in self.dinfo:
                    p["name"] = self.dinfo[c]["name"]
                elif e.get("n") and not p["name"]:
                    p["name"] = main_name(e["n"])
                p["cos"][t.get("group") or t.get("sponsor") or ""] += 1
                if e.get("m") and e["m"] != "未识别":
                    p["mods"][e["m"]] += 1
                if phn(t.get("phase")) > phn(p["ph"]):
                    p["ph"] = t.get("phase")
                if t not in p["trials"]:
                    p["trials"].append(t)
                if t.get("fp") and t["fp"] < p["fp"]:
                    p["fp"] = t["fp"]
                break
        return sorted(P.values(), key=lambda p: (-phn(p["ph"]), -len(p["trials"]), p["name"] or "~"))

    # ---- 网址 ----
    def path(self, lang, kind, slug=""):
        return self.base + ("en/" if lang == "en" else "") + kind + "/" + (quote(slug, safe="") + "/" if slug else "")

    def abs(self, p):
        return self.site.rstrip("/") + p if p.startswith("/") else self.site + p

    def _load_taxonomy(self, path):
        """靶点分类（类别 › 家族）、通路（按上下游排的阶段）和额外关系，见 scripts/make_target_taxonomy.py。"""
        try:
            self.tax = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            self.tax = {"classes": [], "pathways": [], "links": [], "rel_lbl": {}}
        self.tax_of, self.fam_members, self.paths_of, self.links_of = {}, {}, collections.defaultdict(list), collections.defaultdict(list)
        for c in self.tax["classes"]:
            for f in c["families"]:
                self.fam_members[f["id"]] = f["targets"]
                for g in f["targets"]:
                    self.tax_of[g] = (c, f)
        for pw in self.tax["pathways"]:
            for i, st in enumerate(pw["steps"]):
                for g in st:
                    self.paths_of[g].append((pw, i))
        for a, b, ty in self.tax["links"]:
            self.links_of[a].append((b, ty))
            self.links_of[b].append((a, ty))

    def app(self, lang, frag=""):
        return self.base + ("?lang=en" if lang == "en" else "") + (("#" + frag) if frag else "")

    def tlink(self, lang, g):
        return f'<a href="{self.path(lang, "target", self.tslug[g])}">{esc(self.tr(g) if lang == "en" else g)}</a>' if g in self.tslug else esc(g)

    def dlink(self, lang, c, label=None):
        nm = label or (self.dinfo[c]["name"] if c in self.dinfo else c)
        return f'<a href="{self.path(lang, "drug", c)}">{esc(nm)}</a>' if c in self.dpage else esc(nm)

    def nlink(self, lang, t, label=None):
        lbl = esc(label or t.get("acronym") or cut(t.get("title"), 70))
        if t["nct"] in self.main:
            return f'<a href="{self.path(lang, "trial", t["nct"])}">{lbl}</a>'
        if t["nct"].startswith("NCT"):
            return f'<a href="https://clinicaltrials.gov/study/{t["nct"]}" rel="noopener" target="_blank">{lbl}</a>'
        return lbl


# ---------------- 页面外壳 ----------------
def T(lang, zh, en):
    return zh if lang == "zh" else en


def pl(n, w, ws=None):
    return f"{n} {w if n == 1 else (ws or w + 's')}"


def ph_lbl(lang, p):
    return (f"{p} 期" if lang == "zh" else f"Phase {p}") if p else "—"


def st_lbl(lang, s):
    return STATUS.get(s, (s, s))[0 if lang == "zh" else 1] if s else ""


def page(S, lang, kind, slug, title, desc, body, crumbs, ld=None):
    """kind 为 None 时（404 页）不写 canonical 和语言互链。"""
    alt = kind is not None
    zh_p, en_p = (S.path("zh", kind, slug), S.path("en", kind, slug)) if alt else (S.app("zh"), S.app("en"))
    me = zh_p if lang == "zh" else en_p
    other = en_p if lang == "zh" else zh_p
    nav = [(S.path(lang, "targets"), T(lang, "靶点", "Targets")), (S.path(lang, "drugs"), T(lang, "药物", "Drugs")),
           (S.path(lang, "trials"), T(lang, "试验", "Trials")), (S.path(lang, "failures"), T(lang, "失败库", "Failures")),
           (S.app(lang), T(lang, "交互版", "Interactive app"))]
    bc = [{"@type": "ListItem", "position": i + 1, "name": n, "item": S.abs(u)} for i, (u, n) in enumerate(crumbs)]
    lds = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": bc}] + ([ld] if ld else [])
    ldj = "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False).replace("</", "<\\/") + "</script>" for x in lds)
    alts = (f'<link rel="alternate" hreflang="zh" href="{S.abs(zh_p)}"><link rel="alternate" hreflang="en" href="{S.abs(en_p)}">'
            f'<link rel="alternate" hreflang="x-default" href="{S.abs(zh_p)}">') if alt else ""
    crumb_html = " <span>/</span> ".join(f'<a href="{u}">{esc(n)}</a>' for u, n in crumbs[:-1]) + (
        f' <span>/</span> <span>{esc(crumbs[-1][1])}</span>' if len(crumbs) > 1 else "")
    return f"""<!doctype html>
<html lang="{T(lang, 'zh-CN', 'en')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(cut(desc, 160))}">
{f'<link rel="canonical" href="{S.abs(me)}">' if alt else '<meta name="robots" content="noindex">'}
{alts}
<meta property="og:type" content="website"><meta property="og:site_name" content="Hit or Miss">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(cut(desc, 200))}">
<meta property="og:url" content="{S.abs(me)}">
<link rel="stylesheet" href="{S.base}static.css">
{ldj}
</head>
<body>
<header class="top"><a class="brand" href="{S.app(lang)}">Hit <span>or</span> Miss</a>
<nav>{"".join(f'<a href="{u}">{esc(n)}</a>' for u, n in nav)}<a class="lang" href="{other}" hreflang="{T(lang, 'en', 'zh')}">{T(lang, 'EN', '中文')}</a></nav></header>
<main>
<div class="crumb">{crumb_html}</div>
{body}
</main>
<footer>{T(lang, "注册库数据来自 ClinicalTrials.gov 和欧盟 CTIS；新闻稿读出来自公司公告与行业媒体，每条附来源。成败判定按登记的主要终点统计分析和规则推断，只作参考，引用前请核对原始来源；不构成投资或诊疗建议。",
             "Registry data from ClinicalTrials.gov and EU CTIS; topline news from company press releases and trade media, each linked to its source. Hit / miss calls are rule-based on the registered primary-endpoint analysis and are for reference only; check the original sources before citing. Not investment or medical advice.")}
 · <a href="{S.app(lang)}">Hit or Miss</a></footer>
</body>
</html>
"""


def table(head, rows, cls=""):
    if not rows:
        return ""
    return (f'<div class="tw"><table class="{cls}"><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead><tbody>'
            + "".join(r if isinstance(r, str) else "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")


def vbadge(S, lang, v):
    if not v:
        return ""
    lbl = (V_EN.get(v) or S.tr(v)) if lang == "en" else v
    return f'<span class="v {VCLS.get(v, "")}">{esc(lbl)}</span>'


def kpis(items):
    return '<div class="kpis">' + "".join(f'<div><b>{esc(n)}</b><span>{esc(l)}</span></div>' for n, l in items) + "</div>"


# ---------------- 失败原因库 ----------------
# 三个来源合在一起：主要终点未达到的试验、提前终止的试验（注册库填的终止原因已归类为 why_cat）、
# 新闻稿里的失败 / 终止（同一 NCT 已有试验记录的不重复算）。「目标已达成」的提前结束不算失败。
FAIL_R = [("eff", "疗效不足", "Efficacy"), ("safe", "安全性", "Safety"), ("biz", "商业 / 战略", "Business / strategy"),
          ("ops", "入组 / 运营", "Enrollment / operations"), ("reg", "监管", "Regulatory"), ("unk", "未说明 / 其他", "Not stated / other")]
FAIL_LBL = {k: (zh, en) for k, zh, en in FAIL_R}
FAIL_WHY = {"疗效 / 无效性": "eff", "安全性": "safe", "申办方决定 / 战略": "biz", "资金": "biz", "入组 / 运营": "ops",
            "监管": "reg", "其他": "unk", "未填写": "unk", "": "unk"}
FAIL_SAFE = re.compile(r"safety|adverse event|toxicit|death|died|fatal|hepatotox|clinical hold|serious adverse", re.I)
FAIL_NOSAFE = re.compile(r"(not|no|without|unrelated|independent of)\b[^.;]{0,40}safety|safety[^.;]{0,20}(not|no)\b", re.I)
FAIL_EFF = re.compile(r"futil|lack of efficacy|insufficient efficacy|did not meet|failed to (meet|show|demonstrate)|no (clinical )?benefit|unlikely to meet", re.I)
# 「申办方决定」里其实是看了数据才停的：其他研究的结果、期中分析、疗效数据
FAIL_DATA = re.compile(r"(driven by|based on|due to|following|in light of|after (review(ing)?|evaluation of))[^.;]{0,40}"
                       r"(results?|data|findings|outcome|readout)[^.;]{0,30}(from|of|in)?[^.;]{0,40}(study|trial|analysis|stud)"
                       r"|interim analysis|futility analysis|efficacy (data|results)", re.I)
FAIL_NOEFF = re.compile(r"not (related to|due to|based on|driven by)[^.;]{0,20}(efficacy|data|results)", re.I)


def fail_reason(t):
    """(原因, 类型) 或 None。类型：miss 主要终点未达到，stop 提前终止。"""
    if trial_verdict(t) == "未达到":
        return "eff", "miss"
    if t.get("_set") == "stopped" or t.get("status") in ("TERMINATED", "WITHDRAWN", "SUSPENDED"):
        wc = t.get("why_cat") or ""
        if wc == "目标已达成":
            return None
        r = FAIL_WHY.get(wc, "unk")
        why = t.get("why") or ""
        # 「未说明 / 其他」按原文补判：写了安全性（且不是「与安全性无关」）或无效性的改过来；
        # 「申办方决定」里写明是看了其他研究结果、期中分析或疗效数据才停的，改归疗效不足
        if r == "unk":
            if FAIL_SAFE.search(why) and not FAIL_NOSAFE.search(why):
                r = "safe"
            elif FAIL_EFF.search(why) or (FAIL_DATA.search(why) and not FAIL_NOEFF.search(why)):
                r = "eff"
        elif r == "biz" and (FAIL_EFF.search(why) or FAIL_DATA.search(why)) and not FAIL_NOEFF.search(why):
            r = "eff"
        return r, "stop"
    return None


def fail_drugs(S, t):
    """试验里的药，标准背景药（PD-1 单抗、化疗……）排后面，表格里先看到真正的受试药。"""
    ds = list(t.get("_drugs") or [])
    return sorted(ds, key=lambda c: bool(_BACKBONE.match((S.dinfo[c]["name"] if c in S.dinfo else c) or "")))


def collect_failures(S):
    by_nct = {t["nct"]: t for t in S.trials if t.get("nct")}
    out, done = [], set()
    for t in S.trials:
        if t.get("_set") not in ("results", "stopped"):
            continue
        fr = fail_reason(t)
        if not fr:
            continue
        r, kind = fr
        done.add(t["nct"])
        if kind == "miss":
            why = cut("; ".join(t.get("primary") or []), 160)
        else:
            why = cut(t.get("why") or "", 220)
        ds = fail_drugs(S, t)
        out.append({"t": t, "nct": t["nct"], "r": r, "k": kind, "g": list(t.get("tg") or []), "c": (ds or [None])[0], "ds": ds,
                    "co": t.get("group") or t.get("sponsor") or "", "ph": t.get("phase") or "", "mod": t.get("mod") or "",
                    "ta": t.get("ta") or "", "d": trial_date(t) or "", "why": why, "cond": (t.get("conditions") or [""])[0]})
    for x in S.news:
        if x.get("v") not in ("未达到", "终止"):
            continue
        ncts = [n for n in ([x.get("nct")] + list(x.get("ncts") or [])) if n]
        if any(n in done for n in ncts):
            continue
        if x.get("v") == "未达到":
            r = "eff"
        else:
            tt = x.get("t") or ""
            r = "safe" if FAIL_SAFE.search(tt) and not FAIL_NOSAFE.search(tt) else "eff" if FAIL_EFF.search(tt) else "unk"
        gs = list(x.get("tg") or [])
        if not gs:
            for n in ncts:
                for g in (by_nct.get(n) or {}).get("tg") or []:
                    if g not in gs:
                        gs.append(g)
        done.update(ncts)
        out.append({"t": None, "x": x, "nct": ncts[0] if ncts else "", "r": r, "k": "news", "g": gs, "c": S.dcl(x.get("drug")),
                    "name": x.get("drug") or "", "co": x.get("co") or "", "ph": x.get("ph") or "", "mod": x.get("mod") or "",
                    "ta": x.get("ta") or "", "d": x.get("d") or "", "why": x.get("t") or "", "u": x.get("u") or "", "cond": ""})
    out.sort(key=lambda e: e["d"], reverse=True)
    for e in out:
        for g in e["g"]:
            if g in S.tinfo:
                S.tinfo[g].setdefault("fail", []).append(e)
    return out


def fail_counts(evs):
    c = collections.Counter(e["r"] for e in evs)
    return [c.get(k, 0) for k, _, _ in FAIL_R]


def fail_chip(lang, r):
    return f'<span class="fr fr-{r}">{esc(FAIL_LBL[r][0 if lang == "zh" else 1])}</span>'


def fail_rows(S, lang, evs, with_target=False):
    tr = S.tr if lang == "en" else (lambda s: s)
    rows = []
    for e in evs:
        if e["t"] is not None:
            drug = ", ".join(S.dlink(lang, c) for c in (e.get("ds") or [])[:2]) or "—"
            src = S.nlink(lang, e["t"], e["nct"])
            if e["k"] == "miss":
                basis = T(lang, "主要终点未达到", "Missed primary endpoint") + (f'<div class="sm">{esc(e["why"])}</div>' if e["why"] else "")
            else:
                basis = esc(tr(e["t"].get("why_cat") or "")) + (f'<div class="sm">“{esc(e["why"])}”</div>' if e["why"] else "")
        else:
            drug = S.dlink(lang, e["c"]) if e["c"] in S.dpage else esc(e["name"])
            src = f'<a href="{esc(e["u"])}" rel="noopener" target="_blank">{T(lang, "新闻稿", "News")}</a>' if e.get("u") else ""
            basis = f'<span class="sm">{esc(cut(e["why"], 140))}</span>'
        row = [esc(e["d"]), drug, esc(e["co"]), esc(ph_lbl(lang, e["ph"]))]
        if with_target:
            row.append(" · ".join(S.tlink(lang, g) for g in e["g"][:2]) or "—")
        row += [esc(cut(e["cond"], 50)) or "—", fail_chip(lang, e["r"]), basis, src]
        rows.append(row)
    return rows


def fail_head(lang, with_target=False):
    h = [T(lang, "日期", "Date"), T(lang, "药物", "Drug"), T(lang, "公司", "Company"), T(lang, "阶段", "Phase")]
    if with_target:
        h.append(T(lang, "靶点", "Target"))
    return h + [T(lang, "适应症", "Indication"), T(lang, "原因", "Reason"), T(lang, "依据", "Basis"), T(lang, "来源", "Source")]


def fail_section(S, lang, g):
    evs = S.tinfo[g].get("fail") or []
    if not evs:
        return ""
    tr = S.tr if lang == "en" else (lambda s: s)
    cnt = dict(zip([k for k, _, _ in FAIL_R], fail_counts(evs)))
    eff = [e for e in evs if e["r"] == "eff"]
    mods = collections.Counter(e["mod"] for e in eff if e["mod"])
    conds = collections.Counter(e["cond"] for e in eff if e["cond"])
    if lang == "zh":
        s = f"本站记录到 {len(evs)} 次失败或提前终止，其中疗效不足 {cnt['eff']} 次、安全性 {cnt['safe']} 次、商业 / 战略原因 {cnt['biz']} 次。"
        if eff and mods:
            s += "疗效失败集中在 " + "、".join(f"{m}（{n}）" for m, n in mods.most_common(2))
            s += ("，适应症以 " + "、".join(f"{c}（{n}）" for c, n in conds.most_common(2) if n > 1) + " 为主。") if any(n > 1 for n in conds.values()) else "。"
    else:
        s = f"{pl(len(evs), 'failure or early stop', 'failures or early stops')} recorded: {cnt['eff']} for efficacy, {cnt['safe']} for safety, {cnt['biz']} for business or strategy."
        if eff and mods:
            s += " Efficacy failures cluster in " + ", ".join(f"{tr(m)} ({n})" for m, n in mods.most_common(2))
            s += ("; indications: " + ", ".join(f"{c} ({n})" for c, n in conds.most_common(2) if n > 1) + ".") if any(n > 1 for n in conds.values()) else "."
    chips = " ".join(f'{fail_chip(lang, k)} {cnt[k]}' for k, _, _ in FAIL_R if cnt[k])
    # 药物形式 × 原因（有两种以上形式时才列）
    bym = collections.defaultdict(list)
    for e in evs:
        bym[e["mod"] or T(lang, "未识别", "Unclassified")].append(e)
    mt = ""
    if len(bym) > 1:
        mt = table([T(lang, "药物形式", "Modality")] + [FAIL_LBL[k][0 if lang == "zh" else 1] for k, _, _ in FAIL_R] + [T(lang, "合计", "Total")],
                   [[esc(tr(m))] + [str(n or "") for n in fail_counts(v)] + [f"<b>{len(v)}</b>"] for m, v in sorted(bym.items(), key=lambda x: -len(x[1]))], "ftab")
    return (f'<h2 id="fail">{T(lang, "失败与终止", "Failures and early stops")} <small>{len(evs)}</small></h2>'
            f'<p>{esc(s)}</p><p class="rel">{chips}</p>{mt}'
            + table(fail_head(lang), fail_rows(S, lang, evs[:60]))
            + f'<p class="sm">{T(lang, "原因来自注册库填写的终止理由（已归类）、登记的主要终点统计结果和新闻稿；「商业 / 战略」多为申办方未说明具体原因。", "Reasons come from registry stop reasons (classified), registered primary-endpoint results and topline news; “business / strategy” often means the sponsor gave no specific reason.")} '
              f'<a href="{S.path(lang, "failures")}">{T(lang, "全部靶点的失败原因 →", "Failure reasons across all targets →")}</a></p>')


def hub_failures(S, lang):
    tr = S.tr if lang == "en" else (lambda s: s)
    evs = S.fail
    cnt = fail_counts(evs)
    L = 0 if lang == "zh" else 1
    head = [FAIL_LBL[k][L] for k, _, _ in FAIL_R] + [T(lang, "合计", "Total")]

    def agg(key, link, min_n=1, limit=200):
        by = collections.defaultdict(list)
        for e in evs:
            for k in key(e):
                if k:
                    by[k].append(e)
        rows = []
        for k, v in sorted(by.items(), key=lambda x: (-(sum(1 for e in x[1] if e["r"] in ("eff", "safe"))), -len(x[1]))):
            if len(v) < min_n:
                continue
            c = fail_counts(v)
            rows.append([link(k)] + [(f"<b>{n}</b>" if i < 2 and n else str(n or "")) for i, n in enumerate(c)] + [str(len(v)), esc(v[0]["d"])])
        return rows[:limit]
    tg_rows = agg(lambda e: e["g"], lambda g: (f'<a href="{S.path(lang, "target", S.tslug[g])}#fail">{esc(tr(g))}</a>' if g in S.tslug else esc(tr(g))), 2)
    mod_rows = agg(lambda e: [e["mod"]], lambda m: esc(tr(m)))
    ta_rows = agg(lambda e: [e["ta"]], lambda m: esc(tr(m)))
    last = [T(lang, "最近一次", "Latest")]
    desc = T(lang, f"临床试验为什么失败：{len(evs)} 次主要终点未达到或提前终止，按疗效、安全性、商业、入组、监管归类，并按靶点、药物形式和治疗领域汇总。立项前先看哪些路已经走不通。",
             f"Why clinical trials fail: {len(evs)} missed primary endpoints and early stops, classified as efficacy, safety, business, enrollment or regulatory, and summarised by target, modality and therapeutic area.")
    body = f"""<h1>{T(lang, "失败原因库", "Trial failure library")} <small>{len(evs)}</small></h1><p class="lead">{esc(desc)}</p>
{kpis([(len(evs), T(lang, "失败 / 终止", "Failures / stops")), (cnt[0], FAIL_LBL["eff"][L]), (cnt[1], FAIL_LBL["safe"][L]), (cnt[2], FAIL_LBL["biz"][L])])}
<p class="rel">{T(lang, "跳到：", "Jump to: ")}<a href="#by-target">{T(lang, "按靶点", "By target")}</a> · <a href="#by-mod">{T(lang, "按药物形式", "By modality")}</a> · <a href="#by-ta">{T(lang, "按治疗领域", "By therapeutic area")}</a> · <a href="#recent">{T(lang, "最近的失败", "Recent failures")}</a></p>
<h2 id="by-target">{T(lang, "按靶点", "By target")} <small>{len(tg_rows)}</small></h2><p class="sm">{T(lang, "至少 2 次失败或终止的靶点，按疗效 + 安全性失败次数排序。点靶点看每一次的明细。", "Targets with at least two failures or stops, sorted by efficacy plus safety failures. Click a target for each event.")}</p>
{table([T(lang, "靶点", "Target")] + head + last, tg_rows, "ftab")}
<h2 id="by-mod">{T(lang, "按药物形式", "By modality")}</h2>{table([T(lang, "药物形式", "Modality")] + head + last, mod_rows, "ftab")}
<h2 id="by-ta">{T(lang, "按治疗领域", "By therapeutic area")}</h2>{table([T(lang, "治疗领域", "Therapeutic area")] + head + last, ta_rows, "ftab")}
<h2 id="recent">{T(lang, "最近的失败", "Recent failures")}</h2>{table(fail_head(lang, True), fail_rows(S, lang, evs[:80], True))}
<p class="sm">{T(lang, "归类方法：注册库的终止理由先按关键词归成疗效 / 无效性、安全性、申办方决定 / 战略、资金、入组 / 运营、监管、其他；「其他 / 未填写」里原文写了安全性或无效性的再改归，「申办方决定」里写明是看了其他研究结果、期中分析或疗效数据才停的改归疗效不足。主要终点未达到按登记的统计结果判定。新闻稿只补注册库里没有的事件。「商业 / 战略」常常是申办方没说真实原因，不等于药物本身没问题。",
             "Method: registry stop reasons are keyword-classified into efficacy / futility, safety, sponsor decision / strategy, funding, enrollment / operations, regulatory and other; “other / not stated” entries whose text mentions safety or futility are reassigned, and “sponsor decision” stops that cite results of another study, an interim analysis or efficacy data are counted as efficacy. Missed primary endpoints come from the registered statistical results. Topline news only adds events not in the registry. “Business / strategy” often means the sponsor gave no real reason; it does not clear the drug.")}</p>"""
    return page(S, lang, "failures", "", T(lang, "临床试验失败原因库：按靶点、药物形式、治疗领域 | Hit or Miss", "Clinical trial failure library by target, modality and area | Hit or Miss"), desc, body,
                [(S.app(lang), "Hit or Miss"), (S.path(lang, "failures"), T(lang, "失败原因库", "Failure library"))])


def trial_verdict(t):
    if t.get("tgt_out") == "neg":
        return "未达到"
    v = (t.get("as") or {}).get("verdict")
    if v:
        return v
    return "终止" if t.get("_set") == "stopped" else ""


def trial_date(t):
    if t.get("_set") in ("active", "early"):
        return t.get("fp") or t.get("pcd") or ""
    return t.get("results") or (t.get("updated") if t.get("_set") == "stopped" else None) or t.get("pcd") or t.get("fp") or ""


def trial_row(S, lang, t, with_drug=True):
    tr = S.tr if lang == "en" else (lambda s: s)
    drugs = ", ".join(S.dlink(lang, c) for c in (t.get("_drugs") or [])[:3]) if with_drug else ""
    v = trial_verdict(t)
    stat = vbadge(S, lang, v) if v else esc(SETS.get(t["_set"], ("", ""))[0 if lang == "zh" else 1])
    cond = esc(cut(", ".join(t.get("conditions") or []), 60))
    r = [S.nlink(lang, t), esc(t.get("group") or t.get("sponsor") or "")]
    if with_drug:
        r.append(drugs or "—")
    return r + [esc(ph_lbl(lang, t.get("phase"))), cond, stat, esc(trial_date(t))]


def trial_head(lang, with_drug=True):
    h = [T(lang, "试验", "Trial"), T(lang, "公司", "Company")]
    if with_drug:
        h.append(T(lang, "药物", "Drug"))
    return h + [T(lang, "分期", "Phase"), T(lang, "适应症", "Condition"), T(lang, "状态 / 判定", "Status / call"),
                T(lang, "日期", "Date")]


def news_rows(S, lang, items):
    rows = []
    for x in sorted(items, key=lambda x: x.get("d") or "", reverse=True)[:40]:
        nums = "; ".join(f'{NUM_EN.get(n.get("k"), n.get("k", "")) if lang == "en" else n.get("k", "")} {n.get("v", "")}'.strip() for n in (x.get("nums") or [])[:4] if isinstance(n, dict))
        src = T(lang, "公司新闻稿", "Press release") if x.get("tier") == "pr" else T(lang, "媒体", "Media")
        rows.append([esc(x.get("d")), vbadge(S, lang, x.get("v")),
                     f'<a href="{esc(x.get("u"))}" rel="nofollow noopener" target="_blank">{esc(cut(x.get("t"), 140))}</a>'
                     + (f'<div class="sm">{esc(nums)}</div>' if nums else ""),
                     esc(f'{src} · {x.get("s") or ""}')])
    return rows


def cur_block(S, lang, items):
    if not items:
        return ""
    tr = S.tr if lang == "en" else (lambda s: s)
    out = []
    for c in sorted(items, key=lambda c: c.get("date") or "", reverse=True)[:12]:
        v = OUTV.get(c.get("out"), "")
        out.append(f'<article class="cur"><div class="sm">{esc(tr(c.get("disp") or c.get("date") or ""))} · {esc(c.get("sponsor"))} · '
                   f'{esc(tr(c.get("ind") or ""))}</div><h3>{vbadge(S, lang, v)} {S.dlink(lang, S.dcl(c.get("drug")) or "", c.get("drug"))} '
                   f'{esc(c.get("trial") or "")}</h3><p>{esc(tr(c.get("fact") or ""))}</p>'
                   f'<a class="sm" href="{S.app(lang, "c-" + c["id"])}">{T(lang, "看三种视角的点评 →", "Read the R&D, BD and clinician takes →")}</a></article>')
    return f'<h2>{T(lang, "精选解读", "Curated readouts")}</h2>' + "".join(out)


# ---------------- 分子对比表 ----------------
ROUTE_EN = {"口服": "Oral", "静脉": "IV", "皮下": "SC", "肌注": "IM", "吸入": "Inhaled", "外用": "Topical", "玻璃体内": "Intravitreal",
            "鞘内": "Intrathecal", "鼻用": "Nasal"}


def nm_txt(v):
    x = 10 ** (9 - v)
    return f"{x:.2g}" if x < 100 else f"{x:,.0f}"


def nk_txt(lang, bio):
    k = bio.get("k") or 0
    return T(lang, f" · {k} 次测定中位数", f" · median of {k}") if k > 1 else ""


def num_txt(lang, n):
    k, v = n.get("k", ""), n.get("v", "")
    if k == "HR":
        return f"HR {v}"
    if k == "p":
        return f"p{v}"
    if k in ("mPFS", "mOS"):
        return f"{k} {v} {T(lang, '个月', 'mo')}"
    return f"{NUM_EN.get(k, k) if lang == 'en' else k} {v}%"


def mol_img(lang, m, alt, svg=None):
    """svg：本站按骨架对齐画好的图（docs/mol/<靶点>/）；没有就用全站通用的本地图（docs/mol/s/，m["sh"]），
    再没有才用 PubChem 的图（有 CID 用 CID，否则按 SMILES 现画）。
    专利推测、供应商结构的加标注，链接到专利或供应商页面。"""
    if m.get("cid"):
        src = f'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{m["cid"]}/PNG?image_size=160x160'
        href = f'https://pubchem.ncbi.nlm.nih.gov/compound/{m["cid"]}'
    elif m.get("smi"):
        src = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/" + urllib.parse.quote(m["smi"], safe="") + "/PNG?image_size=160x160"
        href = ""
    else:
        return ""
    tag = ""
    if m.get("src") == "patent":
        pat = m.get("pat") or ""
        href = ("https://patents.google.com/patent/" + urllib.parse.quote(pat)) if pat else href
        tag = (f'<div class="sm" title="{esc(m.get("pwhy") or "")}">{T(lang, "专利推测", "Patent-inferred")}'
               + (f' · {esc(pat)}' if pat else "") + (f' {esc(m["pex"])}' if m.get("pex") else "") + "</div>")
    elif m.get("src") == "vendor":
        href = m.get("vurl") or href
        tag = f'<div class="sm" title="{esc(m.get("pwhy") or "")}">{T(lang, "供应商结构", "Vendor structure")} · {esc(m.get("vendor") or "")}</div>'
    svg = svg or (f'/mol/s/{m["sh"]}.svg' if m.get("sh") else None)   # 没有对齐图就用全站通用的本地图
    imgh = (f'<img class="mol mol-al" loading="lazy" width="120" height="100" alt="{esc(alt)}" src="{esc(svg)}">' if svg
            else f'<img class="mol" loading="lazy" width="80" height="80" alt="{esc(alt)}" src="{esc(src)}">')
    return (f'<a href="{esc(href)}" rel="noopener" target="_blank">{imgh}</a>' if href else imgh) + tag


def mol_section(S, lang, g, progs):
    D = S.mol.get("drugs") or {}
    FL = S.mol.get("freq_lbl") or {}
    SV = (S.mol.get("svg") or {}).get(g) or {}
    SM, SF = SV.get("m") or {}, SV.get("f") or {}
    rows, grp = [], []
    # 同一个分子可能用通用名和研发代号各算一个项目（Atirmociclib / PF-07220060），按 ChEMBL ID、CID 或 SMILES 并成一行
    plan, seen, seen_nm = [], {}, {}
    for p in progs:
        ks = list(S.dinfo[p["drug"]]["keys"]) if p["drug"] in S.dinfo else []
        for t in p["trials"]:
            for e in t.get("tgm") or []:
                if e.get("g") == g and e.get("n"):
                    ks += dkeys(e["n"])
        k = next((k for k in ks if k in D), None)
        if not k:
            continue
        ident = D[k].get("ch") or D[k].get("cid") or D[k].get("smi") or k
        nm = re.sub(r"[^a-z0-9]", "", ((_core_names(p["name"]) or [p["name"]])[0]).lower())
        ident = seen_nm.get(nm, ident)   # 药名一样（一个有结构、一个只有给药信息）也并成一行
        if ident in seen:
            x = seen[ident]
            x["ks"] += ks
            # 只记干净的药名（去掉剂量、剂型、联用部分），和主名一样的不记
            al = (_core_names(p["name"]) or [p["name"]])[0]
            if re.sub(r"[^a-z0-9]", "", al.lower()) not in x["seen"]:
                x["seen"].add(re.sub(r"[^a-z0-9]", "", al.lower()))
                x["aka"].append(al)
            continue
        seen_nm.setdefault(nm, ident)
        seen[ident] = {"p": p, "k": k, "ks": ks, "aka": [],
                       "seen": {re.sub(r"[^a-z0-9]", "", ((_core_names(p["name"]) or [p["name"]])[0]).lower())}}
        plan.append(seen[ident])
    for x in plan:
        p, k, ks = x["p"], x["k"], x["ks"]
        m = D[k]
        kset = set(ks)
        news = sorted([x for x in S.news if x.get("nums") and set(dkeys(x.get("drug"))) & kset], key=lambda x: x.get("d") or "", reverse=True)
        cov = {1: T(lang, "共价", "Covalent"), 2: T(lang, "可能共价", "Likely covalent")}.get(m.get("cov"), "")
        pr = m.get("p") or {}
        phys = " · ".join(x for x in (f"MW {m['mw']}" if m.get("mw") else "", f"cLogP {pr['alogp']}" if pr.get("alogp") is not None else "",
                                      f"TPSA {pr['psa']}" if pr.get("psa") is not None else "") if x)
        route = " / ".join((ROUTE_EN.get(r, r) if lang == "en" else r) for r in m.get("route") or [])
        freq = " / ".join((FL.get(f, [f, f])[0 if lang == "zh" else 1]) for f in m.get("freq") or [])
        dose = ", ".join(m.get("dose") or [])
        bio, cell, sel = m.get("bio"), m.get("cell"), m.get("sel")
        svg = f'/mol/{SV["d"]}/{SF.get(k, k)}.svg' if k in SM else None
        grp.append(SM.get(k, 0))
        img = mol_img(lang, m, p["name"], svg)
        drug = (S.dlink(lang, p["drug"]) if p["drug"] else esc(p["name"])) \
            + (f'<div class="sm">{T(lang, "又名 ", "aka ")}{esc(", ".join(x["aka"][:3]))}</div>' if x["aka"] else "") + f'<div class="sm">{esc(", ".join(c for c, _ in p["cos"].most_common(1) if c))} · {esc(ph_lbl(lang, p["ph"]))}</div>' \
            + (f'<span class="v {"neg" if m.get("cov") == 1 else "mix"}">{cov}</span>' if cov else "")
        rows.append([img, drug, esc(m.get("moa") or "—"),
                     (f'<b>{esc(bio.get("ty") or "")} {nm_txt(bio["v"])} nM</b><div class="sm">{esc(bio.get("n") or "")}{nk_txt(lang, bio)}</div>' if bio else "—")
                     + (f'<div class="sm">{T(lang, "细胞", "Cell")} {nm_txt(cell["v"])} nM · {esc(cell.get("n") or "")}</div>' if cell else ""),
                     (f'{sel["off"]} <span class="sm">/ {T(lang, "测过", "tested")} {sel["tested"]}</span>' if sel else "—"),
                     f'<span class="sm">{esc(phys) or "—"}</span>',
                     f'<span class="sm">{esc(" · ".join(x for x in (route, freq) if x)) or "—"}{"<br>" + esc(dose) if dose else ""}</span>',
                     (f'<span class="sm">{esc(" · ".join(num_txt(lang, n) for n in news[0]["nums"][:3]))}<br>{esc(news[0].get("d"))}</span>' if news else "—")])
    if not rows:
        return ""
    # 按骨架分组排：同组的挨在一起（组内保持原来的顺序），每组前加一行说明；单独成组的放最后
    gi = {a: (b, c) for a, b, c in SV.get("g") or []}
    if gi:
        out, cur = [], None
        for gid, r in sorted(zip(grp, rows), key=lambda x: (x[0] == 0, x[0])):
            if gid != cur:
                cur = gid
                if gid:
                    n, nc = gi.get(gid, (0, 0))
                    lbl = chr(64 + gid) if gid <= 26 else str(gid)
                    out.append(f'<tr class="grp"><td colspan="8">{T(lang, f"骨架 {lbl} · {n} 个分子共用 {nc} 个重原子的骨架", f"Scaffold {lbl} · {n} molecules share a {nc}-atom core")}</td></tr>')
                else:
                    out.append(f'<tr class="grp"><td colspan="8">{T(lang, "其他结构", "Other scaffolds")}</td></tr>')
            out.append(r)
        rows = out
    head = [T(lang, "结构", "Structure"), T(lang, "药物", "Drug"), T(lang, "机制", "Mechanism"), T(lang, "活性", "Potency"),
            T(lang, "选择性 ≤1 µM", "Off-targets ≤1 µM"), T(lang, "理化", "Physchem"), T(lang, "给药", "Dosing"), T(lang, "最新疗效数字", "Latest efficacy")]
    note = T(lang, "结构按化学骨架分组，同组分子的公共骨架摆成同一朝向，橙色底色是和同组其他分子不同的部分（取代基或换了元素的原子）。结构来自 PubChem（少数研发代号没有公开结构，用专利里最可能的化合物或试剂供应商给出的结构，分别标「专利推测」「供应商结构」，都未经公司确认）；机制、活性和理化性质来自 ChEMBL（活性是主靶点上各次测定 pChEMBL 的中位数，换算成 nM，选择性是除主靶点外 ≤1 µM 的人源单一蛋白个数，只含已发表数据）；给药方案从注册库干预描述里抽取；「可能共价」按结构里的弹头判断。",
             "Structures are grouped by scaffold: molecules in a group share the same orientation of their common core, and orange shading marks what differs (substituents or swapped atoms). Structures from PubChem (a few undisclosed codes show the most likely patent compound or a reagent vendor’s structure, marked “patent-inferred” or “vendor structure”, neither confirmed by the company); mechanism, potency and physchem from ChEMBL (median pChEMBL on the primary target as nM; off-targets are other human single proteins at ≤1 µM, published data only); dosing parsed from registry intervention text; “likely covalent” inferred from a warhead in the structure.")
    return (f'<h2>{T(lang, "分子对比", "Molecule comparison")} <small>{len(rows)}</small></h2>'
            f'<p>{T(lang, f"{g} 上各家分子的结构、机制、活性、选择性、理化性质、给药方案和最新疗效数字。", f"Competing {S.tr(g)} molecules: structure, mechanism, potency, selectivity, physchem, dosing and latest efficacy.")}</p>'
            + table(head, rows, "moltab") + f'<p class="sm">{note}</p>')


# ---------------- 靶点页 ----------------
def target_page(S, lang, g):
    x = S.tinfo[g]
    tr = S.tr if lang == "en" else (lambda s: s)
    gn = tr(g)
    progs = x["progs"]
    cos = {c for p in progs for c in p["cos"] if c}
    maxp = max((p["ph"] for p in progs), key=phn, default="")
    new12 = [p for p in progs if p["fp"] >= S.cut12 and p["fp"] != "9999"]
    res = [t for t in x["trials"] if t["_set"] == "results"]
    hit = sum(1 for t in res if trial_verdict(t) == "达到") + sum(1 for n in x["news"] if n.get("v") == "达到")
    miss = sum(1 for t in res if trial_verdict(t) == "未达到") + sum(1 for n in x["news"] if n.get("v") in ("未达到",))
    stop = [t for t in x["trials"] if t["_set"] == "stopped"]
    up = sorted([t for t in x["trials"] if t["_set"] in ("upcoming", "completed") and (t.get("pcd") or "") <= S.h6],
                key=lambda t: t.get("pcd") or "")
    mods = collections.Counter()
    for p in progs:
        if p["mods"]:
            mods[p["mods"].most_common(1)[0][0]] += 1
    tas = collections.Counter(t.get("ta") for t in x["trials"] if t.get("ta"))
    al = [a for a in S.alias.get(g, []) if a.lower() != g.lower()][:12]
    known = S.known.get(g, [])[:16]

    modtxt = T(lang, "、", ", ").join(f"{tr(m)} {n}" + T(lang, " 个", "") for m, n in mods.most_common(4))
    if lang == "zh":
        s = [f"截至 {S.asof}，本站收录靶向 {g} 的临床项目 {len(progs)} 个，来自 {len(cos)} 家公司，最高推进到 {ph_lbl(lang, maxp)}。"]
        if new12:
            s.append(f"近 12 个月新进 {len(new12)} 个项目。")
        if modtxt:
            s.append(f"按药物形式：{modtxt}。")
        if hit or miss:
            s.append(f"已有读出中 {hit} 项达到主要终点、{miss} 项未达到。")
        if stop:
            s.append(f"{len(stop)} 项试验提前终止。")
        if up:
            s.append(f"未来半年有 {len(up)} 项试验到达主要完成日。")
    else:
        s = [f"As of {S.asof}, the site tracks {pl(len(progs), 'clinical program')} against {gn} from {pl(len(cos), 'company', 'companies')}; the furthest has reached {ph_lbl(lang, maxp).lower()}."]
        if new12:
            s.append(f"{pl(len(new12), 'program')} entered the clinic in the last 12 months.")
        if modtxt:
            s.append(f"By modality: {modtxt}.")
        if hit or miss:
            s.append(f"Of the readouts so far, {hit} met the primary endpoint and {miss} missed.")
        if stop:
            s.append(f"{pl(len(stop), 'trial')} {'was' if len(stop) == 1 else 'were'} stopped early.")
        if up:
            s.append(f"{pl(len(up), 'trial')} {'reaches' if len(up) == 1 else 'reach'} primary completion in the next six months.")
    summary = " ".join(s)

    prow = []
    for p in progs:
        lt = max(p["trials"], key=lambda t: (phn(t.get("phase")), t.get("fp") or ""))
        nm = S.dlink(lang, p["drug"]) if p["drug"] else esc(p["name"] or T(lang, "（未注明药名）", "(drug not named)"))
        m = p["mods"].most_common(1)[0][0] if p["mods"] else ""
        prow.append([nm, esc(", ".join(c for c, _ in p["cos"].most_common(2) if c)), esc(tr(m)), esc(ph_lbl(lang, p["ph"])),
                     str(len(p["trials"])), S.nlink(lang, lt, lt.get("acronym") or lt["nct"])])
    readouts = sorted([t for t in x["trials"] if trial_verdict(t) and t["_set"] in ("results", "stopped")],
                      key=lambda t: trial_date(t), reverse=True)

    co = collections.Counter()
    for t in x["trials"]:
        for h in t.get("tg") or []:
            if h != g and h in S.tslug:
                co[h] += 1
    rel = [h for h, _ in co.most_common(10)]
    if len(rel) < 6 and tas:
        top_ta = tas.most_common(1)[0][0]
        for h in sorted(S.tinfo, key=lambda h: -len(S.tinfo[h]["progs"])):
            if h != g and h not in rel and any(t.get("ta") == top_ta for t in S.tinfo[h]["trials"][:20]):
                rel.append(h)
            if len(rel) >= 10:
                break

    body = f"""<h1>{esc(gn)} <small>{T(lang, "靶点：临床管线与试验读出", "drugs in clinical trials: pipeline and readouts")}</small></h1>
{f'<p class="alias">{T(lang, "别名：", "Also known as: ")}{esc(" · ".join(al))}</p>' if al else ""}
{f'<p class="alias">{T(lang, "已知药物：", "Known drugs: ")}{" · ".join(S.dlink(lang, S.dcl(k) or "", k) for k in known)}</p>' if known else ""}
<p class="tags">{"".join(f'<span class="tag">{esc(tr(a))}</span>' for a, _ in tas.most_common(4))}</p>
{kpis([(len(progs), T(lang, "临床项目", "Programs")), (len(cos), T(lang, "公司", "Companies")), (ph_lbl(lang, maxp), T(lang, "最高阶段", "Furthest phase")),
       (len(new12), T(lang, "近 12 个月新进", "New in 12 months")), (f"{hit} / {miss}", T(lang, "读出 成 / 败", "Readouts hit / miss"))])}
<p class="lead">{esc(summary)}</p>
<p><a class="btn" href="{S.app(lang, "target/" + quote(g, safe=""))}">{T(lang, "在交互版里看专利、文献、新闻和交易 →", "Open in the app for patents, literature, news and deals →")}</a></p>
<h2>{T(lang, "临床项目", "Clinical programs")} <small>{len(progs)}</small></h2>
{table([T(lang, "药物", "Drug"), T(lang, "公司", "Company"), T(lang, "药物形式", "Modality"), T(lang, "最高阶段", "Furthest phase"),
        T(lang, "试验数", "Trials"), T(lang, "代表试验", "Lead trial")], prow)}
{mol_section(S, lang, g, progs)}
{f'<h2>{T(lang, "试验读出与终止", "Readouts and stopped trials")} <small>{len(readouts)}</small></h2>' + table(trial_head(lang), [trial_row(S, lang, t) for t in readouts[:80]]) if readouts else ""}
{fail_section(S, lang, g)}
{f'<h2>{T(lang, "新闻稿读出", "Topline news")}</h2>' + table([T(lang, "日期", "Date"), T(lang, "判定", "Call"), T(lang, "标题", "Headline"), T(lang, "来源", "Source")], news_rows(S, lang, x["news"])) if x["news"] else ""}
{f'<h2>{T(lang, "未来半年到达主要完成日", "Primary completion in the next six months")} <small>{len(up)}</small></h2>' + table(trial_head(lang), [trial_row(S, lang, t) for t in up[:60]]) if up else ""}
{cur_block(S, lang, x["cur"])}
{tax_block(S, lang, g)}
{f'<h2>{T(lang, "常在同一试验里出现的靶点", "Often in the same trials")}</h2><p class="rel">' + " · ".join(S.tlink(lang, h) for h in rel) + "</p>" if rel else ""}
"""
    title = T(lang, f"{g} 靶点临床管线：{len(progs)} 个项目、{len(cos)} 家公司 | Hit or Miss",
              f"{gn} drugs in clinical trials: {len(progs)} programs, {len(cos)} companies | Hit or Miss")
    crumbs = [(S.app(lang), "Hit or Miss"), (S.path(lang, "targets"), T(lang, "靶点", "Targets")), (S.path(lang, "target", S.tslug[g]), gn)]
    return page(S, lang, "target", S.tslug[g], title, summary, body, crumbs)


# ---------------- 药物页 ----------------
def drug_page(S, lang, c):
    x = S.dinfo[c]
    tr = S.tr if lang == "en" else (lambda s: s)
    name, trials = x["name"], x["trials"]
    tgs = collections.Counter()
    for t in trials:
        for e in t.get("tgm") or []:
            if e.get("n") and S.dcl(e["n"]) == c and e.get("g") in S.tslug:
                tgs[e["g"]] += 2 if len(t.get("_drugs") or []) == 1 else 1
    for n in x["news"]:
        for g in n.get("tg") or []:
            if g in S.tslug:
                tgs[g] += 1
    for cu in x["cur"]:
        for g in cu.get("tg") or []:
            if g in S.tslug:
                tgs[g] += 3
    tgl = [g for g, _ in tgs.most_common(4)]
    solo = [t for t in trials if len(t.get("_drugs") or []) == 1] or trials
    cos = collections.Counter(t.get("group") or t.get("sponsor") for t in solo if t.get("group") or t.get("sponsor"))
    for n in x["news"]:
        if n.get("co"):
            cos[n["co"]] += 1
    mods = collections.Counter()
    for t in solo:
        for iv in t.get("iv") or []:
            if S.dcl(iv.get("n")) == c and iv.get("m") and iv["m"] != "未识别":
                mods[iv["m"]] += 1
    for n in x["news"]:
        if n.get("mod") and n["mod"] != "未识别":
            mods[n["mod"]] += 1
    mod = mods.most_common(1)[0][0] if mods else ""
    maxp = max((t.get("phase") for t in trials), key=phn, default="")
    hit = sum(1 for t in trials if trial_verdict(t) == "达到") + sum(1 for n in x["news"] if n.get("v") == "达到")
    miss = sum(1 for t in trials if trial_verdict(t) in ("未达到",)) + sum(1 for n in x["news"] if n.get("v") in ("未达到", "终止"))
    stop = sum(1 for t in trials if t["_set"] == "stopped")
    conds = collections.Counter(cd for t in trials for cd in (t.get("conditions") or [])[:1])
    alt = sorted({main_name(iv["n"]) for t in trials for iv in t.get("iv") or [] if S.dcl(iv.get("n")) == c} - {name})[:6]
    st = next((S.struct[k] for k in x["keys"] if k in S.struct), None)

    cotxt = T(lang, "、", ", ").join(cc for cc, _ in cos.most_common(3))
    if lang == "zh":
        s = [f"{name}" + (f"（{cotxt}）" if cotxt else "") + (f"是靶向 {'、'.join(tgl)} 的{tr(mod) if mod else ''}药物" if tgl else (f"是一款{mod}药物" if mod else "")) + "。"]
        s.append(f"截至 {S.asof}，本站收录它的注册库试验 {len(trials)} 项，最高推进到 {ph_lbl(lang, maxp)}。")
        if hit or miss:
            s.append(f"已有读出中 {hit} 项达到主要终点、{miss} 项未达到或终止。")
        elif stop:
            s.append(f"{stop} 项试验提前终止。")
        if conds:
            s.append("主要适应症：" + "、".join(k for k, _ in conds.most_common(3)) + "。")
        if x["guide"]:
            s.append(f"公司给出的读出指引 {len(x['guide'])} 条。")
    else:
        s = [f"{name}" + (f" ({cotxt})" if cotxt else "") + (f" is a {tr(mod).lower() if mod else ''} drug targeting {', '.join(tr(g) for g in tgl)}" if tgl else (f" is a {tr(mod).lower()} drug" if mod else "")) + "."]
        s.append(f"As of {S.asof}, the site tracks {pl(len(trials), 'registry trial')} of it; the furthest has reached {ph_lbl(lang, maxp).lower()}.")
        if hit or miss:
            s.append(f"Of the readouts so far, {hit} met the primary endpoint and {miss} missed or were stopped.")
        elif stop:
            s.append(f"{pl(stop, 'trial')} {'was' if stop == 1 else 'were'} stopped early.")
        if conds:
            s.append("Main conditions: " + ", ".join(k for k, _ in conds.most_common(3)) + ".")
        if x["guide"]:
            s.append(f"{len(x['guide'])} company readout guidance items.")
    summary = re.sub(r"\s+", " ", " ".join(s)).replace(" .", ".")

    ev = []
    for t in trials:
        lbl = S.nlink(lang, t)
        sname = SETS.get(t["_set"], ("", ""))[0 if lang == "zh" else 1]
        v = trial_verdict(t)
        ev.append((trial_date(t), t.get("phase"), (vbadge(S, lang, v) + " " if v else f'<span class="v">{esc(sname)}</span> ') + lbl,
                   esc(" · ".join(x for x in (t.get("group") or t.get("sponsor"), cut((t.get("conditions") or [""])[0], 60)) if x))))
    for n in x["news"]:
        ev.append((n.get("d"), n.get("ph"), vbadge(S, lang, n.get("v")) + f' <a href="{esc(n.get("u"))}" rel="nofollow noopener" target="_blank">{esc(cut(n.get("t"), 130))}</a>',
                   esc(f'{T(lang, "公司新闻稿", "Press release") if n.get("tier") == "pr" else T(lang, "媒体", "Media")} · {n.get("s") or ""}')))
    for cu in x["cur"]:
        ev.append((cu.get("date"), "", vbadge(S, lang, OUTV.get(cu.get("out"), "")) + f' <a href="{S.app(lang, "c-" + cu["id"])}">{esc(cu.get("trial") or "")}</a>',
                   esc(T(lang, "精选解读", "Curated") + " · " + tr(cu.get("ind") or ""))))
    for gd in x["guide"]:
        ev.append((gd.get("start") or gd.get("d"), gd.get("ph"), f'<span class="v mix">{T(lang, "预计读出", "Readout due")} {esc(gd.get("when"))}</span> “{esc(cut(gd.get("snip"), 120))}”',
                   f'<a href="{esc(gd.get("u"))}" rel="nofollow noopener" target="_blank">{esc(gd.get("s") or T(lang, "来源", "Source"))}</a>'))
    ev.sort(key=lambda e: str(e[0] or ""), reverse=True)
    rows = [[esc(d or "—"), esc(ph_lbl(lang, p) if p else ""), h, sub] for d, p, h, sub in ev[:200]]

    others = collections.Counter()
    for g in tgl[:2]:
        for p in S.tinfo[g]["progs"]:
            if p["drug"] and p["drug"] != c and p["drug"] in S.dpage:
                others[p["drug"]] += 10 * phn(p["ph"]) + len(p["trials"])
    rel = [d for d, _ in others.most_common(12)]

    body = f"""<div class="dh">{(f'<img class="mol" alt="{esc(name)}" loading="lazy" width="180" height="150" src="/mol/s/{st[4]}.svg">' if len(st) > 4 and st[4] else f'<img class="mol" alt="{esc(name)}" loading="lazy" width="150" height="150" src="https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{st[0]}/PNG?image_size=300x300">' if st[0] else "") if st else ""}<div>
<h1>{esc(name)} <small>{T(lang, "临床试验、读出与时间线", "clinical trials, results and timeline")}</small></h1>
{f'<p class="alias">{T(lang, "其他写法：", "Also listed as: ")}{esc(" · ".join(alt))}</p>' if alt else ""}
<p class="tags">{f'<span class="tag">{esc(tr(mod))}</span>' if mod else ""}{"".join(f'<span class="tag">{T(lang, "靶点", "Target")} {S.tlink(lang, g)}</span>' for g in tgl)}{"".join(f'<span class="tag">{esc(cc)}</span>' for cc, _ in cos.most_common(3))}</p>
{f'<p class="sm">SMILES <code>{esc(cut(st[1], 160))}</code>{" · MW " + esc(st[2]) if len(st) > 2 and st[2] else ""}</p>' if st else ""}
</div></div>
{kpis([(len(trials), T(lang, "注册库试验", "Registry trials")), (len(x["news"]), T(lang, "新闻稿读出", "Topline news")),
       (f"{hit} / {miss}", T(lang, "成 / 败", "Hit / miss")), (ph_lbl(lang, maxp), T(lang, "最高阶段", "Furthest phase"))])}
<p class="lead">{esc(summary)}</p>
<p><a class="btn" href="{S.app(lang, "d-" + c)}">{T(lang, "在交互版里打开药物时间线 →", "Open the drug timeline in the app →")}</a></p>
<h2>{T(lang, "时间线", "Timeline")} <small>{T(lang, "从新到旧", "newest first")}</small></h2>
{table([T(lang, "日期", "Date"), T(lang, "分期", "Phase"), T(lang, "事件", "Event"), T(lang, "详情", "Details")], rows)}
{f'<p class="sm">{T(lang, f"只列出最近 200 条，共 {len(ev)} 条。", f"Showing the latest 200 of {len(ev)}.")}</p>' if len(ev) > 200 else ""}
{f'<h2>{T(lang, "同靶点的其他药物", "Other drugs on the same target")}</h2><p class="rel">' + " · ".join(S.dlink(lang, d) for d in rel) + "</p>" if rel else ""}
<p class="sm">{T(lang, "按药名和研发代号匹配注册库试验、新闻稿和公司指引；同名不同药或改名的情况可能漏掉或混入，引用前请核对原始来源。",
                 "Matched on drug name and code across registry trials, press releases and company guidance; renamed or similarly named drugs may be missed or mixed in, so check the original sources before citing.")}</p>
"""
    title = T(lang, f"{name} 临床试验与结果：{len(trials)} 项试验，最高 {ph_lbl(lang, maxp)} | Hit or Miss",
              f"{name} clinical trials and results: {len(trials)} trials, {ph_lbl(lang, maxp)} | Hit or Miss")
    crumbs = [(S.app(lang), "Hit or Miss"), (S.path(lang, "drugs"), T(lang, "药物", "Drugs")), (S.path(lang, "drug", c), name)]
    ld = {"@context": "https://schema.org", "@type": "Drug", "name": name, "url": S.abs(S.path(lang, "drug", c))}
    if alt:
        ld["alternateName"] = alt
    return page(S, lang, "drug", c, title, summary, body, crumbs, ld)


# ---------------- 试验页 ----------------
def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3g}" if abs(v) < 1000 else f"{v:,.0f}"
    return str(v)


def trial_page(S, lang, t):
    tr = S.tr if lang == "en" else (lambda s: s)
    nct, lbl = t["nct"], t.get("acronym") or cut(t.get("title"), 80)
    drugs = t.get("_drugs") or []
    dname = S.dinfo[drugs[0]]["name"] if drugs else ""
    v = trial_verdict(t)
    a = t.get("as") or {}
    dt = t.get("dt") or {}
    cond = t.get("conditions") or []
    grp = t.get("group") or t.get("sponsor") or ""
    sname = SETS.get(t["_set"], ("", ""))[0 if lang == "zh" else 1]

    facts = [(T(lang, "注册号", "Registry ID"), f'<a href="https://clinicaltrials.gov/study/{nct}" rel="noopener" target="_blank">{nct}</a>'),
             (T(lang, "申办方", "Sponsor"), esc(t.get("sponsor")) + (f' <span class="sm">（{esc(grp)}）</span>' if grp and grp != t.get("sponsor") else "")),
             (T(lang, "分期", "Phase"), esc(ph_lbl(lang, t.get("phase")))), (T(lang, "状态", "Status"), esc(st_lbl(lang, t.get("status")))),
             (T(lang, "入组人数", "Enrollment"), esc(t.get("n") or "—")), (T(lang, "开始日期", "Start date"), esc(t.get("fp") or "—")),
             (T(lang, "主要完成日", "Primary completion"), esc(t.get("pcd") or "—"))]
    if t.get("results"):
        facts.append((T(lang, "结果公布", "Results posted"), esc(t["results"])))
    facts += [(T(lang, "适应症", "Conditions"), esc("; ".join(cond[:4]))),
              (T(lang, "受试药", "Interventions"), ", ".join(S.dlink(lang, S.dcl(iv["n"]), main_name(iv["n"])) if S.dcl(iv["n"]) in S.dpage else esc(iv["n"])
                                                        for iv in (t.get("iv") or [])[:6])),
              (T(lang, "靶点", "Targets"), " · ".join(S.tlink(lang, g) for g in t.get("tg") or []) or "—"),
              (T(lang, "药物形式", "Modality"), esc(tr(t.get("mod") or ""))), (T(lang, "治疗领域", "Therapeutic area"), esc(tr(t.get("ta") or "")))]
    if dt.get("alloc") or dt.get("mask"):
        facts.append((T(lang, "设计", "Design"), esc(" · ".join(x for x in (dt.get("alloc"), dt.get("model"), dt.get("mask")) if x and x != "NA").replace("_", " ").lower())))

    prim = []
    for pr in (dt.get("prim") or [])[:3]:
        gs = pr.get("groups") or []
        an = pr.get("an") or []
        rows = [[esc(cut(g.get("t"), 60)), esc(fmt(g.get("v"))) + (f' <span class="sm">({fmt(g.get("lo"))}–{fmt(g.get("hi"))})</span>' if g.get("lo") is not None else ""),
                 esc(fmt(g.get("n")))] for g in gs[:8]]
        arow = [esc(f'{a_.get("pt") or T(lang, "效应量", "Estimate")} {fmt(a_.get("est"))}'
                    + (f' (95% CI {fmt(a_.get("lo"))}–{fmt(a_.get("hi"))})' if a_.get("lo") is not None else "")
                    + (f', p = {fmt(a_.get("p"))}' if a_.get("p") is not None else "")) for a_ in an[:3] if a_.get("est") is not None or a_.get("p") is not None]
        prim.append(f'<h3>{esc(pr.get("title"))}</h3><p class="sm">{esc(pr.get("tf") or "")}{" · " + esc(pr.get("unit")) if pr.get("unit") else ""}</p>'
                    + table([T(lang, "组别", "Arm"), T(lang, "数值", "Value"), "N"], rows)
                    + ("<ul>" + "".join(f"<li>{x}</li>" for x in arow) + "</ul>" if arow else ""))
    if not prim and t.get("primary"):
        pv = {p.get("title"): p.get("p") for p in t.get("pvals") or [] if isinstance(p, dict)}
        prim.append("<ul>" + "".join(f'<li>{esc(p)}{f" · p = {fmt(pv[p])}" if pv.get(p) is not None else ""}</li>' for p in t["primary"][:4]) + "</ul>")
    sae = [[esc(cut(s.get("t"), 60)), esc(f'{s.get("s")}/{s.get("r")}' + (f' ({100 * s["s"] / s["r"]:.0f}%)' if s.get("r") else "")),
            esc(s.get("d") if s.get("d") is not None else "—")] for s in (dt.get("sae") or [])[:8]]

    same_tg = []
    for g in (t.get("tg") or [])[:2]:
        for u in S.tinfo.get(g, {}).get("trials", []):
            if u["nct"] != nct and u["nct"] in S.main and u not in same_tg:
                same_tg.append(u)
    same_tg.sort(key=lambda u: (trial_verdict(u) == "", -phn(u.get("phase")), trial_date(u)), reverse=False)
    same_co = [u for u in S.trials if u["nct"] in S.main and u["nct"] != nct and (u.get("group") or u.get("sponsor")) == grp and u not in same_tg][:8]

    if lang == "zh":
        desc = f"{grp} 的 {dname + ' ' if dname else ''}{ph_lbl(lang, t.get('phase'))}试验 {lbl}（{nct}）" + (f"，适应症：{cut(', '.join(cond[:2]), 60)}" if cond else "") + "。" \
            + (f"判定：{v}。" if v else f"{sname}。") + (cut(a["ev"][0], 90) if a.get("ev") else "")
    else:
        desc = f"{lbl} ({nct}): {grp}'s {ph_lbl(lang, t.get('phase')).lower()} trial{' of ' + dname if dname else ''}" + (f" in {cut(', '.join(cond[:2]), 60)}" if cond else "") + ". " \
            + (f"Call: {tr(v)}. " if v else f"{sname}. ") + (cut(tr(a["ev"][0]), 90) if a.get("ev") and not CJK.search(tr(a["ev"][0])) else "")

    evs = [tr(e) for e in a.get("ev") or []]
    whys = [tr(w) for w in a.get("why") or []]
    note = tr(t.get("note") or "")
    if lang == "en":
        evs = [e for e in evs if not CJK.search(e)]
        whys = [w for w in whys if not CJK.search(w)]
        note = "" if CJK.search(note) else note
    body = f"""<p class="sm">{esc(grp)} · {esc(ph_lbl(lang, t.get("phase")))} · {esc(tr(t.get("ta") or ""))}</p>
<h1>{esc(lbl)} <small>{nct}</small></h1>
<p class="sub">{esc(t.get("title"))}</p>
<p class="verdict">{vbadge(S, lang, v) if v else f'<span class="v">{esc(sname)}</span>'}</p>
{("<ul class='ev'>" + "".join(f"<li>{esc(e)}</li>" for e in evs) + "</ul>") if evs else ""}
{(f'<h2>{T(lang, "可能原因", "Likely reasons")}</h2><ul>' + "".join(f"<li>{esc(w)}</li>" for w in whys) + "</ul>") if whys else ""}
{(f'<h2>{T(lang, "编辑分析", "Editor’s analysis")}</h2><p class="lead">{esc(note)}</p>') if note else ""}
{(f'<h2>{T(lang, "终止原因", "Why it stopped")}</h2><p>{esc(tr(t.get("why_cat") or ""))}' + (f' · “{esc(cut(t.get("why"), 300))}”' if t.get("why") else "") + "</p>") if t.get("why") or t.get("why_cat") else ""}
<h2>{T(lang, "基本信息", "Key facts")}</h2>
<dl class="facts">{"".join(f"<dt>{k}</dt><dd>{v_}</dd>" for k, v_ in facts)}</dl>
{(f'<h2>{T(lang, "主要终点", "Primary endpoints")}</h2>' + "".join(prim)) if prim else ""}
{(f'<h2>{T(lang, "严重不良事件", "Serious adverse events")}</h2>' + table([T(lang, "组别", "Arm"), T(lang, "发生 / 风险人数", "Affected / at risk"), T(lang, "死亡", "Deaths")], sae)) if sae else ""}
<p><a class="btn" href="{S.app(lang, "t-" + nct)}">{T(lang, "在交互版里打开 →", "Open in the app →")}</a> <a class="btn ghost" href="https://clinicaltrials.gov/study/{nct}" rel="noopener" target="_blank">ClinicalTrials.gov →</a></p>
{(f'<h2>{T(lang, "同靶点的其他试验", "Other trials on the same target")}</h2>' + table(trial_head(lang), [trial_row(S, lang, u) for u in same_tg[:12]])) if same_tg else ""}
{(f'<h2>{T(lang, f"{grp} 的其他试验", f"Other trials by {grp}")}</h2>' + table(trial_head(lang), [trial_row(S, lang, u) for u in same_co])) if same_co else ""}
"""
    title = T(lang, f"{lbl}（{nct}）{dname + ' ' if dname else ''}{ph_lbl(lang, t.get('phase'))}试验结果{'：' + v if v else ''} | Hit or Miss",
              f"{lbl} ({nct}){': ' + dname if dname else ''} {ph_lbl(lang, t.get('phase'))} results{' — ' + tr(v) if v else ''} | Hit or Miss")
    crumbs = [(S.app(lang), "Hit or Miss"), (S.path(lang, "trials"), T(lang, "试验", "Trials")), (S.path(lang, "trial", nct), lbl)]
    ld = {"@context": "https://schema.org", "@type": "MedicalTrial", "name": t.get("title"), "identifier": nct,
          "url": S.abs(S.path(lang, "trial", nct)), "sponsor": {"@type": "Organization", "name": t.get("sponsor")}}
    if cond:
        ld["healthCondition"] = [{"@type": "MedicalCondition", "name": c_} for c_ in cond[:3]]
    if t.get("phase"):
        ld["phase"] = f"Phase {t['phase']}"
    return page(S, lang, "trial", nct, title, desc, body, crumbs, ld)


# ---------------- 索引页 ----------------
def tax_name(lang, x):
    return x["en"] if lang == "en" else x["zh"]


def pathway_chain(S, lang, pw, cur=None):
    """通路画成一行：阶段之间用 →，同阶段并列用 /，当前靶点加粗。"""
    def one(g):
        return f"<b>{esc(S.tr(g) if lang == 'en' else g)}</b>" if g == cur else S.tlink(lang, g)
    return ' <span class="arr">→</span> '.join('<span class="stg">' + " / ".join(one(g) for g in st) + "</span>" for st in pw["steps"])


def tax_block(S, lang, g):
    """靶点页上的「分类与通路」：类别 › 家族、同家族靶点、所在通路的上下游，以及配体–受体、合成致死等直接关系。"""
    out = []
    if g in S.tax_of:
        c, f = S.tax_of[g]
        peers = [h for h in S.fam_members[f["id"]] if h != g]
        fam = tax_name(lang, f) if tax_name(lang, f) != tax_name(lang, c) else ""
        href = S.path(lang, "targets") + "#c-" + c["id"]
        out.append(f'<p><b>{T(lang, "分类", "Class")}</b>{T(lang, "：", ": ")}<a href="{href}">{esc(tax_name(lang, c))}</a>{" › " + esc(fam) if fam else ""}'
                   + (f'<br><span class="sm">{T(lang, "同家族", "Same family")}{T(lang, "：", ": ")}</span>' + " · ".join(S.tlink(lang, h) for h in peers) if peers else "") + "</p>")
    for pw, i in S.paths_of.get(g, []):
        up = pw["steps"][i - 1] if i > 0 else []
        dn = pw["steps"][i + 1] if i + 1 < len(pw["steps"]) else []
        pos = []
        if up:
            pos.append(T(lang, "上游 ", "upstream ") + " / ".join(S.tlink(lang, h) for h in up))
        if dn:
            pos.append(T(lang, "下游 ", "downstream ") + " / ".join(S.tlink(lang, h) for h in dn))
        out.append(f'<div class="pw"><b><a href="{S.path(lang, "targets")}#p-{pw["id"]}">{esc(tax_name(lang, pw))}</a></b>'
                   + (f' <span class="sm">· {" · ".join(pos)}</span>' if pos else "")
                   + f'<div class="chain">{pathway_chain(S, lang, pw, g)}</div><div class="sm">{esc(pw["den"] if lang == "en" else pw["dzh"])}</div></div>')
    if S.links_of.get(g):
        by = collections.defaultdict(list)
        for h, ty in S.links_of[g]:
            by[ty].append(h)
        lbl = S.tax.get("rel_lbl") or {}
        out.append("<p>" + "<br>".join(f'<span class="sm">{esc((lbl.get(ty) or [ty, ty])[1 if lang == "en" else 0])}{T(lang, "：", ": ")}</span>' + " · ".join(S.tlink(lang, h) for h in hs)
                                       for ty, hs in by.items()) + "</p>")
    if not out:
        return ""
    return f'<h2>{T(lang, "分类与通路", "Class and pathways")}</h2>' + "".join(out)


def hub_targets(S, lang):
    tr = S.tr if lang == "en" else (lambda s: s)
    gs = sorted(S.tinfo, key=lambda g: (-len(S.tinfo[g]["progs"]), g))
    rows = []
    for g in gs:
        x = S.tinfo[g]
        cos = {c for p in x["progs"] for c in p["cos"] if c}
        maxp = max((p["ph"] for p in x["progs"]), key=phn, default="")
        tas = collections.Counter(t.get("ta") for t in x["trials"] if t.get("ta"))
        rows.append([S.tlink(lang, g), str(len(x["progs"])), str(len(cos)), esc(ph_lbl(lang, maxp)), esc(", ".join(tr(a) for a, _ in tas.most_common(2)))])
    desc = T(lang, f"按靶点查临床管线：{len(gs)} 个靶点按分子类别和家族分组，附主要信号通路的上下游关系；每个靶点有多少临床项目、几家公司、最高推进到哪一期。",
             f"Clinical pipelines by drug target: {len(gs)} targets grouped by molecular class and family, with the main signalling pathways; program counts, companies and furthest phase for each.")
    rowof = dict(zip(gs, rows))
    secs, toc, seen = [], [], set()
    for c in S.tax["classes"]:
        crow = []
        for f in c["families"]:
            ts = sorted([g for g in f["targets"] if g in rowof], key=lambda g: (-len(S.tinfo[g]["progs"]), g))
            for i, g in enumerate(ts):
                seen.add(g)
                r = rowof[g]
                crow.append([esc(tax_name(lang, f)) if i == 0 else ""] + r[:4])
        if not crow:
            continue
        n = sum(1 for f in c["families"] for g in f["targets"] if g in rowof)
        toc.append(f'<a href="#c-{c["id"]}">{esc(tax_name(lang, c))}</a> <span class="sm">{n}</span>')
        secs.append(f'<h2 id="c-{c["id"]}">{esc(tax_name(lang, c))} <small>{n}</small></h2>'
                    + table([T(lang, "家族", "Family"), T(lang, "靶点", "Target"), T(lang, "临床项目", "Programs"), T(lang, "公司", "Companies"), T(lang, "最高阶段", "Furthest phase")], crow))
    rest = [rowof[g] for g in gs if g not in seen]
    if rest:
        secs.append(f'<h2 id="c-other">{T(lang, "未分类", "Unclassified")} <small>{len(rest)}</small></h2>'
                    + table([T(lang, "靶点", "Target"), T(lang, "临床项目", "Programs"), T(lang, "公司", "Companies"), T(lang, "最高阶段", "Furthest phase"), T(lang, "领域", "Areas")], rest))
    pws = "".join(f'<div class="pw" id="p-{pw["id"]}"><b>{esc(tax_name(lang, pw))}</b><div class="chain">{pathway_chain(S, lang, pw)}</div>'
                  f'<div class="sm">{esc(pw["den"] if lang == "en" else pw["dzh"])}</div></div>' for pw in S.tax["pathways"])
    body = f"""<h1>{T(lang, "靶点", "Targets")} <small>{len(gs)}</small></h1><p class="lead">{esc(desc)}</p>
<p class="rel">{" · ".join(toc)} · <a href="#pathways">{T(lang, "信号通路", "Pathways")}</a></p>
{"".join(secs)}
<h2 id="pathways">{T(lang, "信号通路与上下游", "Pathways: upstream to downstream")} <small>{len(S.tax["pathways"])}</small></h2>
<p class="sm">{T(lang, "箭头从上游指向下游，斜杠分隔同一环节上并列的靶点；没有箭头的是同一疾病机制下的相关靶点分组。", "Arrows run upstream to downstream; slashes separate targets at the same step. Groups without arrows are related targets for one disease mechanism, not a cascade.")}</p>
{pws}"""
    return page(S, lang, "targets", "", T(lang, "靶点临床管线一览 | Hit or Miss", "Drug targets in clinical development | Hit or Miss"), desc, body,
                [(S.app(lang), "Hit or Miss"), (S.path(lang, "targets"), T(lang, "靶点", "Targets"))])


def hub_drugs(S, lang):
    ds = sorted(S.dpage, key=lambda c: S.dinfo[c]["name"].lower())
    by = collections.OrderedDict()
    for c in ds:
        ch = S.dinfo[c]["name"][:1].upper()
        by.setdefault(ch if ch.isalpha() else "#", []).append(c)
    desc = T(lang, f"按药物查临床试验和读出：{len(ds)} 个药物，每个药物一条时间线，串起注册库试验、新闻稿读出和公司读出指引。",
             f"Clinical trials and readouts by drug: {len(ds)} drugs, each with a timeline of registry trials, topline news and company guidance.")
    body = f"""<h1>{T(lang, "药物", "Drugs")} <small>{len(ds)}</small></h1><p class="lead">{esc(desc)}</p>
<p class="az">{" ".join(f'<a href="#l-{esc(k)}">{esc(k)}</a>' for k in by)}</p>
{"".join(f'<h2 id="l-{esc(k)}">{esc(k)}</h2><p class="rel">' + " · ".join(S.dlink(lang, c) + f' <span class="sm">{len(S.dinfo[c]["trials"])}</span>' for c in v) + "</p>" for k, v in by.items())}"""
    return page(S, lang, "drugs", "", T(lang, "药物临床试验一览 | Hit or Miss", "Drugs in clinical trials, A–Z | Hit or Miss"), desc, body,
                [(S.app(lang), "Hit or Miss"), (S.path(lang, "drugs"), T(lang, "药物", "Drugs"))])


def hub_trials(S, lang):
    tr = S.tr if lang == "en" else (lambda s: s)
    by = collections.defaultdict(list)
    for t in S.main.values():
        by[t.get("ta") or "其他"].append(t)
    desc = T(lang, f"{len(S.main)} 项注册库试验：已公布结果、已完成待公布、即将到达主要完成日和提前终止，每项附成败判定和主要终点数据。",
             f"{len(S.main)} registry trials: results posted, awaiting results, primary completion due, and stopped early — each with a hit / miss call and primary-endpoint data.")
    secs = []
    for ta in sorted(by, key=lambda k: -len(by[k])):
        ts = sorted(by[ta], key=lambda t: trial_date(t), reverse=True)
        secs.append(f'<h2>{esc(tr(ta))} <small>{len(ts)}</small></h2>' + table(trial_head(lang), [trial_row(S, lang, t) for t in ts]))
    body = f'<h1>{T(lang, "试验", "Trials")} <small>{len(S.main)}</small></h1><p class="lead">{esc(desc)}</p>' + "".join(secs)
    return page(S, lang, "trials", "", T(lang, "临床试验读出一览：达到还是落空 | Hit or Miss", "Clinical trial readouts: hit or miss | Hit or Miss"), desc, body,
                [(S.app(lang), "Hit or Miss"), (S.path(lang, "trials"), T(lang, "试验", "Trials"))])


CSS = """:root{--bg:#f3f5f7;--surface:#fff;--ink:#14202e;--muted:#5b6878;--line:#dfe4ea;--accent:#1f4f8f;--accent-soft:#e3ecf8;
--pos:#1d7a4f;--pos-soft:#e2f3ea;--neg:#b3342b;--neg-soft:#fbe7e5;--mix:#a46a0a;--mix-soft:#fbf0dc;
--f-body:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;--f-mono:ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f151c;--surface:#17202a;--ink:#e4eaf1;--muted:#97a4b4;--line:#2a3644;
--accent:#7fb0ef;--accent-soft:#1c2c42;--pos:#5cc792;--pos-soft:#15301f;--neg:#f0857c;--neg-soft:#3a1b19;--mix:#e7b55c;--mix-soft:#3a2c12}}
:root[data-theme="dark"]{--bg:#0f151c;--surface:#17202a;--ink:#e4eaf1;--muted:#97a4b4;--line:#2a3644;--accent:#7fb0ef;--accent-soft:#1c2c42;
--pos:#5cc792;--pos-soft:#15301f;--neg:#f0857c;--neg-soft:#3a1b19;--mix:#e7b55c;--mix-soft:#3a2c12}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 var(--f-body)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.top{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;justify-content:space-between;max-width:1080px;margin:0 auto;padding:14px 16px;border-bottom:1px solid var(--line)}
.brand{font-weight:700;font-size:20px;color:var(--ink);letter-spacing:.01em}.brand span{color:var(--muted);font-weight:500}
.top nav{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:14px}.top .lang{border:1px solid var(--line);border-radius:6px;padding:0 8px}
main{max-width:1080px;margin:0 auto;padding:8px 16px 32px}
.crumb{font-size:13px;color:var(--muted);margin:10px 0 4px}.crumb span{margin:0 2px}
h1{font-size:28px;line-height:1.25;margin:8px 0 10px}h1 small{display:block;font-size:15px;font-weight:500;color:var(--muted);margin-top:4px}
h2{font-size:19px;margin:30px 0 10px;padding-top:12px;border-top:1px solid var(--line)}h2 small,h1 small.n{color:var(--muted);font-weight:500;font-size:14px}
h3{font-size:15px;margin:16px 0 4px}
.lead{font-size:16px;max-width:820px}.sub{color:var(--muted);margin:-4px 0 8px}.sm{font-size:12.5px;color:var(--muted)}
.alias{color:var(--muted);font-size:13.5px;margin:2px 0}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.tag{background:var(--accent-soft);color:var(--accent);border-radius:999px;padding:1px 10px;font-size:12.5px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.kpis div{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.kpis b{display:block;font-size:22px;line-height:1.2}.kpis span{font-size:12.5px;color:var(--muted)}
.btn{display:inline-block;background:var(--accent);color:var(--surface);border-radius:8px;padding:6px 14px;font-size:14px;margin:4px 6px 4px 0}
.btn:hover{text-decoration:none;opacity:.9}.btn.ghost{background:transparent;color:var(--accent);border:1px solid var(--line)}
.tw{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}
td:last-child{white-space:nowrap}
.v{display:inline-block;border-radius:4px;padding:0 6px;font-size:12px;background:var(--line);color:var(--ink);white-space:nowrap}
.v.pos{background:var(--pos-soft);color:var(--pos)}.v.neg{background:var(--neg-soft);color:var(--neg)}.v.mix{background:var(--mix-soft);color:var(--mix)}
.verdict .v{font-size:14px;padding:2px 10px}ul.ev{padding-left:20px}
.facts{display:grid;grid-template-columns:max-content 1fr;gap:4px 18px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0}
.facts dt{color:var(--muted);font-size:13px}.facts dd{margin:0}
.cur{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:10px 0}.cur h3{margin:2px 0}.cur p{margin:4px 0}
.rel{line-height:2}.pw{margin:10px 0 14px}.pw .chain{margin:4px 0;line-height:1.9}.pw .stg{white-space:normal}.pw .arr{color:#888;margin:0 4px}.az a{display:inline-block;min-width:22px;text-align:center}
.fr{display:inline-block;font-size:12px;line-height:1.5;padding:0 7px;border-radius:10px;white-space:nowrap}.fr-eff{background:var(--neg-soft);color:var(--neg)}.fr-safe{background:var(--neg);color:#fff}.fr-biz{background:var(--accent-soft);color:var(--accent)}.fr-ops{background:var(--mix-soft);color:var(--mix)}.fr-reg{border:1px solid var(--mix);color:var(--mix)}.fr-unk{background:var(--bg);color:var(--muted);border:1px solid var(--line)}.ftab td:not(:first-child){text-align:right}.ftab th:not(:first-child){text-align:right}.moltab td:first-child{width:128px}.moltab img.mol{display:block}.moltab tr.grp td{background:var(--bg);font-size:12px;font-weight:600;color:var(--muted);padding:5px 8px}.moltab{min-width:900px}
.dh{display:flex;gap:18px;align-items:flex-start}.mol{background:#fff;border-radius:10px;border:1px solid var(--line)}
code{font-family:var(--f-mono);font-size:12px;word-break:break-all}
footer{max-width:1080px;margin:0 auto;padding:14px 16px 28px;border-top:1px solid var(--line);font-size:12.5px;color:var(--muted)}
@media (max-width:600px){h1{font-size:23px}.facts{grid-template-columns:1fr}.facts dt{margin-top:6px}.dh{flex-direction:column}}
"""


def not_found(S):
    return page(S, "zh", None, "", "页面不存在 | Hit or Miss", "页面不存在", f"""<h1>页面不存在 <small>Page not found</small></h1>
<p>可能是链接写错了，或者这个页面已经下线。可以从这里继续：</p>
<p><a class="btn" href="{S.app('zh')}">打开交互版</a> <a class="btn ghost" href="{S.path('zh', 'targets')}">靶点</a> <a class="btn ghost" href="{S.path('zh', 'drugs')}">药物</a> <a class="btn ghost" href="{S.path('zh', 'trials')}">试验</a></p>
<p class="sm">This page doesn't exist. <a href="{S.app('en')}">Open the app</a> · <a href="{S.path('en', 'targets')}">Targets</a> · <a href="{S.path('en', 'drugs')}">Drugs</a> · <a href="{S.path('en', 'trials')}">Trials</a></p>""",
                [(S.app("zh"), "Hit or Miss")])


def build(d, docs, site_url=None):
    site_url = site_url or os.environ.get("SITE_URL") or DEFAULT_SITE
    S = Site(d, docs, site_url)
    for sub in GEN_DIRS:
        p = os.path.join(docs, sub)
        if os.path.isdir(p):
            shutil.rmtree(p)
    urls = []  # (zh 路径, en 路径, lastmod)

    def write(rel_path, text):
        fp = os.path.join(docs, rel_path[len(S.base):], "index.html")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(text)

    def emit(kind, slug, fn, arg, lastmod):
        for lang in ("zh", "en"):
            write(S.path(lang, kind, slug), fn(S, lang, arg))
        urls.append((S.path("zh", kind, slug), S.path("en", kind, slug), lastmod))

    for kind, fn in (("targets", hub_targets), ("drugs", hub_drugs), ("trials", hub_trials), ("failures", hub_failures)):
        for lang in ("zh", "en"):
            write(S.path(lang, kind), fn(S, lang))
        urls.append((S.path("zh", kind), S.path("en", kind), S.asof))
    for g in S.tinfo:
        emit("target", S.tslug[g], target_page, g, S.asof)
    for c in S.dpage:
        lm = max([trial_date(t) for t in S.dinfo[c]["trials"]] + [n.get("d") or "" for n in S.dinfo[c]["news"]] or [S.asof])
        emit("drug", c, drug_page, c, min(lm, S.asof) if lm else S.asof)
    for nct, t in S.main.items():
        emit("trial", nct, trial_page, t, min(t.get("updated") or t.get("results") or S.asof, S.asof))

    # 失败原因库给交互版用：docs/failures.json
    fl = []
    for e in S.fail:
        r = {"d": e["d"], "r": e["r"], "k": e["k"], "nct": e["nct"], "g": e["g"], "co": e["co"], "ph": e["ph"], "mod": e["mod"], "ta": e["ta"],
             "n": (" + ".join(S.dinfo[c]["name"] for c in (e.get("ds") or [])[:2] if c in S.dinfo) if e.get("ds") else e.get("name") or ""),
             "why": e["why"], "cond": e["cond"]}
        if e["t"] is not None:
            r["wc"] = e["t"].get("why_cat") or ""
        if e.get("u"):
            r["u"] = e["u"]
        fl.append({k: v for k, v in r.items() if v not in ("", [], None)})
    with open(os.path.join(docs, "failures.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": S.asof, "reasons": FAIL_R, "items": fl}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(docs, "static.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    with open(os.path.join(docs, "404.html"), "w", encoding="utf-8") as f:
        f.write(not_found(S))
    with open(os.path.join(docs, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {S.site}sitemap.xml\n")
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    alts = lambda z, e: (f'<xhtml:link rel="alternate" hreflang="zh" href="{esc(S.abs(z))}"/>'
                         f'<xhtml:link rel="alternate" hreflang="en" href="{esc(S.abs(e))}"/>')
    sm.append(f'<url><loc>{esc(S.site)}</loc><lastmod>{S.asof}</lastmod>'
              f'<xhtml:link rel="alternate" hreflang="zh" href="{esc(S.site)}"/><xhtml:link rel="alternate" hreflang="en" href="{esc(S.site)}?lang=en"/></url>')
    for z, e, lm in urls:
        for loc in (z, e):
            sm.append(f"<url><loc>{esc(S.abs(loc))}</loc>" + (f"<lastmod>{esc(lm)}</lastmod>" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(lm or "")) else "") + alts(z, e) + "</url>")
    sm.append("</urlset>\n")
    with open(os.path.join(docs, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(sm))
    untaxed = [g for g in S.tinfo if g not in S.tax_of]
    if untaxed:
        print(f"[warn] {len(untaxed)} targets have no class in data/target_taxonomy.json (add them in scripts/make_target_taxonomy.py): {', '.join(untaxed[:12])}", file=sys.stderr)
    return {"targets": len(S.tinfo), "drugs": len(S.dpage), "trials": len(S.main), "urls": 2 * len(urls) + 1}


def load_embedded(index_html):
    h = open(index_html, encoding="utf-8").read()
    m = re.search(r'<script id="trials-data" type="application/json">(.*?)</script>', h, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


if __name__ == "__main__":
    docs = sys.argv[1] if len(sys.argv) > 1 else "docs"
    r = build(load_embedded(os.path.join(docs, "index.html")), docs)
    print(f"static pages · {r['targets']} targets · {r['drugs']} drugs · {r['trials']} trials · {r['urls']} sitemap URLs", file=sys.stderr)
