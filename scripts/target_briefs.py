#!/usr/bin/env python3
"""靶点小结：为什么重要、从临床结果学到了什么、剩下的机会。用 Claude 根据本站数据写中英文各一份。

每个靶点的临床依据只来自 build_static.fact_pack（本站收录的项目、读出、失败、即将到来的试验）；生物学背景由模型
凭常识写，页面上注明「未逐条人工核实」。结果写 data/target_briefs.json，build_static.py 渲染到靶点页。

只重算事实包有实质变化的靶点（pack_hash 变了），没变的保留上次的结果。

需要 Python ≥ 3.10 和 anthropic SDK（pip install anthropic），以及 API 凭据（ANTHROPIC_API_KEY 或 `ant auth login`）。
本仓库其余脚本兼容 3.8，这个脚本单独用新版 Python 跑，例如：

    python3.12 scripts/target_briefs.py --dry-run --only "EGFR,TL1A"   # 只打印给模型的输入，不调用 API
    python3.12 scripts/target_briefs.py --sync --only EGFR              # 同步跑一个，先看效果
    python3.12 scripts/target_briefs.py                                 # 批量跑全部有变化的靶点（Batch API，半价）

默认用 Batch API：提交后会把批次号记进 data/target_briefs.json 的 pending，下次运行先取回结果再决定要不要提交新批次。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build_static as B  # noqa: E402

OUT = B.BRIEFS
MODEL = "claude-opus-5-5"
EFFORT = "high"

SYSTEM = """You write short target briefs for Hit or Miss, a public, bilingual (Chinese/English) tracker of drug-development \
programs and clinical-trial readouts. Readers are R&D scientists, business-development staff, investors and clinicians.

