/* ================= 新闻稿读出 · 关注 · 药物时间线 · 读出日历 · 对比表 · 导出 =================
   数据都按需加载：news.json（读出 + 指引 + 会议）、structures.json（小分子结构）、rss/index.json（订阅地址）。 */

/* ---------- 通用：加载、药名键、导出、引用 ---------- */
let NEWS = null, newsP = null, STRUCT = null, structP = null, RSSIDX = null, rssP = null;
const getJSON = f => fetch(f, {cache: "no-cache"}).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
function loadNews(){
  if (NEWS) return Promise.resolve(NEWS);
  if (!newsP) newsP = getJSON("news.json").then(j => (NEWS = j)).catch(() => (NEWS = {items: [], guidance: [], conf: [], err: true}));
  return newsP;
}
function loadStruct(){
  if (STRUCT) return Promise.resolve(STRUCT);
  if (!structP) structP = getJSON("structures.json").then(j => (STRUCT = j)).catch(() => (STRUCT = {}));
  return structP;
}
function loadRss(){
  if (RSSIDX) return Promise.resolve(RSSIDX);
  if (!rssP) rssP = getJSON("rss/index.json").then(j => (RSSIDX = j)).catch(() => (RSSIDX = {t: {}, c: {}}));
  return rssP;
}
const nk = s => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
/* 药名 → 一组键：主名、括号里的英文名或代号 */
function drugKeys(name){
  const s = String(name || ""), out = new Set();
  const main = s.split(/[(（\[]/)[0];
  if (!/[一-鿿]/.test(main)) out.add(nk(main));
  (s.match(/[(（]([^)）]+)[)）]/g) || []).forEach(p => p.replace(/[()（）]/g, "").split(/[,;/]/).forEach(z => out.add(nk(z))));
  out.delete(""); return [...out].filter(k => k.length >= 4);
}
const ivKeys = iv => { const ks = new Set(drugKeys(iv.n)); (iv.on || []).forEach(o => { const k = nk(o); if (k.length >= 4) ks.add(k); }); return ks; };
function structOf(name){
  if (!STRUCT) return null;
  for (const k of (Array.isArray(name) ? name : drugKeys(name))) if (STRUCT[k]) return STRUCT[k];
  return null;
}
const molImg = (s, size, alt) => s ? `<a class="mol-wrap" href="https://pubchem.ncbi.nlm.nih.gov/compound/${s[0]}" target="_blank" rel="noopener" title="${esc(T("PubChem 结构", "Structure on PubChem"))}"><img class="mol" style="width:${size}px;height:${size}px" loading="lazy" alt="${esc(alt || "")}" src="https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/${s[0]}/PNG?image_size=${size * 2}x${size * 2}"></a>` : "";
// todayISO 已在模板里定义
function downloadFile(name, text, type){
  const blob = new Blob([text], {type: type || "text/plain;charset=utf-8"}), a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
function downloadCSV(name, head, rows){
  const q = v => { v = v == null ? "" : String(v); return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; };
  downloadFile(name, "﻿" + [head, ...rows].map(r => r.map(q).join(",")).join("\n"), "text/csv;charset=utf-8");
}
function copyText(text, btn){
  const done = () => { if (btn) { const o = btn.textContent; btn.textContent = T("已复制", "Copied"); setTimeout(() => btn.textContent = o, 1400); } };
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(() => fallback());
  else fallback();
  function fallback(){ const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); done(); } catch(e) {} ta.remove(); }
}
const SITE = () => location.href.split("#")[0];
const citeNews = x => `${x.t}. ${x.s || ""}, ${x.d}. ${x.u}` + T(` （经 Hit or Miss 整理，${todayISO()} 访问）`, ` (via Hit or Miss, accessed ${todayISO()})`);
const citeTrial = t => `${t.acronym ? t.acronym + ": " : ""}${t.title} (${t.nct}). ${t.group || t.sponsor || ""}. ClinicalTrials.gov, ${regUrl(t.nct)}` + T(` （经 Hit or Miss 整理，${todayISO()} 访问）`, ` (via Hit or Miss, accessed ${todayISO()})`);

/* ---------- 关键数字 ---------- */
const NUM_LBL = {HR: ["HR", "HR"], p: ["p", "p"], ORR: ["ORR", "ORR"], CR: [T("完全缓解率", "CR rate"), "CR"], mPFS: [T("中位 PFS", "mPFS"), "mPFS"], mOS: [T("中位 OS", "mOS"), "mOS"], "减重": [T("减重", "Weight loss"), "WL"], "降低": [T("降低", "Reduction"), "Red"]};
function numTxt(n){
  const l = NUM_LBL[n.k]?.[0] || n.k;
  if (n.k === "HR") return `HR ${n.v}${n.lo && n.hi ? ` (${n.lo}–${n.hi})` : ""}`;
  if (n.k === "p") return `p${n.v.replace(/^=/, "=")}`;
  if (n.k === "mPFS" || n.k === "mOS") return `${l} ${n.v} ${T("个月", "mo")}`;
  if (n.k === "减重" || n.k === "降低") return `${l} ${n.v}%`;
  return `${l} ${n.v}%`;
}
const numsHTML = ns => (ns || []).length ? `<div class="nums">${ns.map(n => `<span class="num">${esc(numTxt(n))}</span>`).join("")}</div>` : "";
const numsPlain = ns => (ns || []).map(numTxt).join(" · ");

