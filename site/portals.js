/* ====================================================================
   三个入口：靶点（药化 / CADD）· 治疗领域（医生）· 并购（BD）
   这段代码在构建时插进 template.html，和老代码共用 REG / EARLY / D / TGS 等全局变量。
   ==================================================================== */
const PHN = p => PH_LBL[Math.min(4, p)] || "—";
const pctS = v => v == null ? "—" : Math.round(v) + "%";
const cut = (s, n) => { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
const enc = encodeURIComponent;
function svgEl(W, H, label){ return `<svg xmlns="${SVGNS}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`; }

/* ---------------- 靶点索引 ---------------- */
let TGX = null, tgxLimit = 60, tgCur = null, tgTab = "clin", tgPatCtx = "all", tgPatYr = "";
let FEEDS = null, feedsP = null;
function loadFeeds(){
  if (FEEDS) return Promise.resolve(FEEDS);
  if (feedsP) return feedsP;
  feedsP = fetch("feeds.json", {cache:"no-cache"}).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(j => (FEEDS = j)).catch(() => (FEEDS = {targets:{}}));
  return feedsP;
}
function tgxRows(){
  if (TGX) return TGX;
  const rows = lsBuild("", "");
  const pre = new Map(); (EMB?.pre?.cur?.areas || []).forEach(a => a.items.forEach(x => pre.set(x.tg, {...x, area:a._zh || a.name})));
  rows.forEach(r => { if (pre.has(r.g)) r.pre = pre.get(r.g); });
  const have = new Set(rows.map(r => r.g));
  pre.forEach((x, g) => { if (!have.has(g)) rows.push({g, ps:[], nco:0, maxPh:0, tag:"临床前", pre:x, bins:[0,0,0,0], mg:{}, hit:0, miss:0, stop:0, ev:[], newN:0, tas:{[x.area || "肿瘤"]:1}}); });
  TGX = rows; return rows;
}
function tgxFill(){
  if ($("tgx-ta").options.length) return;
  const tas = taOrder(REG.all);
  $("tgx-ta").innerHTML = `<option value="">${T("全部领域", "All areas")}</option>` + tas.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
}
function renderTgx(){
  if (!REG) return;
  if (tgCur) return;          // 当前在靶点详情页
  tgxFill();
  if (!EARLY) { $("tgx-meta").textContent = T("正在加载早期试验…", "Loading early-phase trials…"); loadEarly().then(() => { TGX = null; renderTgx(); }); return; }
  const Q = makeQ($("tgx-q").value), ta = $("tgx-ta").value, fm = $("tgx-mod").value, ph = $("tgx-ph").value, sort = $("tgx-sort").value;
  setQHint("tgx-hint", Q);
  let rows = tgxRows().filter(r => (!ta || r.tas[ta]) && (!fm || r.mg[fm]) &&
    (!ph || (ph === "3" ? r.maxPh >= 2.5 : ph === "2" ? r.maxPh >= 2 && r.maxPh < 2.5 : ph === "1" ? r.maxPh > 0 && r.maxPh < 2 : !r.ps.length)) &&
    qHit(Q, [r.g, ...(TGS.alias[r.g] || []), ...r.ps.map(p => p.co + " " + p.drug)], [r.g]));
  const key = {prog:r => r.ps.length * 10 + (r.pre ? 5 : 0), co:r => r.nco, new:r => r.newN}[sort];
  rows.sort(sort === "az" ? (a, b) => a.g.localeCompare(b.g) : (a, b) => key(b) - key(a) || a.g.localeCompare(b.g));
  $("tgx-meta").textContent = T(`${rows.length} 个靶点`, `${rows.length} targets`);
  $("tgx-grid").innerHTML = rows.slice(0, tgxLimit).map(r => {
    const tas = Object.entries(r.tas).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k]) => esc(k)).join(" · ");
    const chip = r.ps.length ? tagChip(r) : `<span class="ls-tag" style="background:var(--accent-soft);color:var(--accent)">${T("临床前精选", "Preclinical pick")}</span>`;
    const ev = r.hit || r.miss || r.stop ? `<span>${T("读出", "Readouts")} <b style="color:var(--pos)">${r.hit}</b>/<b style="color:var(--neg)">${r.miss + r.stop}</b></span>` : "";
    return `<button class="tgx-card" data-tgo="${esc(r.g)}"><div class="tgx-top"><h3>${esc(r.g)}</h3>${chip}</div>
      <div class="sm">${tas}${r.pre && r.ps.length ? ` · ${T("另有临床前精选", "also a preclinical pick")}` : ""}</div>
      ${r.ps.length ? `<div class="nums"><span><b>${r.ps.length}</b> ${T("项目", "programs")}</span><span><b>${r.nco}</b> ${T("公司", "companies")}</span><span>${T("最高", "max Ph")} <b>${PHN(r.maxPh)}</b>${T(" 期", "")}</span>${ev}</div>
      <div class="ph">${r.bins.map((v, i) => v ? `<i style="flex:${v};background:${phCol(i)}"></i>` : "").join("")}</div>`
      : `<div class="nums"><span>${esc(r.pre?.tag || "")}</span></div>`}</button>`;
  }).join("") || `<div class="empty">${T("没有符合条件的靶点，试试清空筛选。", "No targets match. Try clearing the filters.")}</div>`;
  $("tgx-grid").querySelectorAll("[data-tgo]").forEach(b => b.addEventListener("click", () => openTarget(b.dataset.tgo)));
  const more = $("tgx-more"); more.hidden = rows.length <= tgxLimit;
  more.textContent = T(`再显示 60 个（共 ${rows.length} 个）`, `Show 60 more (${rows.length} total)`);
}
$("tgx-more").addEventListener("click", () => { tgxLimit += 60; renderTgx(); });
["tgx-q","tgx-ta","tgx-mod","tgx-ph","tgx-sort"].forEach(id => $(id).addEventListener("input", () => { tgxLimit = 60; renderTgx(); }));

