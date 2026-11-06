#!/usr/bin/env python3
"""抓欧盟临床试验注册库（CTIS，euclinicaltrials.eu）里已获批、进行中的企业申办试验。

很多早期试验（尤其是在荷兰、比利时、德国做的 I 期）只在欧盟登记，不在 ClinicalTrials.gov。
这里把它们转成和 ClinicalTrials.gov 早期试验一样的字段，写到 data/ctis.json；构建时并入靶点赛道，
和 ClinicalTrials.gov 里同公司、同药、同分期的试验去重。

接口：POST https://euclinicaltrials.eu/ctis-public-api/search（公开、无需登录），每页最多 100 条。
状态码 2–5 是「已获批」的几个子状态（含招募中、进行中）。学术申办的试验去掉。

用法：
  python scripts/fetch_ctis.py                  # 每周更新
  python scripts/fetch_ctis.py --from-json f    # 离线测试：读本地的搜索结果
"""
import argparse, datetime as dt, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import modality  # noqa: E402
from fetch_trials import TA_RULES, sponsor_group  # noqa: E402

API = "https://euclinicaltrials.eu/ctis-public-api/search"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json",
           "User-Agent": "Mozilla/5.0 (compatible; hit-or-miss/1.0; +https://github.com/yangsong0626/hit-or-miss)"}
STATUS = [2, 3, 4, 5]
MAX_PAGES = 200
ACADEMIC = re.compile(r"universit|hospital|ziekenhuis|klinik|clinic\b|krankenhaus|h[oô]pital|ospedal|hospital|instit|"
                      r"foundation|stichting|fondation|fundaci|academ|college|medical cent|centre hospitalier|"
                      r"assistance publique|charit[eé]|consortium|research council|ministry|nhs|trust\b|non-commercial|"
                      r"academic|investigator|group\b|society|association|cooperative|onderzoek|erasmus|leiden|umc\b|"
                      r"amc\b|vumc|inserm|unicancer|eortc|gustave|karolinska|rigshospital", re.I)
COMMERCIAL = re.compile(r"commercial|pharma|industry|company", re.I)
COMPANY_NAME = re.compile(r"\b(inc|ltd|limited|llc|gmbh|ag|a/s|ab|plc|s\.?a\.?s?|s\.?p\.?a|b\.?v|n\.?v|k\.?k|co\.|corp|corporation|"
                          r"therapeutics|pharma\w*|bio\w*|sciences?|medicines?)\b", re.I)


def post(body):
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def _date(s):
    if not s:
        return ""
    s = str(s)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


def _phase(p):
    p = str(p or "")
    has1 = bool(re.search(r"Phase I(?!I|V)|Phase 1\b|first administration to humans|human pharmacology", p, re.I))
    has2 = bool(re.search(r"Phase II(?!I)|Phase 2\b|therapeutic exploratory", p, re.I))
    has3 = bool(re.search(r"Phase III|Phase 3\b|therapeutic confirmatory", p, re.I))
    if has2 and has3:
        return "2/3"
    if has3:
        return "3"
    if has1 and has2:
        return "1/2"
    if has2:
        return "2"
    if has1:
        return "1"
    return ""


def _list(v):
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            out += _list(x) if not isinstance(x, dict) else [x.get("name") or x.get("productName") or x.get("prodName") or ""]
        return [x for x in out if x]
    return [x.strip() for x in re.split(r",\s*(?![^()]*\))|;\s*|\n", str(v)) if x.strip()]


def is_industry(item):
    st = str(item.get("sponsorType") or "")
    sp = str(item.get("sponsor") or "")
    if st and COMMERCIAL.search(st) and not re.search(r"non-commercial", st, re.I):
        return True
    if st and re.search(r"non-commercial|academic|hospital", st, re.I):
        return False
    return bool(COMPANY_NAME.search(sp)) and not ACADEMIC.search(sp)


