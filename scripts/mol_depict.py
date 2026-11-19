#!/usr/bin/env python3
"""分子对比表的结构图：同一靶点的分子按化学骨架分组、对齐朝向，差异部分上色，本地画成 SVG。

做法（每个靶点单独算）：
  1. 取分子对比表里有 SMILES 的分子，去掉盐和溶剂，只留最大片段；
  2. Morgan 指纹 + Butina 粗分组（Tanimoto ≥ 0.2）；
  3. 组内以中心分子为种子，和它的 MCS（只认完整的环）够大（≥ 8 个重原子且 ≥ 最小分子的 35%）的才留下；
     全组 MCS 不够大就从最后加入的开始剔除，剔出来的再按同样办法另成一组；
  4. 以组里第一个分子（聚类中心）的 2D 坐标为模板，其他分子的公共骨架摆成同样的位置和朝向；
  5. 公共骨架画成黑色，骨架以外（取代基、差异部分）和骨架上换了元素的原子用浅橙色底色标出；单独成组的分子不上色。
  MCS 不区分元素，吡啶换苯环、N 换 C 这类生物电子等排仍算同一骨架。

输出：docs/mol/<靶点哈希>/<药名键>.svg，索引写进 docs/molecules.json 的 "svg"：
  {靶点: {"d": 目录名, "m": {药名键: 组号}, "f": {别名键: 画图用的键}, "g": [[组号, 分子数, 公共骨架重原子数], ...]}}
  组号从 1 开始按分子数从多到少排，0 表示单独成组。
同一靶点的分子集合没变就不重画（docs/mol/index.json 记着每个靶点的指纹）。
"""
import hashlib, json, os, re, shutil, sys

try:
    from rdkit import Chem, DataStructs, RDLogger
    from rdkit.Chem import rdFMCS, rdDepictor, rdFingerprintGenerator
    from rdkit.Chem.Draw import rdMolDraw2D
    from rdkit.Chem.MolStandardize import rdMolStandardize
    from rdkit.ML.Cluster import Butina
    RDLogger.DisableLog("rdApp.*")
except ImportError:  # 没装 RDKit 时整步跳过，页面退回 PubChem 图片
    Chem = None

SIM = 0.2             # 先粗分组的最低 Tanimoto 相似度（之后用 MCS 校验）
MIN_CORE = 8          # 公共骨架最少重原子数
MIN_CORE_FRAC = 0.35  # 公共骨架至少占组里最小分子的比例
W, H = 240, 200
HL = (1.0, 0.78, 0.45)   # 差异部分的底色
VER = 3                  # 画法改了就加一，所有靶点重画


def _dir(g):
    return hashlib.md5(g.encode("utf-8")).hexdigest()[:10]


def _prep(smi):
    m = Chem.MolFromSmiles(smi or "")
    if m is None:
        return None
    if "." in smi:
        m = rdMolStandardize.LargestFragmentChooser().choose(m)
    return m


def _groups(mols):
    """[(中心下标, [成员下标...])]，按组大小从大到小。"""
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    fps = [gen.GetFingerprint(m) for m in mols]
    d = []
    for i in range(1, len(fps)):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        d.extend(1 - s for s in sims)
    cl = Butina.ClusterData(d, len(fps), 1 - SIM, isDistData=True) if len(fps) > 1 else ((0,),)
    return sorted(([c[0], list(c)] for c in cl), key=lambda x: -len(x[1]))


def _core(mols, timeout=3):
    r = rdFMCS.FindMCS(mols, timeout=timeout, ringMatchesRingOnly=True, completeRingsOnly=True,
                       atomCompare=rdFMCS.AtomCompare.CompareAny, bondCompare=rdFMCS.BondCompare.CompareOrder)
    if r.canceled and r.numAtoms == 0:
        return None, 0
    need = max(MIN_CORE, MIN_CORE_FRAC * min(m.GetNumHeavyAtoms() for m in mols))
    if r.numAtoms < need:
        return None, r.numAtoms
    return Chem.MolFromSmarts(r.smartsString), r.numAtoms