/* ---------- 关注列表（存在浏览器里） ---------- */
const WKIND = {t: () => T("靶点", "Target"), c: () => T("公司", "Company"), d: () => T("药物", "Drug")};
function getWatch(){ try { return JSON.parse(localStorage.getItem("hom-watch") || "[]"); } catch(e) { return []; } }
function setWatch(w){ try { localStorage.setItem("hom-watch", JSON.stringify(w)); } catch(e) {} updWatchTab(); }
const watchKey = (k, n) => k + "|" + (k === "d" ? (drugKeys(n)[0] || nk(n)) : k === "c" ? nk(n) : n);
const isWatched = (k, n) => getWatch().some(w => watchKey(w.k, w.n) === watchKey(k, n));
function toggleWatch(k, n){
  const w = getWatch(), key = watchKey(k, n), i = w.findIndex(x => watchKey(x.k, x.n) === key);
  if (i >= 0) w.splice(i, 1); else w.push({k, n, at: todayISO()});
  setWatch(w);
  document.querySelectorAll(`[data-w="${CSS.escape(k + "|" + n)}"]`).forEach(b => { b.classList.toggle("on", i < 0); b.textContent = i < 0 ? "★" : "☆"; b.title = i < 0 ? T("取消关注", "Unfollow") : T("关注", "Follow"); });
  if (curTab === "wl") renderWatch();
}
const starBtn = (k, n) => n ? `<button class="star${isWatched(k, n) ? " on" : ""}" data-w="${esc(k + "|" + n)}" title="${isWatched(k, n) ? T("取消关注", "Unfollow") : T("关注", "Follow")} ${esc(n)}" aria-label="${T("关注", "Follow")} ${esc(n)}">${isWatched(k, n) ? "★" : "☆"}</button>` : "";
document.addEventListener("click", e => {
  const b = e.target.closest("[data-w]"); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const s = b.dataset.w, i = s.indexOf("|"); toggleWatch(s.slice(0, i), s.slice(i + 1));
}, true);
document.addEventListener("click", e => {
  const b = e.target.closest("[data-od]"); if (!b) return;
  e.preventDefault(); openDetail("d", b.dataset.od);
});
function watchHit(w, o){
  if (w.k === "t") return (o.tg || []).includes(w.n);
  if (w.k === "c") { const a = nk(w.n), b = nk(o.co); return !!b && (a === b || (a.length >= 5 && (b.startsWith(a) || a.startsWith(b)))); }
  const ks = drugKeys(w.n).concat([nk(w.n)]);
  return (o.dk || []).some(k => ks.includes(k));
}
/* 所有可关注的条目，统一成 {kind, d, title, sub, v, tg, co, dk, open} */
function watchPool(){
  const out = [];
  (NEWS?.items || []).forEach(x => out.push({kind: "nw", d: x.d, seen: x.first_seen || x.d, x, tg: x.tg, co: x.co, dk: drugKeys(x.drug)}));
  (NEWS?.early || []).forEach(e => out.push({kind: "es", d: e.d, seen: e.d, x: e, tg: e.tg, co: e.co, dk: drugKeys(e.drug)}));
  (NEWS?.guidance || []).forEach(g => out.push({kind: "gd", d: g.start, seen: g.d, x: g, tg: g.tg, co: g.co, dk: drugKeys(g.drug)}));
  (REG?.all || []).filter(t => ["results", "stopped", "upcoming", "completed"].includes(t._set)).forEach(t => {
    const dk = new Set(); (t.iv || []).forEach(iv => ivKeys(iv).forEach(k => dk.add(k)));
    out.push({kind: "tr", d: t._set === "results" ? (t.results || t.pcd) : t._set === "stopped" ? t.updated : t.pcd, seen: t.results || t.updated || t.pcd, x: t, tg: t.tg || (t.tgt ? [t.tgt] : []), co: t.group, dk: [...dk]});
  });
  return out;
}
function updWatchTab(){
  const b = $("tab-wl"); if (!b) return;
  const w = getWatch();
  if (!w.length || !NEWS) { b.textContent = T("我的关注", "Following") + (w.length ? ` (${w.length})` : ""); return; }
  let seen = ""; try { seen = localStorage.getItem("hom-watch-seen") || ""; } catch(e) {}
  const n = seen ? watchPool().filter(o => o.kind !== "gd" && (o.seen || "") > seen && w.some(x => watchHit(x, o))).length : 0;
  b.innerHTML = esc(T("我的关注", "Following")) + (n ? ` <span class="badge">${n} ${T("新", "new")}</span>` : ` (${w.length})`);
}
if (getWatch().length) setTimeout(() => loadNews().then(updWatchTab), 1200); else setTimeout(updWatchTab, 0);

function poolRowHTML(o, seen){
  const isNew = seen && o.kind !== "gd" && (o.seen || "") > seen ? `<span class="badge">${T("新", "new")}</span>` : "";
  if (o.kind === "nw") return newsItemHTML(o.x, isNew);
  if (o.kind === "es") { const e = o.x; return `<article class="sh-item"><div class="sh-side"><span class="date">${esc(e.d)}</span><span class="sig ana">${esc((ES_T[e.type] || (() => e.type))())}</span>${isNew}</div>
    <div class="sh-main"><h3><a href="${esc(e.u)}" target="_blank" rel="noopener">${esc(e.t)}</a></h3><div class="meta">${[e.co, e.drug, e.mod, (e.tg || []).join(" / ")].filter(Boolean).map(esc).join(" · ")}</div><div class="sm">${T("早期信号", "Early signal")} · ${esc(e.s || "")}</div></div></article>`; }
  if (o.kind === "gd") { const g = o.x; return `<article class="sh-item"><div class="sh-side"><span class="date">${esc(g.when)}</span><span class="sig mix">${T("预计读出", "Readout due")}</span></div>
    <div class="sh-main"><h3>${g.drug ? `<button class="tbtn" data-od="${esc(drugKeys(g.drug)[0] || "")}">${esc(g.drug)}</button>` : esc(g.co)}</h3><div class="meta">${[g.co, g.ph && T(`${g.ph} 期`, `Ph ${g.ph}`), g.ta].filter(Boolean).map(esc).join(" · ")}</div>
    <p class="sh-why">“${esc(g.snip)}”</p><div class="sm"><a href="${esc(g.u)}" target="_blank" rel="noopener">${esc(g.s || T("来源", "Source"))}</a> · ${esc(g.d)}</div></div></article>`; }
  const t = o.x, setL = {results: T("新公布结果", "Results posted"), stopped: T("提前终止", "Stopped"), upcoming: T("即将完成", "Due"), completed: T("已完成待公布", "Awaiting results")}[t._set];
  return `<article class="sh-item"><div class="sh-side"><span class="date">${esc(o.d || "")}</span>${t._set === "results" ? vchip(t) : `<span class="sig${t._set === "stopped" ? " neg" : ""}">${esc(setL)}</span>`}${isNew}</div>
    <div class="sh-main"><h3><button class="tbtn" data-ot="${esc(t.nct)}">${esc(t.acronym || (t.interventions || [])[0] || t.title)}</button></h3>
    <div class="meta"><b>${esc(t.group)}</b> · ${esc(T(`${t.phase} 期`, `Ph ${t.phase}`))} · ${esc(t.ta)} · ${esc((t.conditions || [])[0] || "")}</div><div class="sm">${esc(setL)} · ${esc(t.nct)}</div></div></article>`;
}

