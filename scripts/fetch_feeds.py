#!/usr/bin/env python3
"""每周抓取靶点页的「文献」和「新闻」：Europe PMC（论文数、最新论文、高被引综述）+ Google News RSS（中英文）。

靶点名单来自上一次构建生成的 docs/targets_index.json（按项目数排序，取前 N 个）。只用 Python 标准库。
任何单个靶点失败都跳过；整体失败时保留旧的 docs/feeds.json，退出码 0，不影响后面的构建。

用法：python scripts/fetch_feeds.py --index docs/targets_index.json --out docs/feeds.json [--top 200]
"""
import argparse, datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "hit-or-miss/1.0 (https://github.com/yangsong0626/hit-or-miss)"}
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CJK = re.compile(r"[㐀-鿿]")


def get(url, timeout=30, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def terms_for(g, alias):
    """和页面里的 tgTerms 规则一致：去掉中文和括号说明，短名称有长别名时用长别名。"""
    base = []
    if not CJK.search(g):
        inner = re.search(r"[（(]([^）)]+)[）)]", g)
        base = [x.strip() for x in re.split(r"\s*/\s*", re.sub(r"[（(][^）)]*[）)]", "", g)) if x.strip()]
        if inner and not CJK.search(inner.group(1)) and not re.search(r"泛|其他|pan", inner.group(1), re.I):
            base += [x.strip() for x in inner.group(1).split("/")]
    al = [a for a in alias if not CJK.search(a) and (not re.search(r"^programmed|^anti", a, re.I) or re.fullmatch(r"[A-Za-z0-9-]{2,12}", a))]
    seen, out = set(), []
    for x in base + al:
        x = x.strip()
        if len(x) >= 2 and not CJK.search(x) and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    strong = [x for x in out if len(x) >= 4 or re.search(r"\d", x)]
    return (strong or out)[:5]


CONTEXT = '(inhibitor OR antagonist OR agonist OR antibody OR degrader OR "drug discovery" OR therapy OR "clinical trial")'


def epmc(query, **kw):
    params = {"query": query, "format": "json", "pageSize": kw.get("size", 1), "resultType": kw.get("rt", "lite")}
    if kw.get("sort"):
        params["sort"] = kw["sort"]
    return json.loads(get(EPMC + "?" + urllib.parse.urlencode(params)))


def paper(r):
    src, pid = r.get("source"), r.get("id")
    u = f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/" if r.get("pmid") else (f"https://doi.org/{r['doi']}" if r.get("doi") else f"https://europepmc.org/article/{src}/{pid}")
    return {"t": (r.get("title") or "").rstrip(".")[:220], "j": (r.get("journalTitle") or r.get("bookOrReportDetails", {}).get("publisher") or "")[:80],
            "d": r.get("firstPublicationDate") or str(r.get("pubYear") or ""), "u": u, **({"c": r["citedByCount"]} if r.get("citedByCount") else {})}


def lit(terms, year):
    q = "(" + " OR ".join(f'"{t}"' for t in terms) + ") AND " + CONTEXT
    out = {"q": q, "years": {}}
    out["total"] = epmc(q, rt="idlist")["hitCount"]
    for y in range(year - 5, year + 1):
        out["years"][str(y)] = epmc(f"{q} AND PUB_YEAR:{y}", rt="idlist")["hitCount"]
        time.sleep(0.15)
    rec = epmc(f"{q} AND SRC:MED", size=8, sort="FIRST_PDATE desc")
    out["recent"] = [paper(r) for r in rec.get("resultList", {}).get("result", [])]
    rv = epmc(f'{q} AND PUB_TYPE:"review" AND FIRST_PDATE:[{year - 3}-01-01 TO {year}-12-31]', size=5, sort="CITED desc")
    out["reviews"] = [paper(r) for r in rv.get("resultList", {}).get("result", [])]
    return out


def news(terms, lang):
    q = "(" + " OR ".join(f'"{t}"' for t in terms) + ")"
    if lang == "en":
        q += " (drug OR trial OR FDA OR biotech) when:90d"
        loc = "hl=en-US&gl=US&ceid=US:en"
    else:
        q += " (药 OR 临床 OR 靶点) when:90d"
        loc = "hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    raw = get(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{loc}")
    root = ET.fromstring(raw)
    items = []
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
        items.append({"t": title[:200], "s": src[:60], "d": d, "u": it.findtext("link") or ""})
    items.sort(key=lambda x: x["d"], reverse=True)
    seen, out = set(), []
    for x in items:
        k = re.sub(r"\W+", "", x["t"].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="docs/targets_index.json")
    ap.add_argument("--out", default="docs/feeds.json")
    ap.add_argument("--top", type=int, default=200)
    a = ap.parse_args()
    try:
        idx = json.load(open(a.index, encoding="utf-8"))["targets"]
    except Exception as e:  # noqa: BLE001
        print(f"no target index ({e}); keeping old feeds", file=sys.stderr)
        return 0
    old = {}
    if os.path.exists(a.out):
        try:
            old = json.load(open(a.out, encoding="utf-8")).get("targets", {})
        except Exception:  # noqa: BLE001
            old = {}
    pick = idx[: a.top]
    year = dt.date.today().year
    res, ok_lit, ok_news = {}, 0, 0

    def one(t):
        g, terms = t["g"], terms_for(t["g"], t.get("alias", []))
        r = dict(old.get(g, {}))
        if not terms:
            return g, r, False, False
        fl = fn = False
        try:
            r["lit"] = lit(terms, year)
            fl = True
        except Exception as e:  # noqa: BLE001
            print(f"lit {g}: {e}", file=sys.stderr)
        return g, r, fl, fn

    with ThreadPoolExecutor(4) as ex:
        for g, r, fl, _ in ex.map(one, pick):
            res[g] = r
            ok_lit += fl
    # Google News 对频率敏感，串行慢一点抓
    fails = 0
    for t in pick:
        g, terms = t["g"], terms_for(t["g"], t.get("alias", []))
        if not terms or fails >= 15:
            continue
        try:
            res.setdefault(g, {})["news"] = {"en": news(terms, "en"), "zh": news(terms, "zh")}
            ok_news += 1
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"news {g}: {e}", file=sys.stderr)
        time.sleep(1.0)
    if ok_lit == 0 and ok_news == 0:
        print("nothing fetched; keeping old feeds", file=sys.stderr)
        return 0
    res = {g: r for g, r in res.items() if r}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"generated": dt.date.today().isoformat(), "targets": res}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"feeds: {ok_lit} targets with literature, {ok_news} with news → {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