def _svg(m, hl_atoms=(), hl_bonds=()):
    d = rdMolDraw2D.MolDraw2DSVG(W, H, -1, -1, True)   # noFreetype：原子标签用 <text>，不画成字形路径
    o = d.drawOptions()
    o.clearBackground = False
    o.padding = 0.06
    o.bondLineWidth = 1.6
    o.additionalAtomLabelPadding = 0.08
    o.highlightRadius = 0.38
    o.highlightBondWidthMultiplier = 14
    o.fillHighlights = True
    o.continuousHighlight = True
    m = rdMolDraw2D.PrepareMolForDrawing(m, kekulize=True, addChiralHs=True, wedgeBonds=True)
    d.DrawMolecule(m, highlightAtoms=list(hl_atoms), highlightAtomColors={a: HL for a in hl_atoms},
                   highlightBonds=list(hl_bonds), highlightBondColors={b: HL for b in hl_bonds})
    d.FinishDrawing()
    s = d.GetDrawingText()
    s = re.sub(r"<\?xml[^>]*>\s*", "", s)
    s = re.sub(r"<!-- END OF HEADER -->\s*", "", s)
    s = re.sub(r"(\d+\.\d)\d+", r"\1", s)          # 坐标留一位小数
    # RDKit 每条路径都带一长串 style，换成共用的 class，文件小 70%
    s = re.sub(r" class='[^']*'", "", s)
    styles = {}
    s = re.sub(r"style='([^']*)'", lambda m: "class='%s'" % styles.setdefault(m.group(1), "s%d" % len(styles)), s)
    s = re.sub(r"<svg[^>]*>", "<svg xmlns='http://www.w3.org/2000/svg' width='%d' height='%d' viewBox='0 0 %d %d'><style>%s</style>"
               % (W, H, W, H, "".join(".%s{%s}" % (c, st) for st, c in styles.items())), s, count=1)
    s = re.sub(r">\s+<", "><", s)
    s = re.sub(r"\s+/>", "/>", s)
    return s


def depict_target(mols):
    """mols: {药名键: Mol} → ({药名键: svg}, {药名键: 组号}, [[组号, 数量, 骨架原子数]])。"""
    keys = list(mols)
    ms = [mols[k] for k in keys]
    out, grp, info = {}, {}, []
    gid = 0
    def emit_single(i):
        m = Chem.Mol(ms[i])
        rdDepictor.Compute2DCoords(m)
        out[keys[i]] = _svg(m)
        grp[keys[i]] = 0

    for _, mem in _groups(ms):
        pending = list(mem)
        while pending:
            seed = pending[0]
            g = [seed] + [j for j in pending[1:] if _core([ms[seed], ms[j]], 1)[0] is not None]
            core, nc = None, 0
            while len(g) > 1:
                core, nc = _core([ms[i] for i in g])
                if core is not None:
                    break
                g.pop()
            pending = [i for i in pending if i not in g]
            if core is None:
                emit_single(seed)
                continue
            gid += 1
            info.append([gid, len(g), nc])
            ref = Chem.Mol(ms[seed])
            rdDepictor.Compute2DCoords(ref)
            ref_mt = ref.GetSubstructMatch(core)
            for i in g:
                m = ref if i == seed else Chem.Mol(ms[i])
                if i != seed:
                    try:
                        rdDepictor.GenerateDepictionMatching2DStructure(m, ref, refPatt=core, acceptFailure=True)
                    except Exception:  # noqa: BLE001
                        rdDepictor.Compute2DCoords(m)
                mt = m.GetSubstructMatch(core)
                match = set(mt)
                # 骨架对齐不区分元素（吡啶换苯环也算同一骨架），但元素和种子分子不同的原子照样上色
                swap = {mt[j] for j in range(len(mt)) if ref_mt and m.GetAtomWithIdx(mt[j]).GetAtomicNum() != ref.GetAtomWithIdx(ref_mt[j]).GetAtomicNum()}
                hl_a = [a.GetIdx() for a in m.GetAtoms() if a.GetIdx() not in match or a.GetIdx() in swap] if match else []
                hl_b = [b.GetIdx() for b in m.GetBonds() if not (b.GetBeginAtomIdx() in match and b.GetEndAtomIdx() in match)] if match else []
                out[keys[i]] = _svg(m, hl_a, hl_b)
                grp[keys[i]] = gid
    # 组号按分子数从多到少重新编
    order = {old: new for new, (old, _, _) in enumerate(sorted(info, key=lambda x: -x[1]), 1)}
    grp = {k: order.get(v, 0) for k, v in grp.items()}
    info = sorted([[order[a], b, c] for a, b, c in info])
    return out, grp, info