function renderWatch(){
  if (!NEWS || !REG) { $("wl-list").innerHTML = `<div class="empty">${T("正在加载…", "Loading…")}</div>`; Promise.all([loadNews(), loadRss(), loadStruct()]).then(() => { if (REG) renderWatch(); }); return; }
  if (!RSSIDX) { loadRss().then(renderWatch); return; }
  const w = getWatch();
  let seen = ""; try { seen = localStorage.getItem("hom-watch-seen") || ""; } catch(e) {}
  // 输入建议：靶点、公司、药物
  if (!$("wl-dl").childElementCount) {
    const tg = Object.keys(TGS.alias), co = new Set(), dr = new Set();
    (REG.all || []).forEach(t => t.group && co.add(t.group)); (NEWS.items || []).forEach(x => { if (x.co) co.add(x.co); if (x.drug) dr.add(x.drug); });
    $("wl-dl").innerHTML = [...tg.map(n => [n, WKIND.t()]), ...[...co].map(n => [n, WKIND.c()]), ...[...dr].map(n => [n, WKIND.d()])].slice(0, 6000).map(([n, k]) => `<option value="${esc(n)}">${esc(k)}</option>`).join("");
  }
  const rssUrl = (k, n) => { const id = RSSIDX?.[k]?.[n]; return id ? new URL(`rss/${k}/${id}.xml`, SITE()).href : ""; };
  $("wl-items").innerHTML = w.length ? w.map(x => { const u = x.k !== "d" ? rssUrl(x.k, x.n) : "";
      return `<span class="wl-chip"><span class="sm">${esc(WKIND[x.k]())}</span> <b>${esc(x.n)}</b>${u ? ` <a href="${esc(u)}" target="_blank" rel="noopener" title="RSS">RSS</a> <button class="linkish" data-copy="${esc(u)}">${T("复制订阅地址", "Copy feed URL")}</button>` : ""}<button class="wl-x" data-wrm="${esc(watchKey(x.k, x.n))}" aria-label="${T("移除", "Remove")}">×</button></span>`; }).join("")
    : `<p class="sm">${T("还没有关注任何东西。在上面输入靶点、公司或药名添加；新闻稿读出列表里的 ☆ 也可以一键关注。", "Nothing followed yet. Add a target, company or drug above, or tap ☆ on any topline news item.")}</p>`;
  $("wl-items").querySelectorAll("[data-wrm]").forEach(b => b.addEventListener("click", () => { setWatch(getWatch().filter(x => watchKey(x.k, x.n) !== b.dataset.wrm)); renderWatch(); }));
  $("wl-items").querySelectorAll("[data-copy]").forEach(b => b.addEventListener("click", () => copyText(b.dataset.copy, b)));
  $("wl-all").innerHTML = `${T("全站订阅：", "Site-wide feed: ")}<a href="rss/all.xml" target="_blank" rel="noopener">rss/all.xml</a> <button class="linkish" data-copy="${esc(new URL("rss/all.xml", SITE()).href)}">${T("复制", "Copy")}</button>`;
  $("wl-all").querySelector("[data-copy]").addEventListener("click", e => copyText(e.target.dataset.copy, e.target));
  const cutPast = new Date(Date.now() - 180 * 864e5).toISOString().slice(0, 10);
  const rows = w.length ? watchPool().filter(o => w.some(x => watchHit(x, o)) && (o.d || "") >= cutPast).sort((a, b) => String(b.seen || b.d).localeCompare(String(a.seen || a.d))) : [];
  const nNew = seen ? rows.filter(o => o.kind !== "gd" && (o.seen || "") > seen).length : 0;
  $("wl-meta").textContent = w.length ? T(`${rows.length} 条（近半年和即将发生）${nNew ? ` · ${nNew} 条是上次来过之后的新内容` : ""}`, `${rows.length} items (past six months and upcoming)${nNew ? ` · ${nNew} new since your last visit` : ""}`) : "";
  $("wl-list").innerHTML = rows.slice(0, 120).map(o => poolRowHTML(o, seen)).join("") || (w.length ? `<div class="empty">${T("近半年没有相关的读出或注册库变化。", "Nothing related in the past six months.")}</div>` : "");
  bindNewsActions($("wl-list"));
  window._wlRows = rows;
  try { localStorage.setItem("hom-watch-seen", todayISO()); } catch(e) {}
  setTimeout(updWatchTab, 50);
}
function addWatchFromInput(){
  const v = $("wl-in").value.trim(); if (!v) return;
  let k = $("wl-kind").value;
  if (!k) k = TGS.alias[v] ? "t" : (REG?.all || []).some(t => t.group === v) || (NEWS?.items || []).some(x => x.co === v) ? "c" : (TGS.ix.has(TGS.nz(v)) ? "t" : "d");
  const n = k === "t" && !TGS.alias[v] && TGS.ix.has(TGS.nz(v)) ? [...TGS.ix.get(TGS.nz(v))][0] : v;
  if (!isWatched(k, n)) toggleWatch(k, n);
  $("wl-in").value = ""; renderWatch();
}

