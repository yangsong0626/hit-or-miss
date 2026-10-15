#!/usr/bin/env python3
"""每周核对手工清单有没有过期：用 openFDA（Drugs@FDA）查交易候选里每个药的通用名，
发现「最后核实日期」之后有新的批准（含新适应症补充申请），就写进 data/watch_alerts.json，页面上会标出来；
本次新发现的提醒另写一份 Markdown（默认 watch_new.md，不入库），工作流用它在 GitHub 上开 issue。

催化剂到期、条目超过 60 天未核实这两类提醒不需要联网，由页面按当天日期计算。
失败时保留旧文件、返回 0，不拖垮每周更新。

用法：python scripts/check_watch.py [--deals data/deal_watch.json] [--out data/watch_alerts.json] [--new-md watch_new.md]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.fda.gov/drug/drugsfda.json"


def fetch_json(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hit-or-miss/1.0"}), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:  # openFDA 查不到时返回 404
                return {"results": []}
            if k == tries - 1:
                raise
        except Exception:  # noqa: BLE001
            if k == tries - 1:
                raise
        time.sleep(2 * (k + 1))


def approvals(name, get=fetch_json):
    """返回 [(日期 YYYY-MM-DD, 申请号, 类型, 品牌名)]，只要已批准（AP）的原始申请和补充申请。"""
    time.sleep(1.6 if get is fetch_json else 0)  # 无 API key 时 openFDA 限每分钟 40 次
    q = f'openfda.generic_name:"{name}"+products.active_ingredients.name:"{name}"'
    data = get(f"{API}?search={urllib.parse.quote(q, safe=':+')}&limit=20")
    out = []
    for r in data.get("results", []):
        brand = ", ".join(sorted({p.get("brand_name", "") for p in r.get("products", []) if p.get("brand_name")}))
        for s in r.get("submissions", []):
            if s.get("submission_status") != "AP" or not s.get("submission_status_date"):
                continue
            d = s["submission_status_date"]
            out.append((f"{d[:4]}-{d[4:6]}-{d[6:8]}", r.get("application_number", ""),
                        f"{s.get('submission_type', '')}{s.get('submission_number', '')}", brand))
    return sorted(set(out))


def run(deals, get=fetch_json):
    alerts = []
    for kind in ("acquire", "license"):
        for area in deals.get(kind, []):
            for x in area["items"]:
                since = x.get("verified") or deals.get("asof") or "1900-01-01"
                for name in x.get("inn") or []:
                    for date, app, sub, brand in approvals(name, get):
                        if date > since:
                            alerts.append({"co": x["co"], "asset": x["asset"], "inn": name, "date": date, "app": app,
                                           "sub": sub, "brand": brand, "kind": "fda"})
    alerts.sort(key=lambda a: a["date"], reverse=True)
    return alerts


def main():
    base = os.path.join(os.path.dirname(__file__), "..", "data")
    ap = argparse.ArgumentParser()
    ap.add_argument("--deals", default=os.path.join(base, "deal_watch.json"))
    ap.add_argument("--out", default=os.path.join(base, "watch_alerts.json"))
    ap.add_argument("--new-md", default="watch_new.md")
    a = ap.parse_args()
    deals = json.load(open(a.deals, encoding="utf-8"))
    old = {}
    if os.path.exists(a.out):
        try:
            old = json.load(open(a.out, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    try:
        alerts = run(deals)
    except Exception as e:  # noqa: BLE001
        print(f"watch check failed, keeping previous file: {e}", file=sys.stderr)
        return 0
    key = lambda x: (x["co"], x["inn"], x["app"], x["sub"])  # noqa: E731
    seen = {key(x) for x in old.get("alerts", [])}
    new = [x for x in alerts if key(x) not in seen]
    json.dump({"asof": dt.date.today().isoformat(), "source": "openFDA Drugs@FDA", "alerts": alerts},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if new:
        lines = ["每周核对发现交易候选清单里有药物在最后核实日期之后获得 FDA 批准，请更新 `data/deal_watch.json`（阶段、成功概率、verified），必要时把已被收购的公司移出。", ""]
        lines += [f"- **{x['co']}** · {x['inn']}（{x['brand'] or '品牌名未知'}）：{x['date']} 批准 {x['app']} {x['sub']}" for x in new]
        open(a.new_md, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    elif os.path.exists(a.new_md):
        os.remove(a.new_md)
    print(f"{len(alerts)} alerts ({len(new)} new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