CORP_TAIL = re.compile(r"[\s,]+(operations|holdings?|international|global|europe|european|deutschland|germany|france|italia|italy|espa[nñ]a|spain|"
                       r"nederland|netherlands|belgium|ireland|uk|danmark|sverige|research( and| &) development|r&d|development|"
                       r"inc\.?|ltd\.?|limited|llc|gmbh|ag|a/s|ab|plc|s\.?a\.?s?|s\.?p\.?a\.?|s\.?r\.?l\.?|b\.?v\.?|n\.?v\.?|k\.?k\.?|co\.?|corp\.?|corporation|company)\.?$", re.I)


def clean_sponsor(sp):
    """欧盟注册库常写子公司全称（Arvinas Operations, Inc.、AstraZeneca AB），去掉尾部的公司后缀再归母公司。"""
    s = (sp or "").strip()
    for _ in range(4):
        s2 = CORP_TAIL.sub("", s).strip(" ,.")
        if s2 == s or len(s2) < 3:
            break
        s = s2
    return s


def convert(item):
    ph = _phase(item.get("trialPhase"))
    if not ph:
        return None
    prods, seen = [], set()
    for p in _list(item.get("product")):
        k = re.sub(r"[^a-z0-9]", "", p.lower())
        if not k or k in seen or re.search(r"placebo|matching|vehicle|sham", p, re.I):
            continue
        seen.add(k)
        prods.append(p)
    sp = str(item.get("sponsor") or "").strip()
    title = str(item.get("ctTitle") or item.get("shortTitle") or "").strip()
    conds = _list(item.get("conditions"))[:3]
    text = f"{title} {' '.join(conds)}"
    ta = next((lab for pat, lab in TA_RULES if re.search(pat, text, re.I)), "其他")
    t = {"nct": str(item.get("ctNumber") or "").strip(), "src": "ctis", "title": title[:300], "acronym": str(item.get("shortTitle") or "")[:60],
         "sponsor": sp, "group": sponsor_group(clean_sponsor(sp)) if sp else "", "phase": ph, "status": str(item.get("ctStatus") or ""),
         "n": item.get("totalNumberEnrolled") if isinstance(item.get("totalNumberEnrolled"), int) else None,
         "fp": _date(item.get("decisionDate") or item.get("decisionDateOverall") or item.get("startDateEU")),
         "conditions": conds, "iv": [{"n": p, "ty": "DRUG", "on": [], "r": "x"} for p in prods[:4]],
         "interventions": prods[:4], "ta": ta, "sum": title}
    if not t["nct"] or not prods:
        return None
    t["mod"], t["mods"] = modality.classify_trial(t)
    t["modg"] = modality.GROUPS.get(t["mod"], "未识别")
    return t


def fetch():
    items, page = [], 1
    while page <= MAX_PAGES:
        d = post({"pagination": {"page": page, "size": 100}, "searchCriteria": {"status": STATUS}})
        batch = d.get("data") or []
        items += batch
        pg = d.get("pagination") or {}
        print(f"  CTIS 第 {page} 页：{len(batch)} 条（共 {pg.get('totalRecords', '?')}）", file=sys.stderr)
        if not batch or not pg.get("nextPage") or page >= (pg.get("totalPages") or page):
            break
        page += 1
        time.sleep(0.6)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "ctis.json"))
    ap.add_argument("--from-json")
    a = ap.parse_args()
    try:
        raw = json.load(open(a.from_json, encoding="utf-8")).get("data", []) if a.from_json else fetch()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] CTIS not updated, keeping old file: {e}", file=sys.stderr)
        return
    ind = [x for x in raw if is_industry(x)]
    trials = [t for t in (convert(x) for x in ind) if t]
    json.dump({"generated": dt.date.today().isoformat(), "source": "CTIS", "trials": trials},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    from collections import Counter
    print(f"CTIS: raw {len(raw)} → industry {len(ind)} → kept {len(trials)}; phases {dict(Counter(t['phase'] for t in trials))}")


if __name__ == "__main__":
    main()