/* ---------- 新闻稿读出 ---------- */
let nwV = "", nwLimit = 40;
const NV = {"达到": ["pos", "Hit"], "未达到": ["neg", "Miss"], "混合": ["mix", "Mixed"], "终止": ["neg", "Stopped"], "积极信号": ["pos", "Promising"], "待判定": ["", "Unclassified"]};
const NV_ORDER = ["达到", "积极信号", "混合", "未达到", "终止", "待判定"];
const NV_COLOR = {"达到": "--pos", "积极信号": "--pos", "混合": "--mix", "未达到": "--neg", "终止": "--neg", "待判定": "--muted"};
const nvLabel = v => EN ? (NV[v]?.[1] || v) : v;
function newsItemHTML(x, extra){
  const M = byNct();
  const dk = drugKeys(x.drug)[0] || "";
  const meta = [x.co ? `<b>${esc(x.co)}</b>${starBtn("c", x.co)}` : "", x.drug ? `<button class="tbtn" data-od="${esc(dk)}" title="${T("这个药的全部读出", "All readouts for this drug")}">${esc(x.drug)}</button>${starBtn("d", x.drug)}` : "",
    x.ph ? T(`${esc(x.ph)} 期`, `Phase ${esc(x.ph)}`) : "", x.ta ? esc(x.ta) : "", x.mod && x.mod !== "未识别" ? esc(x.mod) : ""].filter(Boolean).join(" · ");
  const nct = x.nct ? (M.has(x.nct) ? `<button class="tbtn nct" data-ot="${esc(x.nct)}">${esc(x.nct)}</button>` : `<a class="nct" href="${esc(regUrl(x.nct))}" target="_blank" rel="noopener">${esc(x.nct)}</a>`) : "";
  const more = (x.src || []).slice(0, 4).map(s => `<a href="${esc(s.u)}" target="_blank" rel="noopener">${esc(s.s || s.t)}</a>`).join("、");
  const st = structOf(x.drug);
  return `<article class="sh-item${st ? " has-mol" : ""}">
    <div class="sh-side"><span class="date">${esc(x.d)}</span><span class="sig ${NV[x.v]?.[0] || ""}">${esc(nvLabel(x.v))}</span>${x.stop && x.v !== "终止" ? `<span class="sig neg">${T("项目停止", "Stopped")}</span>` : ""}${x.edited ? `<span class="sig ana">${T("已核对", "Reviewed")}</span>` : ""}${extra || ""}</div>
    <div class="sh-main"><h3><a href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a></h3>
      ${meta ? `<div class="meta">${meta}</div>` : ""}
      ${numsHTML(x.nums)}
      ${(x.tg || []).length || x.conf ? `<div>${(x.tg || []).map(g => `<button class="sig tg" data-lsgo="${esc(g)}">${esc(g)}</button>${starBtn("t", g)}`).join("")}${x.conf ? `<span class="sig">${esc(x.conf)}</span>` : ""}</div>` : ""}
      ${x.note ? `<div class="dtl-note"><span class="who">${T("点评", "Take")}</span>${esc(x.note)}</div>` : ""}
      <div class="sm"><span class="src-tier ${x.tier === "pr" ? "pr" : ""}">${x.tier === "pr" ? T("公司新闻稿", "Press release") : T("媒体报道", "Media")}</span> ${esc(x.s)}${more ? T(` · 另见 `, ` · Also: `) + more : ""}${nct ? " · " + nct : ""} · <button class="linkish" data-cite="${esc(x.id)}">${T("复制引用", "Copy citation")}</button></div></div>
    ${st ? `<div class="sh-mol">${molImg(st, 84, x.drug)}</div>` : ""}
  </article>`;
}
function bindNewsActions(root){
  root.querySelectorAll("[data-ot]").forEach(b => { if (b._b) return; b._b = 1; b.addEventListener("click", () => openDetail("t", b.dataset.ot)); });
  root.querySelectorAll("[data-lsgo]").forEach(b => { if (b._b) return; b._b = 1; b.addEventListener("click", () => goLandscape(b.dataset.lsgo)); });
  root.querySelectorAll("[data-cite]").forEach(b => { if (b._b) return; b._b = 1; b.addEventListener("click", () => { const x = (NEWS?.items || []).find(z => z.id === b.dataset.cite); if (x) copyText(citeNews(x), b); }); });
}
function newsRows(){
  const Q = makeQ($("nw-q").value), ta = $("nw-ta").value, win = +$("nw-win").value, lg = $("nw-lang").value, pend = $("nw-pend").checked, tier = $("nw-tier").value;
  setQHint("nw-hint", Q);
  const cut = win ? new Date(Date.now() - win * 864e5).toISOString().slice(0, 10) : "";
  const base = (NEWS.items || []).filter(x => (!ta || x.ta === ta) && (!lg || x.lang === lg) && (!cut || (x.d || "") >= cut) && (!tier || (tier === "pr" ? x.tier === "pr" : tier === "num" ? (x.nums || []).length : true)) &&
    qHit(Q, [x.t, x.drug, x.co, x.nct, x.ta, x.mod, x.note, x.conf, ...(x.tg || []), ...(x.src || []).map(s => s.t)], x.tg));
  return {base, rows: base.filter(x => nwV ? x.v === nwV : (pend || x.v !== "待判定"))};
}
function renderNews(){
  if (!NEWS) { $("nw-meta").textContent = T("正在加载…", "Loading…"); Promise.all([loadNews(), loadStruct()]).then(renderNews); return; }
  if (!STRUCT) { loadStruct().then(renderNews); return; }
  if (NEWS.err) { $("nw-list").innerHTML = `<div class="empty">${T("新闻稿数据没有加载出来。直接用浏览器打开本地文件时会被拦截，部署到网站上即可正常显示。", "News data did not load. Browsers block it when the page is opened as a local file; it works once deployed.")}</div>`; $("nw-meta").textContent = ""; return; }
  $("nw-asof").textContent = NEWS.generated ? T(`更新于 ${NEWS.generated}`, `Updated ${NEWS.generated}`) : "";
  const {base, rows} = newsRows();
  const c = {}; base.forEach(x => c[x.v] = (c[x.v] || 0) + 1);
  const max = Math.max(1, ...Object.values(c));
  $("nw-bars").innerHTML = `<button class="why-row" data-nv="" aria-pressed="${nwV === ""}"><span class="wl">${T("全部判定", "All verdicts")}</span><span class="wb"><i style="width:100%;background:var(--muted)"></i></span><span class="wn">${base.length}</span></button>` +
    NV_ORDER.filter(k => c[k]).map(k => `<button class="why-row" data-nv="${esc(k)}" aria-pressed="${nwV === k}"><span class="wl">${esc(nvLabel(k))}</span><span class="wb"><i style="width:${100 * c[k] / max}%;background:var(${NV_COLOR[k]})"></i></span><span class="wn">${c[k]}</span></button>`).join("");
  $("nw-bars").querySelectorAll("[data-nv]").forEach(b => b.addEventListener("click", () => { nwV = b.dataset.nv; nwLimit = 40; renderNews(); }));
  const hidden = !nwV && !$("nw-pend").checked ? (c["待判定"] || 0) : 0;
  $("nw-meta").textContent = T(`${rows.length} 条${hidden ? `（另有 ${hidden} 条待判定已隐藏）` : ""}`, `${rows.length} items${hidden ? ` (${hidden} unclassified hidden)` : ""}`);
  $("nw-list").innerHTML = rows.length ? rows.slice(0, nwLimit).map(x => newsItemHTML(x)).join("") : `<div class="empty">${T("没有符合条件的条目，试试放宽时间范围或清空筛选。", "Nothing matches. Try a wider time range or clear the filters.")}</div>`;
  bindNewsActions($("nw-list"));
  const mb = $("nw-more"); mb.hidden = rows.length <= nwLimit; mb.textContent = T(`再显示 40 条（共 ${rows.length} 条）`, `Show 40 more (${rows.length} total)`);
}
function exportNews(){
  if (!NEWS) return;
  const {rows} = newsRows();
  downloadCSV(`hit-or-miss-topline-${todayISO()}.csv`, [T("日期", "Date"), T("判定", "Verdict"), T("标题", "Headline"), T("公司", "Company"), T("药物", "Drug"), T("分期", "Phase"), T("靶点", "Targets"), T("领域", "Area"), T("关键数字", "Key numbers"), T("会议", "Meeting"), "NCT", T("来源类型", "Source type"), T("来源", "Source"), "URL", T("点评", "Note")],
    rows.map(x => [x.d, x.v, x.t, x.co, x.drug, x.ph, (x.tg || []).join("; "), x.ta, numsPlain(x.nums), x.conf, x.nct, x.tier === "pr" ? T("公司新闻稿", "Press release") : T("媒体", "Media"), x.s, x.u, x.note]));
}
$("nw-more").addEventListener("click", () => { nwLimit += 40; renderNews(); });
["nw-q", "nw-ta", "nw-win", "nw-lang", "nw-pend", "nw-tier"].forEach(id => $(id).addEventListener("input", () => { nwLimit = 40; renderNews(); }));
$("nw-csv").addEventListener("click", exportNews);
$("sh-csv")?.addEventListener("click", () => {
  const rows = window._shRows || [];
  downloadCSV(`hit-or-miss-shelved-${todayISO()}.csv`, ["NCT", T("药物", "Drug"), T("公司", "Company"), T("分期", "Phase"), T("领域", "Area"), T("适应症", "Condition"), T("状态", "Status"), T("原因分类", "Reason"), T("原因原文", "Reason (verbatim)"), T("更新", "Updated")],
    rows.map(t => [t.nct, (t.interventions || []).slice(0, 2).join(" + "), t.group, t.phase, t.ta, (t.conditions || []).slice(0, 2).join("; "), t.status, t.why_cat, t.why, t.updated]));
});
$("wl-add").addEventListener("click", addWatchFromInput);
$("wl-in").addEventListener("keydown", e => { if (e.key === "Enter") addWatchFromInput(); });
$("wl-csv").addEventListener("click", () => {
  const rows = window._wlRows || [];
  downloadCSV(`hit-or-miss-following-${todayISO()}.csv`, [T("日期", "Date"), T("类型", "Type"), T("内容", "Item"), T("公司", "Company"), T("判定 / 状态", "Verdict / status"), T("关键数字", "Key numbers"), T("链接", "Link")],
    rows.map(o => o.kind === "es" ? [o.d, T("早期信号", "Early signal"), o.x.t, o.x.co, o.x.type, "", o.x.u] : o.kind === "nw" ? [o.d, T("新闻稿读出", "Topline news"), o.x.t, o.x.co, o.x.v, numsPlain(o.x.nums), o.x.u]
      : o.kind === "gd" ? [o.x.when, T("预计读出", "Readout due"), o.x.drug || o.x.co, o.x.co, "", "", o.x.u]
      : [o.d, T("注册库", "Registry"), o.x.acronym || o.x.title, o.x.group, o.x.as?.verdict || o.x._set, "", `${regUrl(o.x.nct)}`]));
});