def build(docs, pairs):
    """pairs: [(靶点, 药名键)]（药名键是 molecules.json 里的键）。写 SVG 和索引，返回 (靶点数, 图片数)。"""
    if Chem is None:
        print("[warn] RDKit not installed; molecule SVGs skipped", file=sys.stderr)
        return 0, 0
    mp = os.path.join(docs, "molecules.json")
    M = json.load(open(mp, encoding="utf-8"))
    D = M.get("drugs") or {}
    root = os.path.join(docs, "mol")
    ip = os.path.join(root, "index.json")
    old = json.load(open(ip, encoding="utf-8")) if os.path.exists(ip) else {}
    by_t = {}
    for g, k in pairs:
        m = D.get(k) or {}
        if m.get("smi") and (m.get("mw") or 0) <= 1500:
            by_t.setdefault(g, {})[k] = m["smi"]
    idx, new, n_img = {}, {}, 0
    for g in sorted(by_t):
        smis = by_t[g]
        fp = hashlib.md5(json.dumps([VER, sorted(smis.items())]).encode()).hexdigest()
        dn = _dir(g)
        o = old.get(g)
        if o and o.get("fp") == fp and os.path.isdir(os.path.join(root, dn)):
            new[g] = o
            idx[g] = {k: v for k, v in o.items() if k != "fp"}
            n_img += len(o["m"]) - len(o.get("f") or {})
            continue
        # 同一个分子可能挂在几个药名键下（通用名、代号、盐型名），按 SMILES 去重后再聚类，画好再分给每个键
        rep = {}
        for k, s in sorted(smis.items()):
            rep.setdefault(s, k)
        mols = {k: m for k, m in ((k, _prep(s)) for s, k in rep.items()) if m is not None}
        if not mols:
            continue
        svgs, grp, info = depict_target(mols)
        # 别名键不另存文件，"f" 记它用哪个键的图
        fmap = {}
        for k, s in smis.items():
            r = rep[s]
            if r in svgs and k != r:
                grp[k], fmap[k] = grp[r], r
        dd = os.path.join(root, dn)
        shutil.rmtree(dd, ignore_errors=True)
        os.makedirs(dd, exist_ok=True)
        for k, s in svgs.items():
            with open(os.path.join(dd, k + ".svg"), "w", encoding="utf-8") as f:
                f.write(s)
        idx[g] = {"d": dn, "m": grp, "g": info, "f": fmap}
        new[g] = dict(idx[g], fp=fp)
        n_img += len(svgs)
    # 不再用到的靶点目录删掉
    keep = {v["d"] for v in new.values()}
    if os.path.isdir(root):
        for x in os.listdir(root):
            if os.path.isdir(os.path.join(root, x)) and x not in keep:
                shutil.rmtree(os.path.join(root, x))
    os.makedirs(root, exist_ok=True)
    json.dump(new, open(ip, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    M["svg"] = idx
    json.dump(M, open(mp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return len(idx), n_img