/* ---------------- 靶点详情页 ---------------- */
function tgTerms(g){
  let base = [];
  if (!CJK.test(g)) {
    const inner = (g.match(/[（(]([^）)]+)[）)]/) || [])[1];
    base = g.replace(/[（(][^）)]*[）)]/g, "").split(/\s*\/\s*/).map(x => x.trim()).filter(Boolean);
    if (inner && !CJK.test(inner) && !/泛|其他|pan/i.test(inner)) base.push(...inner.split(/\s*\/\s*/));
  }
  const al = (TGS.alias[g] || []).filter(a => !CJK.test(a) && !/^programmed|^anti/i.test(a) || /^[A-Za-z0-9-]{2,12}$/.test(a));
  const terms = [...new Set([...base, ...al].map(x => x.trim()).filter(x => x.length >= 2 && !CJK.test(x)))];
  const strong = terms.filter(x => x.length >= 4 || /\d/.test(x));
  return (strong.length ? strong : terms).slice(0, 5);
}
const orQ = (terms, suf) => "(" + terms.map(x => `"${x}"${suf || ""}`).join(" OR ") + ")";
const PAT_CTX = {
  all: ["全部", "All", ""],
  sm: ["小分子", "Small molecule", '(inhibitor OR antagonist OR agonist OR compound OR "small molecule")'],
  ab: ["抗体 / ADC", "Antibody / ADC", '(antibody OR bispecific OR "antibody-drug conjugate" OR "antigen-binding")'],
  deg: ["降解剂", "Degrader", '(degrader OR PROTAC OR "molecular glue" OR "protein degradation")'],
  na: ["核酸", "Nucleic acid", '(siRNA OR antisense OR oligonucleotide OR mRNA)']
};
function closeTarget(fromHash){
  tgCur = null;
  $("tgx-page").hidden = true; $("tgx-index").hidden = false;
  if (!fromHash) { try { history.pushState(null, "", "#tgx"); } catch(e) {} }
  renderTgx();
}
function openTarget(g, fromHash){
  if (!REG) return;
  if (!EARLY) { $("tgx-page").hidden = false; $("tgx-index").hidden = true; $("tgx-page").innerHTML = `<div class="empty">${T("正在加载…", "Loading…")}</div>`; loadEarly().then(() => { TGX = null; openTarget(g, true); }); return; }
  if (curTab !== "tgx") showTab("tgx", {hash:false});
  if (tgCur !== g) { tgTab = "clin"; }
  tgCur = g;
  $("tgx-index").hidden = true; $("tgx-page").hidden = false;
  const h = "#target/" + enc(g);
  if (!fromHash && location.hash !== h) { try { history.pushState(null, "", h); } catch(e) { location.hash = h; } }
  renderTargetPage();
  window.scrollTo({top: $("panel-tgx").getBoundingClientRect().top + window.scrollY - 10});
  loadFeeds().then(() => { if (tgCur === g && (tgTab === "lit" || tgTab === "news")) renderTargetPage(); else if (tgCur === g) updTgTabs(); });
}
function tgData(g){
  const r = tgxRows().find(x => x.g === g) || {g, ps:[], nco:0, maxPh:0, tag:"", bins:[0,0,0,0], mg:{}, hit:0, miss:0, stop:0, ev:[], newN:0, tas:{}};
  const inTg = t => (t.tg || []).includes(g) || t.tgt === g;
  const up = (REG.sets.upcoming || []).concat(REG.sets.completed || []).filter(inTg).sort((a, b) => String(a.pcd).localeCompare(String(b.pcd)));
  const cur = D.filter(d => (d.tg || []).includes(g) || d.tgt === g);
  const ma = (EMB?.ma?.deals || []).filter(d => (d.tg || []).includes(g));
  const Qg = makeQ(g);
  const cand = ["acquire", "license"].flatMap(k => (EMB?.deals?.[k] || []).flatMap(a => a.items.map(x => ({...x, kind:k, area:a.name}))))
    .filter(x => qHit(Qg, [x.asset, x.mech]));
  const fd = FEEDS?.targets?.[g];
  return {r, up, cur, ma, cand, fd};
}
function updTgTabs(){
  if (!tgCur) return;
  const {r, ma, cand, fd} = tgData(tgCur);
  const n = {clin: r.ps.length, pat: "", lit: fd?.lit?.total != null ? fd.lit.total.toLocaleString() : "", news: fd ? (fd.news?.en?.length || 0) + (fd.news?.zh?.length || 0) : "", deal: ma.length + cand.length || ""};
  document.querySelectorAll("[data-tgt]").forEach(b => { const k = b.dataset.tgt; const el = b.querySelector("b"); if (el) el.textContent = n[k] === "" || n[k] == null ? "" : n[k]; });
}
function renderTargetPage(){
  const g = tgCur, {r, up, cur, ma, cand, fd} = tgData(g);
  const al = (TGS.alias[g] || []).filter(a => a.toLowerCase() !== g.toLowerCase()).slice(0, 12);
  const drugs = (TGS.drugs[g] || []);
  const tas = Object.entries(r.tas).sort((a, b) => b[1] - a[1]).map(([k]) => `<span class="tag">${esc(k)}</span>`).join("");
  const TABS_T = [["clin", T("临床", "Clinical")], ["pat", T("专利", "Patents")], ["lit", T("文献", "Literature")], ["news", T("新闻", "News")], ["deal", T("交易", "Deals")]];
  let html = `<div class="crumb"><button id="tg-back">← ${T("全部靶点", "All targets")}</button><span>/</span><span>${esc(g)}</span></div>
    <header class="pg-head"><h2>${esc(g)}</h2>
      ${al.length ? `<div class="alias">${T("别名：", "Also known as: ")}${al.map(esc).join(" · ")}</div>` : ""}
      ${drugs.length ? `<div class="alias">${T("已知药物：", "Known drugs: ")}${drugs.slice(0, 14).map(esc).join(" · ")}${drugs.length > 14 ? " …" : ""}</div>` : ""}
      <div class="tags">${tas}${r.ps.length ? tagChip(r) : ""}${r.pre ? `<span class="ls-tag" style="background:var(--accent-soft);color:var(--accent)">${T("临床前精选", "Preclinical pick")} · ${esc(r.pre.tag)}</span>` : ""}</div>
      <div class="kpis">
        <div><div class="n">${r.ps.length}</div><div class="l">${T("临床项目", "Clinical programs")}</div></div>
        <div><div class="n">${r.nco}</div><div class="l">${T("公司", "Companies")}</div></div>
        <div><div class="n">${r.ps.length ? PHN(r.maxPh) : "—"}</div><div class="l">${T("最高阶段", "Furthest phase")}</div></div>
        <div><div class="n">${r.newN}</div><div class="l">${T("近 12 个月新进", "New in last 12 months")}</div></div>
        <div><div class="n"><span style="color:var(--pos)">${r.hit}</span> / <span style="color:var(--neg)">${r.miss + r.stop}</span></div><div class="l">${T("II/III 期读出 成 / 败", "Ph 2/3 readouts hit / miss")}</div></div>
      </div></header>
    <div class="pg-tabs" role="tablist">${TABS_T.map(([k, l]) => `<button role="tab" data-tgt="${k}" aria-selected="${tgTab === k}">${l}<b></b></button>`).join("")}</div>
    <div id="tg-body"></div>`;
  $("tgx-page").innerHTML = html;
  $("tg-back").addEventListener("click", () => closeTarget());
  document.querySelectorAll("[data-tgt]").forEach(b => b.addEventListener("click", () => { tgTab = b.dataset.tgt; document.querySelectorAll("[data-tgt]").forEach(x => x.setAttribute("aria-selected", x === b)); renderTgBody(); }));
  updTgTabs(); renderTgBody();
}
function renderTgBody(){
  const g = tgCur, D_ = tgData(g), el = $("tg-body");
  const f = {clin:tgClin, pat:tgPat, lit:tgLit, news:tgNews, deal:tgDeal}[tgTab];
  el.innerHTML = f(g, D_);
  el.querySelectorAll("[data-ot]").forEach(b => b.addEventListener("click", () => openDetail("t", b.dataset.ot)));
  el.querySelectorAll("[data-oc]").forEach(b => b.addEventListener("click", () => openDetail("c", b.dataset.oc)));
  el.querySelectorAll("[data-ls]").forEach(b => b.addEventListener("click", () => goLandscape(b.dataset.ls)));
  el.querySelectorAll("[data-pctx]").forEach(b => b.addEventListener("click", () => { tgPatCtx = b.dataset.pctx; renderTgBody(); }));
  el.querySelectorAll("[data-pyr]").forEach(b => b.addEventListener("click", () => { tgPatYr = b.dataset.pyr; renderTgBody(); }));
  el.querySelectorAll("[data-progall]").forEach(b => b.addEventListener("click", () => { b.closest(".pg-sec").querySelectorAll("tr[hidden]").forEach(tr => tr.hidden = false); b.remove(); }));
  el.querySelectorAll("[data-gotg]").forEach(b => b.addEventListener("click", () => { closeDetail(true); openTarget(b.dataset.gotg); }));
}
function tgClin(g, {r, up, cur}){
  const ps = r.ps.slice().sort((a, b) => b.ph - a.ph || a.co.localeCompare(b.co));
  const prog = ps.length ? `<table class="ls-progs"><thead><tr><th>${T("阶段", "Phase")}</th><th>${T("公司", "Company")}</th><th>${T("药物", "Drug")}</th><th>${T("形式", "Modality")}</th><th>${T("首次登记", "First posted")}</th></tr></thead><tbody>${ps.map((p, i) => {
      const lt = p.trials.slice().sort((a, b) => phNum(b.phase) - phNum(a.phase) || String(b.fp || "").localeCompare(String(a.fp || "")))[0];
      return `<tr${i >= 40 ? " hidden" : ""}><td class="phb">${PHN(p.ph)}</td><td>${esc(p.co)}</td><td><button class="tbtn" data-ot="${esc(lt.nct)}">${esc(p.drug)}</button>${p.trials.length > 1 ? ` <span class="sm">${T(`${p.trials.length} 项试验`, `${p.trials.length} trials`)}</span>` : ""}</td><td class="sm">${esc(p.m || "")}</td><td class="sm">${esc(p.first === "9999" ? "—" : p.first)}</td></tr>`; }).join("")}</tbody></table>
      ${ps.length > 40 ? `<button class="more" data-progall>${T(`显示全部 ${ps.length} 个项目`, `Show all ${ps.length} programs`)}</button>` : ""}`
    : `<p class="sm">${T("本站临床试验数据里还没有以这个靶点为对象的项目。", "No clinical programs against this target in the site's trial data yet.")}</p>`;
  const evs = [...cur.map(d => ({d})), ...r.ev.filter(e => !e.d)];
  const evHTML = evs.length ? `<ol class="pg-list">${evs.slice(0, 14).map(e => e.d
      ? `<li><span class="verdict ${e.d.out}">${OUT[e.d.out]}</span> <button class="tbtn" data-oc="${esc(e.d.id)}">${esc(e.d.drug)} ${esc(e.d.trial)}</button><div class="sm">${esc(e.d.sponsor)} · ${esc(e.d.ind)} · ${esc(e.d.disp)}</div></li>`
      : `<li>${e.r === "stop" ? `<span class="vd neg">${T("终止", "Stopped")}</span>` : vchip(e.t)} <button class="tbtn" data-ot="${esc(e.t.nct)}">${esc(e.t.acronym || (e.t.interventions || [])[0] || e.t.title)}</button><div class="sm">${esc(e.t.group)} · ${esc(e.t.phase)}${T(" 期", "")} · ${esc((e.t.conditions || [])[0] || "")}${e.r === "stop" && e.t.why_cat ? ` · ${esc(e.t.why_cat)}` : ""}</div></li>`).join("")}</ol>`
    : `<p class="sm">${T("还没有 II/III 期读出。", "No phase 2/3 readouts yet.")}</p>`;
  const upHTML = up.length ? `<ol class="pg-list">${up.slice(0, 10).map(t => `<li><span class="date">${esc(t.pcd)}</span> <button class="tbtn" data-ot="${esc(t.nct)}">${esc(t.acronym || (t.interventions || [])[0] || t.title)}</button><div class="sm">${esc(t.group)} · ${esc(t.phase)}${T(" 期", "")}${t.n ? T(` · ${t.n} 例`, ` · n=${t.n}`) : ""} · ${t._set === "completed" ? T("已完成，待公布", "completed, awaiting results") : T("预计完成", "expected completion")}</div></li>`).join("")}</ol>`
    : `<p class="sm">${T("未来半年没有到期的 III 期试验，也没有刚完成待公布的。", "No phase 3 trials due in the next six months and none awaiting results.")}</p>`;
  const cos = new Map(); r.ps.forEach(p => { const c = cos.get(p.co) || {n:0, ph:0}; c.n++; c.ph = Math.max(c.ph, p.ph); cos.set(p.co, c); });
  const coHTML = [...cos.entries()].sort((a, b) => b[1].ph - a[1].ph || b[1].n - a[1].n).slice(0, 14).map(([k, v]) => `<div class="cobar"><span>${esc(k)}</span><span class="sm">${T(`${v.n} 个 · 最高 ${PHN(v.ph)} 期`, `${v.n} · max Ph ${PHN(v.ph)}`)}</span></div>`).join("");
  const maxB = Math.max(1, ...r.bins);
  const fun = `<div class="funnel">${r.bins.map((v, i) => `<div><span>${PH_BINS[i]}${T(" 期", "")}</span><span class="b" style="width:${100 * v / maxB}%;background:${phCol(i)}"></span><b>${v}</b></div>`).join("")}</div>`;
  const mg = Object.entries(r.mg).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<span class="tag">${esc(k)} ${v}</span>`).join("");
  const pre = r.pre ? `<section class="pg-sec"><h3>${T("临床前精选", "Preclinical pick")} <small>${esc(r.pre.tag)}</small></h3>
      <p class="sm">${esc(r.pre.full || "")}</p><div class="pre-pop"><b>${T("人群：", "Population: ")}</b>${esc(r.pre.pop)}</div>
      <div class="pre-cols" style="margin-top:8px"><div><b>${T("证据", "Evidence")}</b>${esc(r.pre.ev)}</div><div><b>${T("化学现状", "Chemistry")}</b>${esc(r.pre.chem)}</div><div><b>${T("风险", "Risks")}</b>${esc(r.pre.risk)}</div></div>
      <div class="pre-src" style="margin-top:6px">${(r.pre.refs || []).map(([n, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(n)}</a>`).join(" · ")}</div></section>` : "";
  return `<div class="pg-grid"><div>
      <section class="pg-sec"><h3>${T("临床项目", "Clinical programs")} <small>${T(`${ps.length} 个项目 · ${r.nco} 家公司，同一公司的同一个药算一个项目`, `${ps.length} programs · ${r.nco} companies; one drug per company counts once`)}</small></h3>${prog}</section>
      <section class="pg-sec"><h3>${T("II/III 期读出", "Phase 2/3 readouts")}</h3>${evHTML}</section>
      <section class="pg-sec"><h3>${T("接下来要读出的", "Coming up")}</h3>${upHTML}</section>
    </div><div>
      ${pre}
      ${r.ps.length ? `<section class="pg-sec"><h3>${T("阶段分布", "By phase")}</h3>${fun}<div class="tags" style="margin-top:10px">${mg}</div></section>
      <section class="pg-sec"><h3>${T("谁在做", "Who is in the race")}</h3>${coHTML}</section>
      <section class="pg-sec"><h3>${T("竞争格局", "Competitive landscape")}</h3><p class="sm">${T("在靶点赛道里和其他靶点对比拥挤度和验证程度。", "Compare crowding and validation against other targets in Landscape.")}</p><button class="more-link" data-ls="${esc(g)}">${T("在靶点赛道里看", "Open in Landscape")} →</button></section>` : ""}
    </div></div>`;
}
function tgPat(g, {r}){
  const terms = tgTerms(g);
  if (!terms.length) return `<section class="pg-sec"><p class="sm">${T("这个靶点没有可用于检索的英文名称。", "No English name available to search for this target.")}</p></section>`;
  const q1 = orQ(terms), ctx = PAT_CTX[tgPatCtx][2], full = ctx ? `${q1} AND ${ctx}` : q1;
  const yr = tgPatYr ? `&after=priority:${tgPatYr}0101` : "";
  const gp = (extra) => `https://patents.google.com/?q=${enc(q1)}${ctx ? `&q=${enc(ctx)}` : ""}${yr}${extra || ""}`;
  const links = [
    ["Google Patents", gp(), T("可按优先权日筛选", "filters by priority date")],
    ["Lens.org", `https://www.lens.org/lens/search/patent/list?q=${enc(full)}`, T("含引用和专利族", "citations and families")],
    ["Espacenet", `https://worldwide.espacenet.com/patent/search?q=${enc(full)}`, T("欧洲专利局", "European Patent Office")],
    ["WIPO Patentscope", `https://patentscope.wipo.int/search/en/result.jsf?query=${enc(full)}`, "PCT"]
  ];
  const cos = new Map(); r.ps.forEach(p => cos.set(p.co, Math.max(cos.get(p.co) || 0, p.ph)));
  const top = [...cos.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
  const asg = n => n.replace(/,? (Inc|Ltd|LLC|plc|AG|SA|Co|Corp|Corporation|Pharmaceuticals?|Therapeutics|Biosciences|Bio)\.?$/i, "");
  return `<div class="pg-grid"><div>
    <section class="pg-sec"><h3>${T("专利检索", "Patent search")}</h3>
      <p class="sub">${T("按靶点名和别名生成检索式，直接打开各专利库的结果页。本站不托管专利数据。", "A query built from the target name and aliases, opened directly in each patent database. The site does not host patent data.")}</p>
      <div class="seg" role="group" aria-label="${T("技术方向", "Modality")}">${Object.entries(PAT_CTX).map(([k, v]) => `<button data-pctx="${k}" aria-pressed="${tgPatCtx === k}">${T(v[0], v[1])}</button>`).join("")}</div>
      <div class="seg" role="group" aria-label="${T("优先权日", "Priority date")}">${[["", T("不限", "Any year")], ["2021", T("2021 年后", "Since 2021")], ["2024", T("2024 年后", "Since 2024")]].map(([k, l]) => `<button data-pyr="${k}" aria-pressed="${tgPatYr === k}">${l}</button>`).join("")}</div>
      <div class="qbox">${esc(full)}</div>
      <div class="ext">${links.map(([n, u, s]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${n} ↗ <small>${s}</small></a>`).join("")}</div>
      <p class="sm" style="margin-top:10px">${T("时间筛选只对 Google Patents 生效。短名称（如 AR、RET）容易误中，检索式里已优先使用全称和别名。", "The year filter applies to Google Patents only. Short names such as AR or RET give noisy hits, so full names and aliases are used first.")}</p>
    </section></div><div>
    <section class="pg-sec"><h3>${T("按公司检索", "By assignee")}</h3>
      <p class="sub">${T("在研公司的专利（Google Patents 按申请人筛选）。子公司可能用不同的申请人名称，比如强生的专利多以 Janssen 申请。", "Patents from companies with programs on this target (Google Patents, filtered by assignee). Subsidiaries may file under other names; J&J often files as Janssen.")}</p>
      ${top.length ? top.map(([c, ph]) => `<div class="cobar"><span>${esc(c)} <span class="sm">${T(`最高 ${PHN(ph)} 期`, `max Ph ${PHN(ph)}`)}</span></span><a href="${esc(gp(`&assignee=${enc(asg(c))}`))}" target="_blank" rel="noopener">Google Patents ↗</a></div>`).join("") : `<p class="sm">${T("没有在研公司。", "No companies with clinical programs.")}</p>`}
    </section></div></div>`;
}
function feedWait(){
  return `<p class="wait">${T("文献和新闻在每周一的数据更新里自动抓取（Europe PMC、Google News）。这个靶点还没有抓取结果，下面的链接可以直接打开最新检索。", "Literature and news are fetched in the Monday data update (Europe PMC, Google News). Nothing has been fetched for this target yet; the links below open a live search.")}</p>`;
}
function tgLit(g, {fd}){
  const terms = tgTerms(g);
  const pm = terms.length ? terms.map(x => `"${x}"[tiab]`).join(" OR ") : g;
  const ep = terms.length ? orQ(terms) : g;
  const ext = `<div class="ext">
    <a href="https://pubmed.ncbi.nlm.nih.gov/?term=${enc(pm)}&sort=date" target="_blank" rel="noopener">PubMed ↗</a>
    <a href="https://europepmc.org/search?query=${enc(ep)}&sortBy=FIRST_PDATE_D" target="_blank" rel="noopener">Europe PMC ↗</a>
    <a href="https://scholar.google.com/scholar?q=${enc(ep)}&scisbd=1" target="_blank" rel="noopener">Google Scholar ↗</a>
    <a href="https://pubmed.ncbi.nlm.nih.gov/?term=${enc(`(${pm}) AND review[pt]`)}&sort=date" target="_blank" rel="noopener">${T("综述", "Reviews")} ↗</a></div>`;
  const L = fd?.lit;
  if (!L) return `<section class="pg-sec">${feedWait()}${ext}</section>`;
  const ys = Object.entries(L.years || {}).sort((a, b) => a[0].localeCompare(b[0])), maxY = Math.max(1, ...ys.map(y => y[1]));
  const paper = p => `<li><a href="${esc(p.u)}" target="_blank" rel="noopener">${esc(p.t)}</a><div class="sm">${esc(p.j || "")}${p.d ? ` · ${esc(p.d)}` : ""}${p.c ? T(` · 被引 ${p.c}`, ` · ${p.c} citations`) : ""}</div></li>`;
  return `<div class="pg-grid"><div>
    <section class="pg-sec"><h3>${T("最新文献", "Latest papers")} <small>${T(`Europe PMC · 共 ${L.total?.toLocaleString?.() ?? "?"} 篇`, `Europe PMC · ${L.total?.toLocaleString?.() ?? "?"} total`)}</small></h3>
      <ol class="pg-list">${(L.recent || []).map(paper).join("") || `<li class="sm">—</li>`}</ol></section>
    <section class="pg-sec"><h3>${T("近三年高被引综述", "Most-cited recent reviews")}</h3><ol class="pg-list">${(L.reviews || []).map(paper).join("") || `<li class="sm">—</li>`}</ol></section>
  </div><div>
    <section class="pg-sec"><h3>${T("每年发表数", "Papers per year")}</h3>
      <div class="yrs">${ys.map(([y, n]) => `<div><b>${n.toLocaleString()}</b><i style="height:${Math.max(2, 80 * n / maxY)}px"></i><span>${y.slice(2)}</span></div>`).join("")}</div>
      <p class="sm">${T(`抓取于 ${esc(FEEDS.generated || "")}。当年为截至抓取日的数量。`, `Fetched ${esc(FEEDS.generated || "")}. The current year counts to the fetch date.`)}</p></section>
    <section class="pg-sec"><h3>${T("检索式", "Query")}</h3><div class="qbox">${esc(L.q || ep)}</div>${ext}</section>
  </div></div>`;
}
function tgNews(g, {fd, cur, ma}){
  const terms = tgTerms(g), q = terms.length ? orQ(terms) : g;
  const ext = `<div class="ext">
    <a href="https://news.google.com/search?q=${enc(q + " (drug OR trial OR FDA)")}&hl=en-US&gl=US&ceid=US:en" target="_blank" rel="noopener">Google News ↗ <small>English</small></a>
    <a href="https://news.google.com/search?q=${enc(q + " (药 OR 临床)")}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans" target="_blank" rel="noopener">Google News ↗ <small>中文</small></a></div>`;
  const item = n => `<li><a href="${esc(n.u)}" target="_blank" rel="noopener">${esc(n.t)}</a><div class="news-src">${esc(n.s || "")}${n.d ? ` · ${esc(n.d)}` : ""}</div></li>`;
  const N = fd?.news, order = EN ? ["en", "zh"] : ["zh", "en"];
  const own = [...cur.map(d => `<li><span class="date">${esc(d.disp)}</span> <span class="verdict ${d.out}">${OUT[d.out]}</span> <button class="tbtn" data-oc="${esc(d.id)}">${esc(d.drug)} ${esc(d.trial)}</button><div class="sm">${esc(d.fact)}</div></li>`),
    ...ma.map(d => `<li><span class="date">${esc(d.d)}</span> <b>${esc(d.a)}</b> ${T("收购", "acquires")} <b>${esc(d.t)}</b> · $${d.v}B<div class="sm">${esc(d.asset || "")}</div></li>`)];
  return `<div class="pg-grid"><div>
    ${N ? order.map(l => `<section class="pg-sec"><h3>${l === "en" ? T("英文新闻", "English news") : T("中文新闻", "Chinese news")} <small>${T("近 90 天 · Google News", "last 90 days · Google News")}</small></h3><ol class="pg-list">${(N[l] || []).map(item).join("") || `<li class="sm">${T("近 90 天没有相关新闻。", "No news in the last 90 days.")}</li>`}</ol></section>`).join("") : `<section class="pg-sec">${feedWait()}${ext}</section>`}
  </div><div>
    <section class="pg-sec"><h3>${T("本站记录", "On this site")}</h3><p class="sub">${T("精选读出和并购案例。", "Curated readouts and acquisitions.")}</p>${own.length ? `<ol class="pg-list">${own.join("")}</ol>` : `<p class="sm">—</p>`}</section>
    ${N ? `<section class="pg-sec"><h3>${T("更多", "More")}</h3>${ext}<p class="sm" style="margin-top:8px">${T(`抓取于 ${esc(FEEDS.generated || "")}`, `Fetched ${esc(FEEDS.generated || "")}`)}</p></section>` : ""}
  </div></div>`;
}
function tgDeal(g, {ma, cand}){
  const maHTML = ma.length ? `<ol class="pg-list">${ma.map(d => `<li><span class="date">${esc(d.d)}</span> <b>${esc(d.a)}</b> → <b>${esc(d.t)}</b> <span class="val">$${d.v}B</span> ${phChip(d.ph)}<div class="sm">${esc(d.asset || "")}${d.why ? ` · ${esc(d.why)}` : ""}</div>${d.src ? `<div class="sm"><a href="${esc(d.src)}" target="_blank" rel="noopener">${T("来源", "Source")} ↗</a></div>` : ""}</li>`).join("")}</ol>`
    : `<p class="sm">${T("2019 年以来没有以这个靶点为核心资产、金额 10 亿美元以上的收购。", "No acquisition of $1B+ since 2019 with this target as the lead asset.")}</p>`;
  const cHTML = cand.length ? `<ol class="pg-list">${cand.map(x => `<li><b>${esc(x.co)}</b> <span class="deal-tk">${esc(x.tk)}</span> <span class="deal-chip">${x.kind === "acquire" ? T("可能被收购", "Acquisition candidate") : T("可能被授权", "Licensing candidate")}</span><div>${esc(x.asset)} · ${esc(x.mech)}</div><div class="sm">${esc(x.stage)}</div></li>`).join("")}</ol>`
    : `<p class="sm">${T("交易候选里没有这个靶点的资产。", "No asset on this target in the deal-candidate list.")}</p>`;
  return `<div class="pg-grid"><div><section class="pg-sec"><h3>${T("并购案例", "Acquisitions")}</h3>${maHTML}</section></div>
    <div><section class="pg-sec"><h3>${T("交易候选", "Deal candidates")}</h3>${cHTML}<button class="more-link" style="margin-top:8px" onclick="showTab('deal')">${T("看全部交易候选", "All deal candidates")} →</button></section></div></div>`;
}

/* ---------------- 治疗领域（医生） ---------------- */
let taCur = null, taCond = "", taQ = "", taLimit = {r:30, p:30, m:30};
const CMP = (EMB?.cmp || []);
function closeArea(fromHash){
  taCur = null; $("tax-page").hidden = true; $("tax-index").hidden = false;
  if (!fromHash) { try { history.pushState(null, "", "#tax"); } catch(e) {} }
  renderTax();
}
function taStats(rows){
  const by = k => rows.filter(t => t._set === k);
  const judged = by("results").filter(t => JUDGED.includes(t.as?.verdict)), hit = judged.filter(t => t.as.verdict === "达到").length;
  return {n: rows.length, res: by("results").length, judged: judged.length, hit, rate: judged.length >= 3 ? 100 * hit / judged.length : null,
          up: by("upcoming").length, stop: by("stopped").length, comp: by("completed").length};
}
function renderTax(){
  if (!REG || taCur) return;
  const tas = taOrder(REG.all);
  $("tax-meta").textContent = T(`${tas.length} 个领域 · ${REG.all.length.toLocaleString()} 项 II/III 期试验`, `${tas.length} areas · ${REG.all.length.toLocaleString()} phase 2/3 trials`);
  $("tax-grid").innerHTML = tas.map(ta => {
    const s = taStats(REG.all.filter(t => t.ta === ta)), nc = D.filter(d => d.ta === ta).length, nm = CMP.filter(c => REG.all.find(t => t.nct === c.n && t.ta === ta)).length;
    return `<button class="tax-card" data-tao="${esc(ta)}"><h3>${esc(ta)}</h3>
      <div class="nums"><span><b>${s.res}</b>${T("新结果", "new results")}</span><span><b>${pctS(s.rate)}</b>${T("达到率", "hit rate")}</span><span><b>${s.up}</b>${T("半年内读出", "due ≤6 mo")}</span><span><b>${s.stop}</b>${T("提前终止", "stopped")}</span></div>
      <div class="sm">${T(`${nc} 条精选读出 · ${nm} 组可比数据`, `${nc} curated readouts · ${nm} comparable data points`)}</div></button>`;
  }).join("");
  $("tax-grid").querySelectorAll("[data-tao]").forEach(b => b.addEventListener("click", () => openArea(b.dataset.tao)));
}
function openArea(ta, fromHash){
  if (!REG) return;
  if (curTab !== "tax") showTab("tax", {hash:false});
  if (taCur !== ta) { taCond = ""; taQ = ""; taLimit = {r:30, p:30, m:30}; }
  taCur = ta; $("tax-index").hidden = true; $("tax-page").hidden = false;
  const h = "#area/" + enc(ta);
  if (!fromHash && location.hash !== h) { try { history.pushState(null, "", h); } catch(e) { location.hash = h; } }
  renderAreaPage();
  window.scrollTo({top: $("panel-tax").getBoundingClientRect().top + window.scrollY - 10});
}
const condOf = t => (t.conditions || [])[0] || "";
function taRows(){
  const Q = makeQ(taQ);
  return REG.all.filter(t => t.ta === taCur && (!taCond || (t.conditions || []).includes(taCond)) && qHit(Q, trialParts(t), t.tg));
}
function renderAreaPage(){
  const ta = taCur, all = REG.all.filter(t => t.ta === ta);
  const cc = {}; all.forEach(t => (t.conditions || []).slice(0, 2).forEach(c => cc[c] = (cc[c] || 0) + 1));
  const conds = Object.entries(cc).filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1]).slice(0, 60);
  $("tax-page").innerHTML = `<div class="crumb"><button id="ta-back">← ${T("全部领域", "All areas")}</button><span>/</span><span>${esc(ta)}</span></div>
    <header class="pg-head"><h2>${esc(ta)}</h2><div class="kpis" id="ta-kpis"></div></header>
    <div class="filters" style="margin-top:14px">
      <select id="ta-cond" aria-label="${T("适应症", "Indication")}"><option value="">${T("全部适应症", "All indications")}</option>${conds.map(([c, n]) => `<option value="${esc(c)}"${c === taCond ? " selected" : ""}>${esc(cut(c, 60))}（${n}）</option>`).join("")}</select>
      <input id="ta-q" type="search" placeholder="${T("搜药名、靶点、公司…", "Search drug, target, company…")}" value="${esc(taQ)}" aria-label="${T("搜索", "Search")}">
      <span class="regmeta" id="ta-meta"></span>
    </div>
    <div id="ta-body"></div>`;
  $("ta-back").addEventListener("click", () => closeArea());
  $("ta-cond").addEventListener("input", e => { taCond = e.target.value; taLimit = {r:30, p:30, m:30}; renderAreaBody(); });
  $("ta-q").addEventListener("input", e => { taQ = e.target.value; renderAreaBody(); });
  renderAreaBody();
}
function cmpRows(kind){
  const M = new Map(taRows().map(t => [t.nct, t]));
  return CMP.filter(c => c.k === kind && M.has(c.n)).map(c => ({...c, t: M.get(c.n)}));
}
const trialLbl = t => t.acronym || ivName(t, t.mod) || t.title;
function forestSVG(rows, wrapW){
  const W = Math.max(320, wrapW), narrow = W < 620, LW = narrow ? 128 : 270, RW = narrow ? 64 : 120, RH = narrow ? 34 : 30, Tp = 24, B = 30;
  const H = Tp + rows.length * RH + B;
  const lo = Math.min(...rows.map(r => r.lo ?? r.v)), hi = Math.max(...rows.map(r => r.hi ?? r.v));
  const a = Math.log(Math.max(0.02, Math.min(lo, 0.8))), b = Math.log(Math.min(50, Math.max(hi, 1.25)));
  const x = v => LW + (Math.log(Math.min(50, Math.max(0.02, v))) - a) / (b - a) * (W - LW - RW - 10);
  let s = svgEl(W, H, T("主要终点效应量森林图", "Forest plot of primary-endpoint effect sizes"));
  [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20].filter(v => Math.log(v) >= a - 1e-9 && Math.log(v) <= b + 1e-9).forEach(v => {
    s += `<line x1="${x(v)}" x2="${x(v)}" y1="${Tp - 6}" y2="${H - B + 4}" stroke="var(--line)"${v === 1 ? ' stroke-width="1.5" stroke="var(--muted)"' : ' stroke-dasharray="2 3"'}/><text class="ax" x="${x(v)}" y="${H - B + 18}" text-anchor="middle">${v}</text>`; });
  s += `<text class="ax" x="${LW}" y="12">${T("← 风险更低 / 比值更小", "← lower risk / ratio")}</text><text class="ax" x="${W - RW - 10}" y="12" text-anchor="end">${T("比值更大 →", "higher ratio →")}</text>`;
  rows.forEach((r, i) => {
    const y = Tp + i * RH + RH / 2, sig = r.p != null && r.p < 0.05, col = sig ? "var(--s1)" : "var(--muted)";
    const lab = cut(trialLbl(r.t), narrow ? 16 : 34), sub = cut(`${r.s} · ${r.e}`, narrow ? 20 : 46);
    s += `<g class="row"><rect class="hl" x="0" y="${y - RH / 2}" width="${W}" height="${RH}" fill="transparent"/>
      <text class="lb" x="4" y="${y - 2}" data-ot="${esc(r.n)}"><title>${esc(trialLbl(r.t))} · ${esc(r.t.group)} · ${esc(condOf(r.t))}\n${esc(r.e)}</title>${esc(lab)}</text><text class="sm" x="4" y="${y + 11}">${esc(sub)}</text>
      ${r.lo != null && r.hi != null ? `<line x1="${x(r.lo)}" x2="${x(r.hi)}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="2"/>` : ""}
      <rect x="${x(r.v) - 4.5}" y="${y - 4.5}" width="9" height="9" fill="${col}"/>
      <text x="${W - RW + 4}" y="${y + 4}" class="ax" style="fill:var(--ink)">${fmtV(r.v)}${narrow ? "" : r.lo != null ? ` (${fmtV(r.lo)}–${fmtV(r.hi)})` : ""}</text></g>`;
  });
  return s + `</svg>`;
}
function dumbSVG(rows, wrapW, unit, maxV){
  const W = Math.max(320, wrapW), narrow = W < 620, LW = narrow ? 128 : 270, RW = narrow ? 52 : 90, RH = narrow ? 34 : 30, Tp = 24, B = 30;
  const H = Tp + rows.length * RH + B;
  const mx = maxV || Math.max(1, ...rows.flatMap(r => [r.x[1], r.c[1]])) * 1.05;
  const x = v => LW + Math.max(0, Math.min(mx, v)) / mx * (W - LW - RW - 10);
  let s = svgEl(W, H, T("治疗组与对照组对比", "Treatment vs control"));
  const step = mx > 60 ? 20 : mx > 30 ? 10 : mx > 12 ? 5 : mx > 6 ? 2 : 1;
  for (let v = 0; v <= mx; v += step) s += `<line x1="${x(v)}" x2="${x(v)}" y1="${Tp - 6}" y2="${H - B + 4}" stroke="var(--line)" stroke-dasharray="2 3"/><text class="ax" x="${x(v)}" y="${H - B + 18}" text-anchor="middle">${v}${unit === "%" ? "%" : ""}</text>`;
  rows.forEach((r, i) => {
    const y = Tp + i * RH + RH / 2, d = r.x[1] - r.c[1], sig = r.p != null && r.p < 0.05;
    const lab = cut(trialLbl(r.t), narrow ? 16 : 34), sub = cut(r.e, narrow ? 20 : 46);
    s += `<g class="row"><rect class="hl" x="0" y="${y - RH / 2}" width="${W}" height="${RH}" fill="transparent"/>
      <text class="lb" x="4" y="${y - 2}" data-ot="${esc(r.n)}"><title>${esc(trialLbl(r.t))} · ${esc(r.t.group)} · ${esc(condOf(r.t))}\n${esc(r.e)}\n${esc(r.x[0])}: ${fmtV(r.x[1])} · ${esc(r.c[0])}: ${fmtV(r.c[1])}${r.p != null ? ` · p=${r.p}` : ""}</title>${esc(lab)}</text><text class="sm" x="4" y="${y + 11}">${esc(sub)}</text>
      <line x1="${x(r.c[1])}" x2="${x(r.x[1])}" y1="${y}" y2="${y}" stroke="var(--line)" stroke-width="3"/>
      <circle cx="${x(r.c[1])}" cy="${y}" r="5" fill="var(--surface)" stroke="var(--muted)" stroke-width="2"/>
      <circle cx="${x(r.x[1])}" cy="${y}" r="5.5" fill="${sig ? "var(--s1)" : "var(--s2)"}"/>
      <text x="${W - RW + 4}" y="${y + 4}" class="ax" style="fill:${d >= 0 ? "var(--ink)" : "var(--neg)"}">${d >= 0 ? "+" : ""}${fmtV(d)}${unit === "%" ? T(" 个百分点", " pp") : unit === "mo" ? T(" 月", " mo") : ""}</text></g>`;
  });
  return s + `</svg>`;
}
function chartBlock(id, title, sub, legend, n, kind){
  return `<section class="pg-sec"><h3>${title} <small>${n}</small></h3><p class="sub">${sub}</p><div class="chart" id="${id}"></div>${legend ? `<div class="chart-leg">${legend}</div>` : ""}<div id="${id}-more"></div></section>`;
}
function renderAreaBody(){
  const rows = taRows(), s = taStats(rows), cur = D.filter(d => d.ta === taCur && (!taCond || true));
  $("ta-kpis").innerHTML = `
    <div><div class="n">${s.res}</div><div class="l">${T("新公布结果", "New results")}</div></div>
    <div><div class="n">${pctS(s.rate)}</div><div class="l">${T(`达到率（${s.hit}/${s.judged}）`, `Hit rate (${s.hit}/${s.judged})`)}</div></div>
    <div><div class="n">${s.comp}</div><div class="l">${T("已完成待公布", "Awaiting results")}</div></div>
    <div><div class="n">${s.up}</div><div class="l">${T("III 期半年内完成", "Ph 3 due ≤6 mo")}</div></div>
    <div><div class="n">${s.stop}</div><div class="l">${T("提前终止", "Stopped early")}</div></div>`;
  $("ta-meta").textContent = T(`${rows.length} 项试验`, `${rows.length} trials`);
  const R = cmpRows("r").sort((a, b) => a.v - b.v), P = cmpRows("p").sort((a, b) => (b.x[1] - b.c[1]) - (a.x[1] - a.c[1])), M = cmpRows("m").sort((a, b) => (b.x[1] - b.c[1]) - (a.x[1] - a.c[1]));
  const up = rows.filter(t => t._set === "upcoming" || t._set === "completed").sort((a, b) => String(a.pcd).localeCompare(String(b.pcd)));
  const g0 = REG.generated.split("-").map(Number), months = Array.from({length:7}, (_, i) => new Date(g0[0], g0[1] - 1 + i, 1));
  const mc = months.map(m => up.filter(t => t._set === "upcoming" && t.pcd && t.pcd.slice(0, 7) === `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`).length), mmx = Math.max(1, ...mc);
  const stopped = rows.filter(t => t._set === "stopped"), wc = {}; stopped.forEach(t => wc[t.why_cat || "未填写"] = (wc[t.why_cat || "未填写"] || 0) + 1);
  const wmx = Math.max(1, ...Object.values(wc));
  const legS = `<span><i style="background:var(--s1)"></i>${T("p<0.05", "p<0.05")}</span><span><i style="background:var(--muted)"></i>${T("不显著或未登记检验", "not significant / no test")}</span>`;
  const legD = `<span><i style="background:var(--surface);border:2px solid var(--muted)"></i>${T("对照组", "Control")}</span><span><i style="background:var(--s1)"></i>${T("治疗组（p<0.05）", "Treatment (p<0.05)")}</span><span><i style="background:var(--s2)"></i>${T("治疗组（不显著 / 无检验）", "Treatment (n.s. / no test)")}</span>`;
  $("ta-body").innerHTML = `
    ${chartBlock("ch-r", T("风险比 / 比值比", "Hazard and odds ratios"), T("登记了效应量和置信区间的主要终点。生存类终点的风险比小于 1 表示治疗组事件更少；应答类的比值比大于 1 表示治疗组应答更多。点试验名看详情。", "Primary endpoints with a registered effect size and confidence interval. For survival endpoints a hazard ratio below 1 favours treatment; for response endpoints an odds ratio above 1 does. Click a trial for details."), legS, T(`${R.length} 组`, `${R.length} estimates`))}
    ${chartBlock("ch-p", T("应答率：治疗组 vs 对照组", "Response rates: treatment vs control"), T("以受试者比例计的主要终点（应答率、缓解率、达标率等），右侧是两组差值。不同试验的终点定义和人群不同，横向比较只作参考。", "Primary endpoints measured as a percentage of participants (response, remission, target attainment); the right column shows the difference. Endpoint definitions and populations differ across trials, so treat cross-trial comparisons as indicative."), legD, T(`${P.length} 组`, `${P.length} comparisons`))}
    ${chartBlock("ch-m", T("中位时间：治疗组 vs 对照组", "Median times: treatment vs control"), T("以月计的中位时间终点（无进展生存、总生存、缓解持续时间等），周和天已换算成月。", "Median time-to-event endpoints in months (PFS, OS, duration of response); weeks and days are converted to months."), legD, T(`${M.length} 组`, `${M.length} comparisons`))}
    <div class="pg-grid">
      <section class="pg-sec"><h3>${T("接下来要读出的", "Coming up")} <small>${T(`${up.length} 项`, `${up.length} trials`)}</small></h3>
        <div class="funnel">${months.map((m, i) => `<div><span>${m.getFullYear() % 100}-${String(m.getMonth() + 1).padStart(2, "0")}</span><span class="b" style="width:${100 * mc[i] / mmx}%"></span><b>${mc[i]}</b></div>`).join("")}</div>
        <p class="sm">${T("III 期按申办方登记的主要完成日计，经常推迟。", "Phase 3 by sponsor-registered primary completion date, which often slips.")}</p>
        <ol class="pg-list">${up.slice().sort((a, b) => (b.n || 0) - (a.n || 0)).slice(0, 12).map(t => `<li><span class="date">${esc(t.pcd)}</span> <button class="tbtn" data-ot="${esc(t.nct)}">${esc(trialLbl(t))}</button><div class="sm">${esc(t.group)} · ${esc(condOf(t))}${t.n ? T(` · ${t.n} 例`, ` · n=${t.n}`) : ""}${t._set === "completed" ? T(" · 已完成待公布", " · awaiting results") : ""}</div></li>`).join("") || `<li class="sm">—</li>`}</ol></section>
      <section class="pg-sec"><h3>${T("提前终止的原因", "Why trials stopped")} <small>${T(`${stopped.length} 项`, `${stopped.length} trials`)}</small></h3>
        <div class="funnel">${Object.entries(wc).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<div style="grid-template-columns:120px minmax(0,1fr) 40px"><span>${esc(k)}</span><span class="b" style="width:${100 * v / wmx}%;background:var(${WHY_COLOR[k] || "--muted"})"></span><b>${v}</b></div>`).join("") || `<p class="sm">—</p>`}</div>
        <ol class="pg-list" style="margin-top:8px">${stopped.filter(t => ["疗效 / 无效性", "安全性"].includes(t.why_cat)).slice(0, 6).map(t => `<li><button class="tbtn" data-ot="${esc(t.nct)}">${esc(trialLbl(t))}</button><div class="sm">${esc(t.group)} · ${esc(t.why_cat)} · ${esc(cut(t.why, 90))}</div></li>`).join("")}</ol></section>
    </div>
    <section class="pg-sec" style="margin-top:14px"><h3>${T("精选读出", "Curated readouts")} <small>${T(`${cur.length} 条，附研发、BD、医生三种视角点评`, `${cur.length}, with R&D, BD and clinician commentary`)}</small></h3>
      <ol class="pg-list">${cur.slice().sort((a, b) => b.date.localeCompare(a.date)).map(d => `<li><span class="date">${esc(d.disp)}</span> <span class="verdict ${d.out}">${OUT[d.out]}</span> <button class="tbtn" data-oc="${esc(d.id)}">${esc(d.drug)} ${esc(d.trial)}</button><div class="sm">${esc(d.ind)} · ${esc(d.ep)}</div><div class="sm">${esc(d.md)}</div></li>`).join("") || `<li class="sm">—</li>`}</ol></section>`;
  const draw = () => {
    const w = $("ch-r")?.clientWidth || 700;
    [["ch-r", R, "r"], ["ch-p", P, "p"], ["ch-m", M, "m"]].forEach(([id, rows, k]) => {
      const el = $(id), more = $(id + "-more"), shown = rows.slice(0, taLimit[k]);
      el.innerHTML = rows.length ? (k === "r" ? forestSVG(shown, w) : dumbSVG(shown, w, k === "p" ? "%" : "mo", k === "p" ? 100 : null))
        : `<div class="chart-empty">${T("这个范围里没有可比的数据。换一个适应症或清空搜索试试。", "No comparable data in this selection. Try another indication or clear the search.")}</div>`;
      more.innerHTML = rows.length > taLimit[k] ? `<button class="more" data-tam="${k}">${T(`再显示 30 组（共 ${rows.length} 组）`, `Show 30 more (${rows.length} total)`)}</button>` : "";
    });
    $("ta-body").querySelectorAll("[data-tam]").forEach(b => b.addEventListener("click", () => { taLimit[b.dataset.tam] += 30; draw(); bind(); }));
    bind();
  };
  const bind = () => {
    $("ta-body").querySelectorAll("[data-ot]").forEach(b => { if (b._b) return; b._b = 1; b.addEventListener("click", () => openDetail("t", b.dataset.ot)); });
    $("ta-body").querySelectorAll("[data-oc]").forEach(b => { if (b._b) return; b._b = 1; b.addEventListener("click", () => openDetail("c", b.dataset.oc)); });
  };
  draw();
}
let rzA; window.addEventListener("resize", () => { clearTimeout(rzA); rzA = setTimeout(() => { if (taCur && curTab === "tax") renderAreaBody(); if (curTab === "ma") renderMA(); }, 250); });

/* ---------------- 并购（BD） ---------------- */
const MA_TA_COL = {"肿瘤":"--c1","免疫 / 炎症":"--c3","心血管 / 代谢 / 肾":"--c4","神经 / 精神 / 疼痛":"--c5","血液":"--c7","罕见病 / 遗传":"--c2","感染 / 疫苗":"--c6","其他":"--c8"};
const MA_PH = ["上市","申报","III 期","II 期","I 期","临床前","平台"];
const MA_PH_COL = {"上市":"--c6","申报":"--c3","III 期":"--c1","II 期":"--c5","I 期":"--c2","临床前":"--c7","平台":"--c8"};
const MA_PH_EN = {"上市":"Approved","申报":"Filed","III 期":"Ph 3","II 期":"Ph 2","I 期":"Ph 1","临床前":"Preclinical","平台":"Platform"};
const phL = ph => EN ? (MA_PH_EN[ph] || ph) : ph;
const phChip = ph => ph ? `<span class="ph-chip" style="background:color-mix(in srgb, var(${MA_PH_COL[ph] || "--c8"}) 18%, transparent);color:var(${MA_PH_COL[ph] || "--c8"})">${esc(phL(ph))}</span>` : "";
let maF = {y:"", ta:"", a:"", ph:"", mod:"", q:""}, maMetric = "n", maLimit = 40, maSort = "d";
const maTA = d => MA_TA_COL[d.ta] ? d.ta : "其他";
function maFiltered(skip){
  const MA = EMB?.ma?.deals || [], Q = maF.q.trim().toLowerCase();
  return MA.filter(d => (skip === "y" || !maF.y || d.d.slice(0, 4) === maF.y) && (skip === "ta" || !maF.ta || maTA(d) === maF.ta) && (skip === "a" || !maF.a || d.a === maF.a) &&
    (skip === "ph" || !maF.ph || d.ph === maF.ph) && (skip === "mod" || !maF.mod || d.mod === maF.mod) &&
    (!Q || [d.a, d.t, d.asset, d.why, ...(d.tg || [])].join(" ").toLowerCase().includes(Q)));
}
const sumV = ds => ds.reduce((a, d) => a + (d.v || 0), 0);
const fB = v => v >= 100 ? Math.round(v) : (Math.round(v * 10) / 10).toFixed(1);
function maYearChart(ds, W){
  const yrs = [...new Set((EMB.ma.deals || []).map(d => d.d.slice(0, 4)))].sort();
  const tas = Object.keys(MA_TA_COL), H = 230, L = 40, R = 8, Tp = 14, B = 26;
  const val = d => maMetric === "n" ? 1 : d.v || 0;
  const tot = yrs.map(y => ds.filter(d => d.d.slice(0, 4) === y).reduce((a, d) => a + val(d), 0)), mx = Math.max(1, ...tot) * 1.08;
  const bw = (W - L - R) / yrs.length, y = v => Tp + (1 - v / mx) * (H - Tp - B);
  let s = svgEl(W, H, T("按年份的并购数量", "Acquisitions by year")).replace("<svg ", '<svg style="width:100%;height:auto" ');
  const step = mx > 150 ? 50 : mx > 60 ? 20 : mx > 25 ? 10 : 5;
  for (let v = 0; v <= mx; v += step) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-dasharray="2 3"/><text class="ax" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  yrs.forEach((yr, i) => {
    let acc = 0; const x0 = L + i * bw + bw * .16, w = bw * .68;
    tas.forEach(ta => { const v = ds.filter(d => d.d.slice(0, 4) === yr && maTA(d) === ta).reduce((a, d) => a + val(d), 0); if (!v) return;
      s += `<rect x="${x0}" y="${y(acc + v)}" width="${w}" height="${y(acc) - y(acc + v)}" fill="var(${MA_TA_COL[ta]})" data-may="${yr}" data-mata="${esc(ta)}" style="cursor:pointer"><title>${yr} · ${esc(ta)} · ${maMetric === "n" ? v + T(" 笔", " deals") : "$" + fB(v) + "B"}</title></rect>`; acc += v; });
    s += `<text class="ax" x="${x0 + w / 2}" y="${y(acc) - 4}" text-anchor="middle" style="fill:var(--ink)">${maMetric === "n" ? acc : fB(acc)}</text>`;
    s += `<text class="ax lb" x="${x0 + w / 2}" y="${H - 8}" text-anchor="middle" data-may="${yr}" style="cursor:pointer;${maF.y === yr ? "font-weight:700;fill:var(--accent)" : ""}">${yr}</text>`;
  });
  return s + `</svg>`;
}
function maStack(ds, keyFn, order, colFn, lab){
  lab = lab || (k => k);
  const yrs = [...new Set((EMB.ma.deals || []).map(d => d.d.slice(0, 4)))].sort();
  return `<div class="hbar" style="grid-template-columns:46px minmax(0,1fr) 34px">${yrs.map(y => {
    const r = ds.filter(d => d.d.slice(0, 4) === y), c = {}; r.forEach(d => { const k = keyFn(d); c[k] = (c[k] || 0) + 1; });
    return `<span class="v">${y}</span><div class="bar">${order.filter(k => c[k]).map(k => `<i style="flex:${c[k]};background:var(${colFn(k)})" title="${y} · ${esc(lab(k))} · ${c[k]}"></i>`).join("")}</div><span class="v">${r.length}</span>`; }).join("")}</div>
    <div class="chart-leg">${order.filter(k => ds.some(d => keyFn(d) === k)).map(k => `<span><i style="background:var(${colFn(k)});border-radius:2px"></i>${esc(lab(k))}</span>`).join("")}</div>`;
}
function renderMA(){
  const MAD = EMB?.ma;
  if (!MAD) { $("ma-body").innerHTML = `<div class="empty">${T("并购数据还没有生成。", "Acquisition data has not been built yet.")}</div>`; return; }
  const ds = maFiltered(), all = MAD.deals;
  const W = Math.max(320, ($("ma-body").clientWidth || 900) - 34);
  $("ma-meta").textContent = T(`${all.length} 笔 · 核实于 ${MAD.asof}`, `${all.length} deals · verified ${MAD.asof}`);
  const late = ds.filter(d => ["上市", "申报", "III 期"].includes(d.ph)).length;
  const vs = ds.map(d => d.v).sort((a, b) => a - b), med = vs.length ? vs[Math.floor(vs.length / 2)] : 0;
  const acq = {}; ds.forEach(d => { const o = acq[d.a] || (acq[d.a] = {n:0, v:0}); o.n++; o.v += d.v || 0; });
  const acqTop = Object.entries(acq).sort((a, b) => (maMetric === "n" ? b[1].n - a[1].n : 0) || b[1].v - a[1].v).slice(0, 15), amx = Math.max(1, ...acqTop.map(([, o]) => maMetric === "n" ? o.n : o.v));
  const yrs = [...new Set(all.map(d => d.d.slice(0, 4)))].sort(), tas = Object.keys(MA_TA_COL);
  const hc = {}; maFiltered("ta").filter(d => !maF.y || true).forEach(d => { const k = maTA(d) + "|" + d.d.slice(0, 4); hc[k] = (hc[k] || 0) + 1; });
  const hmx = Math.max(1, ...Object.values(hc));
  const chips = Object.entries(maF).filter(([k, v]) => v && k !== "q").map(([k, v]) => `<button class="chip" data-maclr="${k}">${esc({y:T("年份", "Year"), ta:T("领域", "Area"), a:T("买家", "Buyer"), ph:T("阶段", "Stage"), mod:T("形式", "Modality")}[k])}：${esc(v)} ✕</button>`).join("");
  const sorted = ds.slice().sort(maSort === "v" ? (a, b) => (b.v || 0) - (a.v || 0) : (a, b) => b.d.localeCompare(a.d));
  const mods = [...new Set(all.map(d => d.mod))].filter(Boolean);
  $("ma-body").innerHTML = `
    <div class="kpis ma-kpis">
      <div><div class="n">${ds.length}</div><div class="l">${T("笔交易", "Deals")}</div></div>
      <div><div class="n">$${fB(sumV(ds))}B</div><div class="l">${T("总金额", "Total value")}</div></div>
      <div><div class="n">$${fB(med)}B</div><div class="l">${T("中位金额", "Median deal")}</div></div>
      <div><div class="n">${ds.length ? Math.round(100 * late / ds.length) : 0}%</div><div class="l">${T("核心资产已到 III 期或更后", "Lead asset at Ph 3 or later")}</div></div>
    </div>
    <div class="ma-filters"><div class="seg" role="group" aria-label="${T("指标", "Metric")}"><button data-mam="n" aria-pressed="${maMetric === "n"}">${T("按笔数", "By count")}</button><button data-mam="v" aria-pressed="${maMetric === "v"}">${T("按金额", "By value")}</button></div>${chips}</div>
    <div class="ma-grid">
      <section class="pg-sec"><h3>${T("每年的并购", "Deals per year")} <small>${maMetric === "n" ? T("笔数", "count") : T("金额，十亿美元", "value, $B")}</small></h3><div class="chart" id="ma-yr">${maYearChart(maFiltered("y"), 560)}</div>
        <div class="chart-leg">${tas.map(k => `<span><i style="background:var(${MA_TA_COL[k]});border-radius:2px"></i>${esc(k)}</span>`).join("")}</div></section>
      <section class="pg-sec"><h3>${T("买家排行", "Top buyers")} <small>${maMetric === "n" ? T("按笔数", "by count") : T("按金额", "by value")}</small></h3>
        <div class="hbar">${acqTop.map(([k, o]) => `<button data-maa="${esc(k)}" aria-pressed="${maF.a === k}" title="${esc(k)}">${esc(k)}</button><div class="bar" style="width:${100 * (maMetric === "n" ? o.n : o.v) / amx}%"><i style="flex:1;background:var(--c1)"></i></div><span class="v">${o.n}${T(" 笔", "")} · $${fB(o.v)}B</span>`).join("")}</div></section>
      <section class="pg-sec"><h3>${T("领域 × 年份", "Area × year")} <small>${T("笔数，点格子筛选", "count; click to filter")}</small></h3>
        <div class="tablewrap" style="border:0"><table class="heat"><thead><tr><th></th>${yrs.map(y => `<th>${y.slice(2)}</th>`).join("")}</tr></thead><tbody>${tas.map(ta => `<tr><th scope="row">${esc(ta)}</th>${yrs.map(y => { const v = hc[ta + "|" + y] || 0;
          return `<td style="${v ? `background:color-mix(in srgb, var(${MA_TA_COL[ta]}) ${Math.round(12 + 60 * v / hmx)}%, transparent)` : ""}">${v ? `<button data-may="${y}" data-mata="${esc(ta)}">${v}</button>` : ""}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div></section>
      <section class="pg-sec"><h3>${T("收购时核心资产所处阶段", "Stage of lead asset at deal")}</h3>${maStack(maFiltered("ph"), d => d.ph, MA_PH, k => MA_PH_COL[k] || "--c8", phL)}</section>
      <section class="pg-sec"><h3>${T("核心资产的药物形式", "Modality of lead asset")}</h3>${maStack(maFiltered("mod"), d => d.mod, MOD_GROUP_ORDER.filter(m => mods.includes(m)), k => ({"小分子":"--c1","蛋白 / 抗体":"--c3","细胞 / 基因":"--c5","核酸":"--c2","多肽":"--c4","放射性药物":"--c7","疫苗":"--c6"}[k] || "--c8"))}</section>
      <section class="pg-sec"><h3>${T("看出来的规律", "Patterns")}</h3><ul class="loe" style="padding-left:18px;margin:0">${(MAD.insights || []).map(x => `<li style="margin-bottom:6px">${esc(x)}</li>`).join("")}</ul></section>
    </div>
    <section class="pg-sec" style="margin-top:14px"><h3>${T("交易列表", "All deals")} <small>${T(`${ds.length} 笔`, `${ds.length} deals`)}</small></h3>
      <div class="filters"><input id="ma-q" type="search" placeholder="${T("搜公司、药物、靶点…", "Search company, drug, target…")}" value="${esc(maF.q)}">
        <select id="ma-ph"><option value="">${T("全部阶段", "All stages")}</option>${MA_PH.map(p => `<option value="${p}"${maF.ph === p ? " selected" : ""}>${phL(p)}</option>`).join("")}</select>
        <select id="ma-mod"><option value="">${T("全部药物形式", "All modalities")}</option>${mods.map(p => `<option${maF.mod === p ? " selected" : ""}>${esc(p)}</option>`).join("")}</select>
        <select id="ma-sort"><option value="d"${maSort === "d" ? " selected" : ""}>${T("按日期", "By date")}</option><option value="v"${maSort === "v" ? " selected" : ""}>${T("按金额", "By value")}</option></select></div>
      <div class="tablewrap"><table class="ma"><thead><tr><th>${T("宣布", "Announced")}</th><th>${T("买家 → 标的", "Buyer → target")}</th><th class="num">${T("金额", "Value")}</th><th>${T("核心资产", "Lead asset")}</th><th>${T("领域 · 形式", "Area · modality")}</th><th>${T("阶段", "Stage")}</th></tr></thead><tbody>
      ${sorted.slice(0, maLimit).map(d => `<tr><td class="d">${esc(d.d)}${d.st && d.st !== "完成" ? `<div class="sm">${esc(d.st)}</div>` : ""}</td>
        <td><b>${esc(d.a)}</b> → <b>${esc(d.t)}</b>${d.why ? `<div class="sm">${esc(d.why)}</div>` : ""}${d.src ? `<div class="sm"><a href="${esc(d.src)}" target="_blank" rel="noopener">${T("来源", "Source")} ↗</a></div>` : ""}</td>
        <td class="num"><span class="val">$${fB(d.v)}B</span>${d.cvr ? `<div class="sm">${T("含或有付款", "incl. contingent")}</div>` : ""}</td>
        <td>${esc(d.asset || "")}${(d.tg || []).length ? `<div class="sm">${d.tg.map(g => `<button class="tbtn" data-gotg="${esc(g)}">${esc(g)}</button>`).join(" · ")}</div>` : ""}</td>
        <td class="sm">${esc(d.ta)}<br>${esc(d.mod || "")}</td><td>${phChip(d.ph)}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">${T("没有符合条件的交易。", "No deals match.")}</td></tr>`}</tbody></table></div>
      ${sorted.length > maLimit ? `<button class="more" id="ma-more">${T(`再显示 40 笔（共 ${sorted.length} 笔）`, `Show 40 more (${sorted.length} total)`)}</button>` : ""}
    </section>
    ${maNextHTML()}
    <div class="deal-src">${esc(MAD.method || "")}</div>`;
  const B = $("ma-body");
  B.querySelectorAll("[data-mam]").forEach(b => b.addEventListener("click", () => { maMetric = b.dataset.mam; renderMA(); }));
  B.querySelectorAll("[data-maa]").forEach(b => b.addEventListener("click", () => { maF.a = maF.a === b.dataset.maa ? "" : b.dataset.maa; maLimit = 40; renderMA(); }));
  B.querySelectorAll("[data-may]").forEach(b => b.addEventListener("click", () => { const y = b.dataset.may, ta = b.dataset.mata || "";
    if (maF.y === y && maF.ta === ta) { maF.y = ""; maF.ta = ""; } else { maF.y = y; maF.ta = ta; } maLimit = 40; renderMA(); }));
  B.querySelectorAll("[data-maclr]").forEach(b => b.addEventListener("click", () => { maF[b.dataset.maclr] = ""; renderMA(); }));
  B.querySelectorAll("[data-gotg]").forEach(b => b.addEventListener("click", () => openTarget(b.dataset.gotg)));
  B.querySelectorAll("[data-oc]").forEach(b => b.addEventListener("click", () => openDetail("c", b.dataset.oc)));
  const mq = $("ma-q"); mq.addEventListener("input", () => { maF.q = mq.value; clearTimeout(mq._t); mq._t = setTimeout(() => { renderMA(); const e = $("ma-q"); e.focus(); e.setSelectionRange(e.value.length, e.value.length); }, 250); });
  $("ma-ph").addEventListener("input", e => { maF.ph = e.target.value; renderMA(); });
  $("ma-mod").addEventListener("input", e => { maF.mod = e.target.value; renderMA(); });
  $("ma-sort").addEventListener("input", e => { maSort = e.target.value; renderMA(); });
  const mm = $("ma-more"); if (mm) mm.addEventListener("click", () => { maLimit += 40; renderMA(); });
  B.querySelectorAll("[data-godeal]").forEach(b => b.addEventListener("click", () => showTab("deal")));
}
function maNextHTML(){
  const MAD = EMB.ma, L = MAD.loe || [];
  if (!L.length) return "";
  const yr = +(REG?.generated || todayISO()).slice(0, 4);
  const cands = ["acquire"].flatMap(k => (EMB?.deals?.[k] || []).flatMap(a => a.items.map(x => ({...x, area:a.name, _a:a._zh || a.name, rv:(x.lo + x.hi) / 2 * x.p}))));
  const cards = L.map(c => {
    const own = MAD.deals.filter(d => d.a === c.co && +d.d.slice(0, 4) >= yr - 3);
    const tas = {}; own.forEach(d => tas[maTA(d)] = (tas[maTA(d)] || 0) + 1);
    const key = f => ({"肿瘤":"肿瘤","免疫 / 炎症":"免疫","呼吸":"呼吸","心血管 / 代谢 / 肾":"心血管","神经 / 精神 / 疼痛":"神经"}[f]);
    const focus = (c.ta || []).slice(0, 2).map(key).filter(Boolean), match = [];
    focus.forEach(k => cands.filter(x => x._a.includes(k) && !match.includes(x)).sort((a, b) => b.rv - a.rv).slice(0, 2).forEach(x => match.push(x)));
    return `<article class="next-card"><h4>${esc(c.co)} <span class="deal-chip ${c.p === "高" || c.p === "High" ? "neg" : c.p === "中" || c.p === "Medium" ? "warn" : ""}">${T("专利悬崖压力：", "LOE pressure: ")}${esc(c.p)}</span></h4>
      <div class="loe">${(c.items || []).map(([n, y]) => `<span>${esc(n)} <b>${esc(y)}</b></span>`).join(" · ")}</div>
      ${c.note ? `<div class="sm">${esc(c.note)}</div>` : ""}
      <div class="sm">${T("近三年买过：", "Bought in last 3 years: ")}${own.length ? own.map(d => `${esc(d.t)}（${esc(maTA(d))}）`).join("、") : T("没有 10 亿美元以上的收购", "no $1B+ acquisitions")}</div>
      ${match.length ? `<div class="sm"><b>${T("交易候选里方向对得上的", "Matching deal candidates")}</b></div><ul>${match.map(x => `<li><b>${esc(x.co)}</b> · ${esc(x.asset)} <span class="sm">${esc(x.area)}</span></li>`).join("")}</ul>` : ""}
    </article>`;
  }).join("");
  return `<section class="pg-sec" style="margin-top:14px"><h3>${T("接下来可能发生什么", "What may come next")}</h3>
    <p class="sub">${T("大药企的专利到期越集中、近年补充的管线越少，买的动力越大。每张卡片列出主要产品的美国专利 / 独占期到期年份、近三年的收购，以及交易候选里领域对得上的资产。这是推理线索，不是预测。", "Big pharma buy more when patent expiries cluster and recent pipeline additions are thin. Each card lists key products' US exclusivity end years, acquisitions in the last three years, and deal candidates in matching areas. These are leads, not predictions.")}</p>
    <div class="next-grid">${cards}</div><button class="more-link" style="margin-top:12px" data-godeal>${T("看全部交易候选", "All deal candidates")} →</button></section>`;
}