For one drug target you get FACTS: a JSON pack of what this site tracks for that target (programs with phase, modality and \
company; recent readouts with the site's verdict; failures and early stops with a reason code; trials reaching primary \
completion in the next six months). You write three parts, in Chinese and in English:

1. why — why the target matters: the biology and the clinical rationale (mechanism, the disease it drives, genetic or \
clinical validation). 2-3 sentences.
2. learned — what the clinical record so far teaches: 2-4 bullets. Each bullet is a lesson that ties several facts together \
(where the mechanism works and where it does not, what separated hits from misses, modality or combination patterns, \
safety signals, attrition for commercial reasons), not a restatement of one row.
3. opps — where the remaining openings are: 2-3 bullets. Concrete white space suggested by the facts plus the biology: \
an indication few programs address, a modality not yet tried, patient selection or biomarkers, a way to differentiate from \
crowded leaders, an unanswered question the upcoming readouts will settle. Phrase these as hypotheses for a researcher, \
never as investment advice.

Grounding rules:
- Every clinical claim (a result, a failure, how crowded a field is, who is furthest along) must come from FACTS. When you \
use a specific readout or failure, cite its NCT id from FACTS in the text. Do not cite an NCT id that is not in FACTS.
- Do not invent efficacy numbers, dates, trial names, approval decisions or deal terms. FACTS has no efficacy numbers, so \
describe results qualitatively.
- The biology in "why" may draw on well-established knowledge. Name approved drugs only when the approval is long \
established and you are certain; otherwise say "the most advanced programs tracked here".
- FACTS covers registry trials (ClinicalTrials.gov, EU CTIS) and press releases this site tracks. Absence from FACTS does \
not mean absence in the world: say "among programs tracked here" when the claim depends on completeness.
- Verdicts: 达到 = met the primary endpoint; 部分达到 = partly met; 未达到 = missed; 终止 = stopped early; 无统计检验 and \
描述性 = no formal hypothesis test (neither a success nor a failure). Failure reason codes: eff efficacy, safe safety, biz \
business or strategy, ops enrollment or operations, reg regulatory, unk not stated. A stop for business reasons is not \
evidence against the mechanism.
- If there are too few readouts to draw lessons, set thin to true and write one "learned" bullet that says the clinical \
record is still thin and names which upcoming readouts (from upcoming_6m) will be the first real test, if any.

Style:
- zh: natural Simplified Chinese as written by Chinese pharma professionals. Keep drug names, gene names, company names and \
NCT ids in Latin script. No exclamation marks, no hype words (重磅, 颠覆, 革命性).
- en: plain, direct English. No hype.
- Both languages carry the same content. Length: why ≤ 110 Chinese characters / ≤ 70 English words; each bullet ≤ 80 \
Chinese characters / ≤ 50 English words.
- Do not start bullets with labels like "教训：" or "Lesson:"."""

LANG = {"type": "object", "additionalProperties": False, "required": ["why", "learned", "opps"],
        "properties": {"why": {"type": "string"},
                       "learned": {"type": "array", "items": {"type": "string"}},
                       "opps": {"type": "array", "items": {"type": "string"}}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["zh", "en", "thin"],
          "properties": {"zh": LANG, "en": LANG, "thin": {"type": "boolean"}}}


def load_site():
    docs = os.path.join(ROOT, "docs")
    S = B.Site(B.load_embedded(os.path.join(docs, "index.html")), docs, B.DEFAULT_SITE)
    S.fail = B.collect_failures(S)
    return S


def load_out():
    try:
        return json.load(open(OUT, encoding="utf-8"))
    except (OSError, ValueError):
        return {"targets": {}}


def save_out(d):
    d["targets"] = dict(sorted(d.get("targets", {}).items()))
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")
    os.replace(tmp, OUT)


def cid(g):
    return "t" + hashlib.md5(g.encode()).hexdigest()[:16]


def params(pk, model, effort):
    return {"model": model, "max_tokens": 16000, "system": SYSTEM,
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": "FACTS:\n" + json.dumps(pk, ensure_ascii=False, separators=(",", ":"))}]}


def known_ncts(pk):
    s = set()
    for k in ("readouts", "failures", "upcoming_6m"):
        for r in pk.get(k) or []:
            if r.get("nct"):
                s.add(r["nct"])
    return s


def validate(pk, out):
    """去掉引用了事实包之外 NCT 号的条目；why 里有就整份作废。返回 (结果或 None, 问题列表)。"""
    ok, issues = known_ncts(pk), []
    for lang in ("zh", "en"):
        L = out.get(lang) or {}
        if not (L.get("why") or "").strip():
            return None, [f"{lang}: empty why"]
        bad = set(B.NCT_RE.findall(L["why"])) - ok
        if bad:
            return None, [f"{lang}: why cites unknown {sorted(bad)}"]
        for part in ("learned", "opps"):
            keep = []
            for s in L.get(part) or []:
                s = s.strip()
                bad = set(B.NCT_RE.findall(s)) - ok
                if bad:
                    issues.append(f"{lang}.{part}: dropped bullet citing {sorted(bad)}")
                elif s:
                    keep.append(s)
            L[part] = keep[:4]
    return out, issues


def text_of(msg):
    return next((b.text for b in msg.content if b.type == "text"), "")


def record(d, g, pk, msg, model):
    if msg.stop_reason != "end_turn":
        return f"stop_reason={msg.stop_reason}"
    try:
        out = json.loads(text_of(msg))
    except ValueError:
        return "invalid JSON"
    out, issues = validate(pk, out)
    if out is None:
        return "; ".join(issues)
    out.update({"asof": pk["asof"], "fh": B.pack_hash(pk), "model": getattr(msg, "model", None) or model,
                "generated": datetime.date.today().isoformat()})
    if issues:
        out["issues"] = issues
    d["targets"][g] = out
    return None


def todo(S, d, args):
    want = [g.strip() for g in args.only.split(",")] if args.only else None
    gs = []
    for g in sorted(S.tinfo, key=lambda g: -len(S.tinfo[g]["progs"])):
        if want is not None and g not in want:
            continue
        if want is None and len(S.tinfo[g]["progs"]) < args.min_programs:
            continue
        pk = B.fact_pack(S, g)
        old = d["targets"].get(g)
        if not args.force and old and old.get("fh") == B.pack_hash(pk):
            continue
        gs.append((g, pk))
    if want:
        miss = set(want) - set(S.tinfo)
        if miss:
            print(f"[warn] not a target on this site: {', '.join(sorted(miss))}", file=sys.stderr)
    return gs[: args.limit] if args.limit else gs


def run_sync(client, d, items, args):
    """同步逐个调用；遇到拒答由服务端自动换模型重试（server-side fallbacks）。"""
    import anthropic
    for i, (g, pk) in enumerate(items, 1):
        p = params(pk, args.model, args.effort)
        try:
            msg = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **p)
        except anthropic.RateLimitError:
            print(f"[{i}/{len(items)}] {g}: rate limited, stopping; rerun to continue", file=sys.stderr)
            break
        except anthropic.APIStatusError as e:
            print(f"[{i}/{len(items)}] {g}: API error {e.status_code} {e.message}", file=sys.stderr)
            continue
        err = record(d, g, pk, msg, args.model)
        u = msg.usage
        print(f"[{i}/{len(items)}] {g}: {'ok' if not err else 'FAILED ' + err} · in {u.input_tokens} out {u.output_tokens}",
              file=sys.stderr)
        save_out(d)


def collect_batch(client, d, S, args):
    """取回上次提交的批次。没结束就返回 False。"""
    pend = d.get("pending")
    if not pend:
        return True
    b = client.messages.batches.retrieve(pend["id"])
    if b.processing_status != "ended":
        c = b.request_counts
        print(f"batch {pend['id']} still {b.processing_status}: {c.processing} processing, {c.succeeded} done", file=sys.stderr)
        return False
    by = {v: k for k, v in pend["ids"].items()}
    retry, n_ok = [], 0
    for r in client.messages.batches.results(pend["id"]):
        g = by.get(r.custom_id)
        if g is None or g not in S.tinfo:
            continue
        pk = B.fact_pack(S, g)
        if r.result.type == "succeeded":
            err = record(d, g, pk, r.result.message, args.model)
            if err:
                print(f"{g}: {err}", file=sys.stderr)
                if "refusal" in err:
                    retry.append((g, pk))
            else:
                n_ok += 1
        else:
            print(f"{g}: {r.result.type}", file=sys.stderr)
            retry.append((g, pk))
    d.pop("pending", None)
    save_out(d)
    print(f"batch {pend['id']}: {n_ok} briefs saved, {len(retry)} to retry", file=sys.stderr)
    if retry:
        # 拒答和出错的改走同步接口（带 fallbacks，批量接口不支持）
        run_sync(client, d, retry, args)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="comma-separated target names (exactly as on the site)")
    ap.add_argument("--limit", type=int, default=0, help="at most this many targets")
    ap.add_argument("--min-programs", type=int, default=1, help="skip targets with fewer programs (default 1)")
    ap.add_argument("--force", action="store_true", help="regenerate even when the facts have not changed")
    ap.add_argument("--sync", action="store_true", help="call the API one target at a time instead of the Batch API")
    ap.add_argument("--dry-run", action="store_true", help="print the facts that would be sent and exit")
    ap.add_argument("--wait", action="store_true", help="after submitting a batch, poll until it ends and collect it")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--effort", default=EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    args = ap.parse_args()

    S = load_site()
    d = load_out()
    if args.dry_run:
        items = todo(S, d, args)
        for g, pk in items:
            print(f"===== {g} · fh {B.pack_hash(pk)} · {len(json.dumps(pk, ensure_ascii=False))} chars")
            print(json.dumps(pk, ensure_ascii=False, indent=1))
        print(f"{len(items)} targets would be sent ({len(d['targets'])} briefs on file)", file=sys.stderr)
        return

    import anthropic
    client = anthropic.Anthropic()
    if not args.sync and not collect_batch(client, d, S, args):
        if not args.wait:
            return
        while not collect_batch(client, d, S, args):
            time.sleep(60)
    items = todo(S, d, args)
    if not items:
        print(f"nothing to do · {len(d['targets'])} briefs on file", file=sys.stderr)
        return
    if args.sync:
        run_sync(client, d, items, args)
        return

    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    ids = {g: cid(g) for g, _ in items}
    batch = client.messages.batches.create(requests=[
        Request(custom_id=ids[g], params=MessageCreateParamsNonStreaming(**params(pk, args.model, args.effort)))
        for g, pk in items])
    d["pending"] = {"id": batch.id, "submitted": datetime.datetime.now().isoformat(timespec="seconds"), "ids": ids}
    save_out(d)
    print(f"submitted batch {batch.id} with {len(items)} targets; rerun this script to collect results", file=sys.stderr)
    if args.wait:
        while not collect_batch(client, d, S, args):
            time.sleep(60)


if __name__ == "__main__":
    main()
