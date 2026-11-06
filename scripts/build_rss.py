#!/usr/bin/env python3
"""按靶点、公司生成 RSS 订阅（构建时由 build_site.py 调用）。

每个订阅包含新闻稿读出和注册库新公布的结果，最近一年、最多 50 条。RSS 阅读器可以直接订阅；
想收邮件的话，把订阅地址填进任意 RSS 转邮件服务即可。

  docs/rss/all.xml           全站：所有新闻稿读出 + 注册库新结果
  docs/rss/t/<id>.xml        单个靶点
  docs/rss/c/<id>.xml        单个公司
  docs/rss/index.json        {"t": {靶点: id}, "c": {公司: id}}，页面用它找订阅地址
"""
import datetime as dt, email.utils, hashlib, json, os, re
from xml.sax.saxutils import escape

KEEP_DAYS = 365
MAX_ITEMS = 50
VL = {"达到": "Hit", "未达到": "Miss", "混合": "Mixed", "终止": "Stopped", "积极信号": "Promising", "待判定": "Unclassified",
      "部分达到": "Partly met", "存疑": "Questionable", "描述性": "Descriptive"}
NUM_FMT = {"HR": "HR {v}", "p": "p{v}", "ORR": "ORR {v}%", "CR": "CR {v}%", "mPFS": "mPFS {v} mo", "mOS": "mOS {v} mo", "减重": "weight −{v}%", "降低": "−{v}%"}


def fid(name):
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]


def nums_txt(nums):
    out = []
    for n in nums or []:
        s = NUM_FMT.get(n["k"], n["k"] + " {v}").format(v=n["v"])
        if n.get("lo") and n.get("hi"):
            s += f" ({n['lo']}–{n['hi']})"
        out.append(s)
    return " · ".join(out)


def rfc822(d):
    try:
        return email.utils.format_datetime(dt.datetime.fromisoformat(d).replace(hour=12, tzinfo=dt.timezone.utc))
    except (ValueError, TypeError):
        return ""


def collect(news, sets, site):
    """统一成 {d, title, link, desc, tg, co, guid}。"""
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    rows = []
    for x in news:
        if (x.get("d") or "") < cut:
            continue
        meta = " · ".join(z for z in [x.get("co"), x.get("drug"), x.get("ph") and f"Ph {x['ph']}", x.get("ta"), nums_txt(x.get("nums"))] if z)
        rows.append({"d": x["d"], "title": f"[{x.get('v')} / {VL.get(x.get('v'), '')}] {x['t']}", "link": x["u"],
                     "desc": f"{meta}\n{x.get('s', '')}" + (f"\n{site}#t-{x['nct']}" if x.get("nct") else "") + (f"\n{x['note']}" if x.get("note") else ""),
                     "tg": x.get("tg") or [], "co": x.get("co") or "", "guid": "news-" + x["id"]})
    for t in sets.get("results", []):
        d = t.get("results") or t.get("pcd") or ""
        if d < cut:
            continue
        v = (t.get("as") or {}).get("verdict") or ""
        lbl = t.get("acronym") or (t.get("iv") or [{}])[0].get("n") or t.get("title", "")
        rows.append({"d": d, "title": f"[{v or '结果'}{' / ' + VL[v] if v in VL else ''}] {lbl}: {t.get('nct')} results posted",
                     "link": f"{site}#t-{t['nct']}", "desc": " · ".join(z for z in [t.get("group"), t.get("phase") and f"Ph {t['phase']}",
                                                                                   (t.get("conditions") or [""])[0], t.get("title")] if z),
                     "tg": t.get("tg") or [], "co": t.get("group") or "", "guid": "reg-" + t["nct"]})
    rows.sort(key=lambda r: r["d"], reverse=True)
    return rows


def write_feed(path, title, desc, link, rows):
    items = []
    for r in rows[:MAX_ITEMS]:
        items.append(f"<item><title>{escape(r['title'])}</title><link>{escape(r['link'])}</link>"
                     f"<description>{escape(r['desc'])}</description><pubDate>{rfc822(r['d'])}</pubDate>"
                     f"<guid isPermaLink=\"false\">{escape(r['guid'])}</guid></item>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
           f"<title>{escape(title)}</title><link>{escape(link)}</link><description>{escape(desc)}</description>"
           f"<lastBuildDate>{rfc822(rows[0]['d']) if rows else ''}</lastBuildDate>" + "".join(items) + "</channel></rss>\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(xml)


def build(news, sets, out_dir, site):
    site = site.rstrip("/") + "/"
    rows = collect(news, sets, site)
    write_feed(os.path.join(out_dir, "all.xml"), "Hit or Miss · 全部读出", "新闻稿读出和注册库新结果", site, rows)
    by_t, by_c = {}, {}
    for r in rows:
        for g in r["tg"]:
            by_t.setdefault(g, []).append(r)
        if r["co"]:
            by_c.setdefault(r["co"], []).append(r)
    # 先清掉旧文件，避免留下已经没有条目的订阅
    for sub in ("t", "c"):
        d = os.path.join(out_dir, sub)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".xml"):
                    os.remove(os.path.join(d, f))
    idx = {"t": {}, "c": {}, "generated": dt.date.today().isoformat()}
    for g, rs in by_t.items():
        idx["t"][g] = fid("t:" + g)
        write_feed(os.path.join(out_dir, "t", idx["t"][g] + ".xml"), f"Hit or Miss · {g}", f"{g} 的临床读出", site + "#target/" + g, rs)
    for c, rs in by_c.items():
        idx["c"][c] = fid("c:" + c)
        write_feed(os.path.join(out_dir, "c", idx["c"][c] + ".xml"), f"Hit or Miss · {c}", f"{c} 的临床读出", site, rs)
    json.dump(idx, open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return len(rows), len(idx["t"]), len(idx["c"])