/* ---------- 药物时间线（详情页 kind = "d"） ---------- */
function openDrug(key, fromHash){
  if (!NEWS || !EARLY || !STRUCT) { Promise.all([loadNews(), loadEarly(), loadStruct()]).then(() => openDrug(key, fromHash)); return; }
  const seen = new Set(), trials = [];
  [...(REG?.all || []), ...ACTIVE, ...(EARLY || [])].forEach(t => { if (seen.has(t.nct)) return; if ((t.iv || []).some(iv => ivKeys(iv).has(key))) { seen.add(t.nct); trials.push(t); } });
  const news = (NEWS.items || []).filter(x => drugKeys(x.drug).includes(key));
  const guide = (NEWS.guidance || []).filter(g => drugKeys(g.drug).includes(key));
  const cur = D.filter(d => drugKeys(d.drug).includes(key) || nk(d.drug) === key);
  const name = news[0]?.drug || ((trials[0]?.iv || []).find(iv => ivKeys(iv).has(key)) || {}).n || cur[0]?.drug || key;
  const keys = [key, ...drugKeys(name)];
  const st = structOf(keys);
  // 靶点和药物形式只从单药试验和新闻稿取，免得把联用药的靶点算进来
  const solo = trials.filter(t => (t.iv || []).filter(iv => iv.r !== "c" && !/placebo|standard of care|chemotherapy/i.test(iv.n)).length === 1);
  const base = solo.length ? solo : trials;
  const tgs = [...new Set([...news.flatMap(x => x.tg || []), ...base.flatMap(t => t.tg || (t.tgt ? [t.tgt] : []))])].slice(0, 5);
  const cos = [...new Set([...base.map(t => t.group), ...news.map(x => x.co), ...trials.map(t => t.group)].filter(Boolean))].slice(0, 6);
  const mods = [...new Set([...news.map(x => x.mod), ...base.map(t => t.mod)].filter(m => m && m !== "未识别"))].slice(0, 2);
  const ev = [];
  trials.forEach(t => {
    const lbl = t.acronym || t.title, ph = t.phase || "";
    if (t._set === "results") ev.push({d: t.results || t.pcd, ph, html: `${vchip(t)} <button class="tbtn" data-ot="${esc(t.nct)}">${esc(lbl)}</button>`, sub: `${T("注册库公布结果", "Results posted")} · ${esc(t.group)} · ${esc((t.conditions || [])[0] || "")}`});
    else if (t._set === "stopped") ev.push({d: t.updated, ph, html: `<span class="sig neg">${T("提前终止", "Stopped")}</span> <button class="tbtn" data-ot="${esc(t.nct)}">${esc(lbl)}</button>`, sub: `${esc(t.why_cat || "")}${t.why ? " · “" + esc(cut(t.why, 80)) + "”" : ""}`});
    else if (t._set === "upcoming" || t._set === "completed") ev.push({d: t.pcd, ph, html: `<span class="sig mix">${t._set === "completed" ? T("已完成待公布", "Awaiting results") : T("预计完成", "Due")}</span> <button class="tbtn" data-ot="${esc(t.nct)}">${esc(lbl)}</button>`, sub: `${esc(t.group)} · ${esc((t.conditions || [])[0] || "")}`});
    else ev.push({d: t.fp, ph, html: `<span class="sig">${t._set === "early" ? T("新登记", "Registered") : T("在研", "Ongoing")}</span> <button class="tbtn" data-ot="${esc(t.nct)}">${esc(lbl)}</button>`, sub: `${esc(t.group)} · ${esc((t.conditions || [])[0] || "")}`});
  });
  news.forEach(x => ev.push({d: x.d, ph: x.ph, html: `<span class="sig ${NV[x.v]?.[0] || ""}">${esc(nvLabel(x.v))}</span> <a href="${esc(x.u)}" target="_blank" rel="noopener">${esc(x.t)}</a>`, sub: `${x.tier === "pr" ? T("公司新闻稿", "Press release") : T("媒体", "Media")} · ${esc(x.s)}${(x.nums || []).length ? " · " + esc(numsPlain(x.nums)) : ""}`}));
  cur.forEach(d => ev.push({d: d.date, ph: d.phase, html: `<span class="verdict ${d.out}">${OUT[d.out]}</span> <button class="tbtn" data-oc="${esc(d.id)}">${esc(d.drug)} ${esc(d.trial)}</button>`, sub: `${T("精选解读", "Curated")} · ${esc(d.ind)}`}));
  (NEWS.early || []).filter(e => drugKeys(e.drug).includes(key)).forEach(e => ev.push({d: e.d, ph: "", html: `<span class="sig ana">${esc((ES_T[e.type] || (() => e.type))())}</span> <a href="${esc(e.u)}" target="_blank" rel="noopener">${esc(e.t)}</a>`, sub: `${T("早期信号", "Early signal")} · ${esc(e.s || "")}`}));
  guide.forEach(g => ev.push({d: g.start, ph: g.ph, fut: true, html: `<span class="sig mix">${T("预计读出", "Readout due")} ${esc(g.when)}</span> “${esc(g.snip)}”`, sub: `<a href="${esc(g.u)}" target="_blank" rel="noopener">${esc(g.s || T("来源", "Source"))}</a> · ${esc(g.d)}`}));
  ev.sort((a, b) => String(a.d || "").localeCompare(String(b.d || "")));
  const phs = [...new Set(trials.map(t => t.phase).filter(Boolean))].sort((a, b) => phNum(b) - phNum(a));
  const hit = trials.filter(t => t.as?.verdict === "达到").length + news.filter(x => x.v === "达到").length;
  const miss = trials.filter(t => t.as?.verdict === "未达到" || t._set === "stopped").length + news.filter(x => x.v === "未达到" || x.v === "终止").length;
  const html = `<header class="dp-head"><div class="drug-head">${st ? molImg(st, 150, name) : ""}<div>
      <div class="card-head"><span class="meta">${T("药物时间线", "Drug timeline")}</span></div>
      <h2 id="dp-title">${esc(name)} ${starBtn("d", name)}</h2>
      <div class="meta">${cos.map(esc).join(" · ")}</div>
      <div class="tags">${mods.map(m => `<span class="tag">${esc(m)}</span>`).join("")}${tgs.map(g => `<button class="tag" data-ls="${esc(g)}">${T("靶点", "Target")} ${esc(g)}</button>`).join("")}${phs[0] ? `<span class="tag">${T("最高", "Furthest")} ${esc(phs[0])}${T(" 期", "")}</span>` : ""}</div>
      ${st ? `<div class="sm smiles">SMILES <code>${esc(cut(st[1], 120))}</code> <button class="linkish" data-copysmi="${esc(st[1])}">${T("复制", "Copy")}</button>${st[2] ? ` · MW ${esc(st[2])}` : ""}</div>` : ""}
    </div></div></header>
    <section class="dp-sec"><div class="kpis mini"><div><div class="n">${trials.length}</div><div class="l">${T("注册库试验", "Registry trials")}</div></div><div><div class="n">${news.length}</div><div class="l">${T("新闻稿读出", "Topline news")}</div></div><div><div class="n"><span style="color:var(--pos)">${hit}</span> / <span style="color:var(--neg)">${miss}</span></div><div class="l">${T("成 / 败", "Hit / miss")}</div></div><div><div class="n">${guide.length}</div><div class="l">${T("待读出", "Upcoming")}</div></div></div></section>
    <section class="dp-sec"><h4>${T("时间线", "Timeline")} <small>${T("从早到晚", "oldest first")}</small></h4>
      ${ev.length ? `<ol class="drug-tl">${ev.map(e => `<li class="${e.fut ? "fut" : ""}"><span class="date">${esc(e.d || "—")}</span><span class="ph">${e.ph ? esc(String(e.ph).replace(/PHASE/gi, "").trim()) + T(" 期", "") : ""}</span><div>${e.html}<div class="sm">${e.sub}</div></div></li>`).join("")}</ol>`
        : `<p class="sm">${T("本站数据里还没有这个药的记录。", "No records for this drug in the site's data yet.")}</p>`}
    </section>
    <section class="dp-sec"><p class="sm">${T("按药名和研发代号匹配注册库试验、新闻稿和公司指引；同名不同药或改名的情况可能漏掉或混入，引用前请核对原始来源。", "Matched on drug name and code across registry trials, press releases and company guidance; renamed or similarly named drugs may be missed or mixed in, so check the original sources before citing.")}</p></section>`;
  const dp = $("detail");
  if (dp.hidden) { lastFocus = document.activeElement; }
  $("dp-crumb").textContent = `${T("药物时间线", "Drug timeline")} · ${name}`;
  $("dp-body").innerHTML = html;
  dp.hidden = false; document.documentElement.classList.add("dp-open");
  dp.scrollTop = 0; $("dp-close").focus({preventScroll: true});
  $("dp-body").querySelectorAll("[data-oc]").forEach(b => b.addEventListener("click", () => openDetail("c", b.dataset.oc)));
  $("dp-body").querySelectorAll("[data-ot]").forEach(b => b.addEventListener("click", () => openDetail("t", b.dataset.ot)));
  $("dp-body").querySelectorAll("[data-ls]").forEach(b => b.addEventListener("click", () => { closeDetail(); goLandscape(b.dataset.ls); }));
  $("dp-body").querySelectorAll("[data-copysmi]").forEach(b => b.addEventListener("click", () => copyText(b.dataset.copysmi, b)));
  const h = `d-${key}`;
  if (!fromHash && location.hash.slice(1) !== h) { try { history.pushState(null, "", "#" + h); } catch(e) { location.hash = h; } }
}
/* 试验详情页加一条工具栏：结构、药物时间线、关注、引用 */
function dpExtras(kind, id){
  if (kind !== "t") return;
  const t = byNct().get(id); if (!t) return;
  const ivs = (t.iv || []).filter(iv => iv.r !== "c" && !/placebo/i.test(iv.n)).slice(0, 3);
  const add = () => {
    if ($("dp-body").querySelector(".dp-tools")) return;
    const bar = document.createElement("section"); bar.className = "dp-sec dp-tools";
    bar.innerHTML = `${ivs.map(iv => { const ks = [...ivKeys(iv)], s = structOf(ks); return `<div class="dp-drug">${s ? molImg(s, 72, iv.n) : ""}<div><button class="more-link" data-od="${esc(ks[0] || nk(iv.n))}">${esc(cut(iv.n, 40))} ${T("的时间线", "timeline")} →</button> ${starBtn("d", iv.n.split(/[(（]/)[0].trim())}</div></div>`; }).join("")}
      <div class="dp-tools-r">${t.group ? `${starBtn("c", t.group)} <span class="sm">${T("关注", "Follow")} ${esc(t.group)}</span>` : ""} <button class="linkish" data-citet="1">${T("复制引用", "Copy citation")}</button></div>`;
    const head = $("dp-body").querySelector(".dp-head"); head ? head.after(bar) : $("dp-body").prepend(bar);
    bar.querySelector("[data-citet]").addEventListener("click", e => copyText(citeTrial(t), e.target));
  };
  if (STRUCT) add(); else loadStruct().then(() => { if (!$("detail").hidden && location.hash.slice(1) === `t-${id}`) add(); });
}

/* ---------- 读出日历 ---------- */
let calType = "";
function calRows(){
  const today = todayISO(), end = new Date(Date.now() + 400 * 864e5).toISOString().slice(0, 10);
  const rows = [];
  (NEWS?.conf || []).filter(c => c.end >= today && c.start <= end).forEach(c => rows.push({type: "conf", start: c.start, end: c.end, title: c.n, sub: `${c.full} · ${c.where}`, ta: c.ta, link: c.src, tg: [], co: "", dk: []}));
  (NEWS?.guidance || []).filter(g => g.end >= today && g.start <= end).forEach(g => rows.push({type: "guide", start: g.start, end: g.end, when: g.when, title: g.drug || g.co, sub: [g.co, g.ph && T(`${g.ph} 期`, `Ph ${g.ph}`), g.ta].filter(Boolean).join(" · "), snip: g.snip, ta: g.ta, link: g.u, src: g.s, tg: g.tg, co: g.co, dk: drugKeys(g.drug), drug: g.drug}));
  const ph2 = $("cal-ph2").checked;
  (REG?.sets?.upcoming || []).filter(t => t.pcd >= today && t.pcd <= end && (ph2 || /3/.test(t.phase))).forEach(t => {
    const dk = new Set(); (t.iv || []).forEach(iv => ivKeys(iv).forEach(k => dk.add(k)));
    const nm = String(t.acronym || ivName(t, t.mod) || t.title).replace(/^(drug|biological|combination product)\s*:\s*/i, "");
    rows.push({type: "reg", start: t.pcd, end: t.pcd, title: cut(nm, 60), sub: `${t.group} · ${T(`${t.phase} 期`, `Ph ${t.phase}`)} · ${(t.conditions || [])[0] || ""}${t.n ? T(` · ${t.n} 例`, ` · n=${t.n}`) : ""}${t.acronym ? "" : " · " + cut(t.title, 70)}`, ta: t.ta, nct: t.nct, tg: t.tg || [], co: t.group, dk: [...dk]});
  });
  const Q = makeQ($("cal-q").value), ta = $("cal-ta").value, mine = $("cal-mine").checked, w = getWatch();
  setQHint("cal-hint", Q);
  return rows.filter(r => (!calType || r.type === calType) && (!ta || r.ta === ta || (r.type === "conf" && !r.ta)) &&
      (!mine || r.type === "conf" || w.some(x => watchHit(x, r))) && qHit(Q, [r.title, r.sub, r.snip, r.co, r.drug, r.nct, ...(r.tg || [])], r.tg))
    .sort((a, b) => a.start.localeCompare(b.start) || a.type.localeCompare(b.type));
}
const CAL_T = {conf: () => T("会议", "Meeting"), guide: () => T("公司指引", "Company guidance"), reg: () => T("注册库完成日", "Registry completion")};
function renderCal(){
  if (!NEWS) { $("cal-list").innerHTML = `<div class="empty">${T("正在加载…", "Loading…")}</div>`; loadNews().then(renderCal); return; }
  if (!REG) return;
  const rows = calRows(), byM = new Map();
  rows.forEach(r => { const m = r.start.slice(0, 7); if (!byM.has(m)) byM.set(m, []); byM.get(m).push(r); });
  const cnt = {}; rows.forEach(r => cnt[r.type] = (cnt[r.type] || 0) + 1);
  $("cal-types").innerHTML = [["", T("全部", "All")], ["conf", CAL_T.conf()], ["guide", CAL_T.guide()], ["reg", CAL_T.reg()]].map(([k, l]) => `<button class="chip-btn" data-ct="${k}" aria-pressed="${calType === k}">${esc(l)}${k && cnt[k] != null ? ` <b>${cnt[k]}</b>` : ""}</button>`).join("");
  $("cal-types").querySelectorAll("[data-ct]").forEach(b => b.addEventListener("click", () => { calType = b.dataset.ct; renderCal(); }));
  $("cal-meta").textContent = T(`${rows.length} 条`, `${rows.length} items`);
  const fmtM = m => { const [y, mo] = m.split("-"); return EN ? new Date(+y, +mo - 1, 1).toLocaleString("en-US", {month: "long", year: "numeric"}) : `${y} 年 ${+mo} 月`; };
  $("cal-list").innerHTML = rows.length ? [...byM.entries()].map(([m, rs]) => `<section class="cal-month"><h3>${esc(fmtM(m))} <small>${rs.length}</small></h3>${rs.map(r => `
    <div class="cal-row ${r.type}"><span class="date">${esc(r.type === "guide" ? r.when : r.start === r.end ? r.start.slice(5) : `${r.start.slice(5)} – ${r.end.slice(5)}`)}</span><span class="sig ${r.type === "conf" ? "ana" : r.type === "guide" ? "mix" : ""}">${esc(CAL_T[r.type]())}</span>
      <div><b>${r.type === "reg" ? `<button class="tbtn" data-ot="${esc(r.nct)}">${esc(r.title)}</button>` : r.drug ? `<button class="tbtn" data-od="${esc(r.dk[0] || "")}">${esc(r.title)}</button>` : r.link ? `<a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title)}</b>${r.type !== "conf" && r.co ? starBtn("c", r.co) : ""}
        <div class="sm">${esc(r.sub)}${(r.tg || []).length ? " · " + r.tg.map(esc).join(" / ") : ""}</div>${r.snip ? `<div class="sm">“${esc(r.snip)}” <a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.src || T("来源", "Source"))}</a></div>` : ""}</div></div>`).join("")}</section>`).join("")
    : `<div class="empty">${T("没有符合条件的条目。", "Nothing matches.")}</div>`;
  $("cal-list").querySelectorAll("[data-ot]").forEach(b => b.addEventListener("click", () => openDetail("t", b.dataset.ot)));
  window._calRows = rows;
}
function exportCal(kind){
  const rows = window._calRows || [];
  if (kind === "csv") return downloadCSV(`hit-or-miss-calendar-${todayISO()}.csv`, [T("开始", "Start"), T("结束", "End"), T("类型", "Type"), T("名称", "Name"), T("说明", "Details"), T("指引原文", "Guidance"), "NCT", T("链接", "Link")],
    rows.map(r => [r.start, r.end, CAL_T[r.type](), r.title, r.sub, r.snip, r.nct, r.link || (r.nct ? `${regUrl(r.nct)}` : "")]));
  const d8 = s => s.replace(/-/g, ""), next = s => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10); };
  const escI = s => String(s || "").replace(/[\\;,]/g, m => "\\" + m).replace(/\n/g, "\\n");
  const ev = rows.map((r, i) => ["BEGIN:VEVENT", `UID:hom-${d8(r.start)}-${i}-${nk(r.title).slice(0, 20)}@hit-or-miss`, `DTSTAMP:${d8(todayISO())}T000000Z`,
    `DTSTART;VALUE=DATE:${d8(r.type === "guide" ? r.end : r.start)}`, `DTEND;VALUE=DATE:${d8(next(r.type === "guide" ? r.end : r.end))}`,
    `SUMMARY:${escI((r.type === "guide" ? T("预计读出（最晚）", "Readout due (latest) ") + r.when + " · " : r.type === "reg" ? T("III 期完成 · ", "Completion · ") : "") + r.title)}`,
    `DESCRIPTION:${escI([r.sub, r.snip, r.link || (r.nct ? regUrl(r.nct) : "")].filter(Boolean).join("\n"))}`, "END:VEVENT"].join("\r\n"));
  downloadFile(`hit-or-miss-calendar-${todayISO()}.ics`, ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Hit or Miss//Readout calendar//EN", "CALSCALE:GREGORIAN", ...ev, "END:VCALENDAR"].join("\r\n"), "text/calendar;charset=utf-8");
}
["cal-q", "cal-ta", "cal-mine", "cal-ph2"].forEach(id => $(id).addEventListener("input", renderCal));
$("cal-csv").addEventListener("click", () => exportCal("csv"));
$("cal-ics").addEventListener("click", () => exportCal("ics"));

/* ---------- 对比表：治疗领域页和靶点页 ---------- */
function cmpTableRows(trialFilter, newsFilter){
  const M = byNct(), out = [];
  (EMB?.cmp || []).forEach(c => {
    const t = M.get(c.n); if (!t || !trialFilter(t)) return;
    const res = c.k === "r" ? `${c.s} ${fmtV(c.v)}${c.lo != null ? ` (${fmtV(c.lo)}–${fmtV(c.hi)})` : ""}` : c.k === "p" ? `${fmtV(c.x[1])}% vs ${fmtV(c.c[1])}%` : `${fmtV(c.x[1])} vs ${fmtV(c.c[1])} ${T("个月", "mo")}`;
    const diff = c.k === "r" ? "" : `${c.x[1] - c.c[1] >= 0 ? "+" : ""}${fmtV(c.x[1] - c.c[1])}${c.k === "p" ? T(" 个百分点", " pp") : T(" 个月", " mo")}`;
    out.push({src: "reg", d: t.results || t.pcd || "", trial: trialLbl(t), drug: ivName(t, t.mod), co: t.group, cond: condOf(t), ph: t.phase, ep: c.e, res, diff, p: c.p != null ? fmtP(c.p) : "", v: t.as?.verdict || "", nct: t.nct, link: `${regUrl(t.nct)}`});
  });
  (NEWS?.items || []).filter(x => (x.nums || []).length && newsFilter(x)).forEach(x => {
    const ns = x.nums.filter(n => n.k !== "p");
    out.push({src: "news", d: x.d, trial: cut(x.t, 70), drug: x.drug, co: x.co, cond: x.ta, ph: x.ph, ep: ns.map(n => NUM_LBL[n.k]?.[0] || n.k).join(" / "), res: ns.map(numTxt).join(" · "), diff: "", p: (x.nums.find(n => n.k === "p") || {}).v ? "p" + x.nums.find(n => n.k === "p").v : "", v: x.v, nct: x.nct || "", link: x.u});
  });
  return out.sort((a, b) => String(b.d).localeCompare(String(a.d)));
}
function cmpTableHTML(rows, id){
  if (!rows.length) return `<p class="sm">${T("这个范围里没有可比的数字。", "No comparable numbers in this selection.")}</p>`;
  return `<div class="tbl-tools"><button class="more-link" data-cmpcsv="${id}">${T("导出 CSV", "Export CSV")}</button> <button class="more-link" data-cmptsv="${id}">${T("复制为表格（可粘贴进 Excel / PPT）", "Copy as table (paste into Excel / PPT)")}</button> <span class="sm">${T(`${rows.length} 行；不同试验的人群和终点定义不同，横向比较只作参考`, `${rows.length} rows; populations and endpoint definitions differ across trials, so treat comparisons as indicative`)}</span></div>
    <div class="tbl-wrap"><table class="cmp-tbl"><thead><tr><th>${T("日期", "Date")}</th><th>${T("试验 / 药物", "Trial / drug")}</th><th>${T("公司", "Company")}</th><th>${T("适应症", "Indication")}</th><th>${T("终点", "Endpoint")}</th><th>${T("结果", "Result")}</th><th>${T("差值", "Diff")}</th><th>p</th><th>${T("判定", "Verdict")}</th><th>${T("来源", "Source")}</th></tr></thead><tbody>
    ${rows.slice(0, 300).map(r => `<tr><td class="sm">${esc(r.d)}</td><td>${r.src === "reg" ? `<button class="tbtn" data-ot="${esc(r.nct)}">${esc(r.trial)}</button><div class="sm">${esc(cut(r.drug, 40))}</div>` : `<a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.drug || r.trial)}</a><div class="sm">${esc(r.trial)}</div>`}</td><td class="sm">${esc(r.co)}</td><td class="sm">${esc(cut(r.cond, 40))}</td><td class="sm">${esc(cut(r.ep, 60))}</td><td><b>${esc(r.res)}</b></td><td class="sm">${esc(r.diff)}</td><td class="sm">${esc(r.p)}</td><td class="sm">${esc(r.v)}</td><td class="sm">${r.src === "reg" ? T("注册库", "Registry") : T("新闻稿", "News")}</td></tr>`).join("")}</tbody></table></div>`;
}
const CMP_HEAD = () => [T("日期", "Date"), T("来源", "Source"), T("试验", "Trial"), T("药物", "Drug"), T("公司", "Company"), T("适应症", "Indication"), T("分期", "Phase"), T("终点", "Endpoint"), T("结果", "Result"), T("差值", "Diff"), "p", T("判定", "Verdict"), "NCT", T("链接", "Link")];
const cmpRowArr = r => [r.d, r.src === "reg" ? T("注册库", "Registry") : T("新闻稿", "News"), r.trial, r.drug, r.co, r.cond, r.ph, r.ep, r.res, r.diff, r.p, r.v, r.nct, r.link];
const CMP_CACHE = {};
function bindCmp(root){
  root.querySelectorAll("[data-cmpcsv]").forEach(b => b.addEventListener("click", () => downloadCSV(`hit-or-miss-compare-${b.dataset.cmpcsv}-${todayISO()}.csv`, CMP_HEAD(), (CMP_CACHE[b.dataset.cmpcsv] || []).map(cmpRowArr))));
  root.querySelectorAll("[data-cmptsv]").forEach(b => b.addEventListener("click", () => copyText([CMP_HEAD(), ...(CMP_CACHE[b.dataset.cmptsv] || []).map(cmpRowArr)].map(r => r.map(v => String(v ?? "").replace(/\t|\n/g, " ")).join("\t")).join("\n"), b)));
  root.querySelectorAll("[data-ot]").forEach(b => { if (b._b) return; b._b = 1; b.addEventListener("click", () => openDetail("t", b.dataset.ot)); });
}
/* 治疗领域页底部 */
function taCmpExtra(){
  const body = $("ta-body"); if (!body) return;
  const draw = () => {
    if (!taCur) return;
    const inArea = new Set(taRows().map(t => t.nct)), Q = (taQ || "").toLowerCase(), cond = (taCond || "").toLowerCase();
    const rows = cmpTableRows(t => inArea.has(t.nct), x => x.ta === taCur && (!Q || [x.t, x.drug, x.co].join(" ").toLowerCase().includes(Q)) && (!cond || x.t.toLowerCase().includes(cond)));
    CMP_CACHE.area = rows;
    let sec = $("ta-cmp");
    if (!sec) { sec = document.createElement("section"); sec.className = "pg-sec"; sec.id = "ta-cmp"; sec.style.marginTop = "14px"; body.appendChild(sec); }
    sec.innerHTML = `<h3>${T("对比表", "Comparison table")} <small>${T("注册库主要终点 + 新闻稿关键数字", "Registry primary endpoints + topline news numbers")}</small></h3>${cmpTableHTML(rows, "area")}`;
    bindCmp(sec);
  };
  if (NEWS) draw(); else loadNews().then(draw);
}
/* 靶点页「对比」分页 */
function tgCmp(g){
  if (!NEWS) { loadNews().then(() => { if (tgCur === g && tgTab === "cmp") renderTgBody(); }); return `<div class="empty">${T("正在加载…", "Loading…")}</div>`; }
  const rows = cmpTableRows(t => (t.tg || []).includes(g) || t.tgt === g, x => (x.tg || []).includes(g));
  CMP_CACHE.target = rows;
  setTimeout(() => bindCmp($("tg-body")), 0);
  return `<section class="pg-sec"><h3>${esc(g)} · ${T("对比表", "Comparison table")} ${starBtn("t", g)}</h3><p class="sub">${T("这个靶点上各试验登记的主要终点效应量、应答率、中位时间，加上新闻稿里抽出的关键数字。", "Registered primary-endpoint effects, response rates and medians for trials on this target, plus key numbers pulled from topline news.")}</p>${cmpTableHTML(rows, "target")}</section>`;
}

/* ---------- 早期信号（IND、首例给药、首次人体、临床前数据、候选药物）：靶点页底部 ---------- */
const ES_T = {"IND": () => "IND", "首例给药": () => T("首例给药", "First dosed"), "首次人体": () => T("首次人体", "First-in-human"), "临床前数据": () => T("临床前数据", "Preclinical data"), "候选药物": () => T("候选药物", "Candidate")};
function earlyItemHTML(e){
  const dk = drugKeys(e.drug)[0] || "";
  return `<li><span class="date">${esc(e.d)}</span> <span class="sig ana">${esc((ES_T[e.type] || (() => e.type))())}</span> <a href="${esc(e.u)}" target="_blank" rel="noopener">${esc(e.t)}</a>
    <div class="sm">${[e.co ? `<b>${esc(e.co)}</b>` : "", e.drug ? `<button class="tbtn" data-od="${esc(dk)}">${esc(e.drug)}</button>` : "", e.mod ? esc(e.mod) : "", esc(e.s || "")].filter(Boolean).join(" · ")}</div></li>`;
}
function tgEarlyFill(g){
  const el = $("tg-body"); if (!el) return;
  const draw = () => {
    if (tgCur !== g || tgTab !== "clin") return;
    const rows = (NEWS?.early || []).filter(e => (e.tg || []).includes(g));
    let sec = $("tg-early");
    if (!sec) { sec = document.createElement("section"); sec.className = "pg-sec"; sec.id = "tg-early"; sec.style.marginTop = "14px"; el.appendChild(sec); }
    sec.innerHTML = `<h3>${T("早期信号", "Early signals")} <small>${T("IND、首例给药、首次人体、临床前数据，来自新闻稿；注册库里往往还没有", "IND, first dosing, first-in-human, preclinical data from press releases; often not in registries yet")}</small></h3>
      ${rows.length ? `<ol class="pg-list">${rows.slice(0, 20).map(earlyItemHTML).join("")}</ol>` : `<p class="sm">${T("最近两年的新闻稿里还没有这个靶点的早期信号。", "No early signals for this target in the past two years of press releases.")}</p>`}`;
  };
  if (NEWS) draw(); else loadNews().then(draw);
}
