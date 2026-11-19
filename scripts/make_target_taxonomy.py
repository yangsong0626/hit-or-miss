#!/usr/bin/env python3
"""生成 data/target_taxonomy.json（靶点分类、通路和关系）。人工维护这个脚本，改完运行一次：python scripts/make_target_taxonomy.py"""
import json
C = {}  # class id -> (zh, en, [(fam id, zh, en, [targets])])
def cls(cid, zh, en, fams): C[cid] = (zh, en, fams)
cls("kinase", "激酶", "Kinases", [
 ("rtk", "受体酪氨酸激酶", "Receptor tyrosine kinases", ["EGFR","HER2","HER3","c-MET","ALK","ROS1","RET","KIT","FLT3","FGFR（泛）","FGFR2","FGFR3","FGFR4","TRK (NTRK)","PDGFR","CSF1R","AXL","VEGF / VEGFR","胰岛素受体"]),
 ("angio_lig", "血管生成配体", "Angiogenic ligands", ["Ang-2"]),
 ("nrtk", "非受体酪氨酸激酶", "Non-receptor tyrosine kinases", ["BTK","BCR-ABL","JAK（泛）","JAK1","JAK2","TYK2"]),
 ("mapk", "RAF–MEK–ERK", "RAF–MEK–ERK", ["RAF（泛）","BRAF","MEK","ERK"]),
 ("pi3k", "PI3K–AKT–mTOR", "PI3K–AKT–mTOR", ["PI3Kα","PI3K（其他）","AKT","mTOR"]),
 ("cellcycle", "细胞周期激酶", "Cell-cycle kinases", ["CDK4/6","CDK2","CDK7","CDK9","WEE1","PKMYT1","Aurora A","PLK1","CDC7"]),
 ("ddrk", "DNA 损伤应答激酶", "DNA-damage-response kinases", ["ATR","ATM"]),
 ("tgfr", "TGF-β 超家族受体激酶", "TGF-β superfamily receptor kinases", ["ALK2 (ACVR1)","ALK7"]),
 ("otherk", "其他激酶", "Other kinases", ["ROCK","LRRK2","IRAK4","HPK1","PKC","PIM"]),
])
cls("ras", "RAS 通路蛋白（非激酶）", "RAS pathway (non-kinase)", [
 ("rasg", "RAS GTP 酶", "RAS GTPases", ["KRAS G12C","KRAS G12D","KRAS（泛 / 其他突变）","RAS（泛 / RAS-ON）"]),
 ("rasadapt", "磷酸酶与支架蛋白", "Phosphatases and scaffolds", ["SHP2","SHOC2"]),
])
cls("gpcr", "G 蛋白偶联受体", "GPCRs", [
 ("gpcr_met", "代谢与肽类激素受体", "Metabolic peptide-hormone receptors", ["GLP-1R","GIPR","胰高血糖素受体 (GCGR)","胰淀素受体","MC4R","Relaxin (RXFP1)","CGRP / CGRP 受体","催产素受体","SSTR2"]),
 ("gpcr_neuro", "神经递质受体", "Neurotransmitter receptors", ["毒蕈碱受体 M1/M4","5-HT2A","5-HT（其他）","多巴胺受体","κ 阿片受体","NK1 受体","食欲素受体","TAAR1","mGluR","CB1"]),
 ("gpcr_cv", "心血管与肾脏受体", "Cardiovascular and renal receptors", ["AT1 受体","内皮素受体","缓激肽 B2 受体","P2Y12"]),
 ("gpcr_imm", "免疫与炎症受体", "Immune and inflammatory receptors", ["S1P 受体","CCR8","CXCR1/2","Adenosine A2A/A2B","MRGPRX2","LPA1"]),
 ("gpcr_dev", "发育通路受体", "Developmental pathway receptors", ["Hedgehog / SMO","Wnt 通路"]),
])
cls("ion", "离子通道", "Ion channels", [
 ("ion_all", "离子通道", "Ion channels", ["Nav1.7 / Nav1.8","Nav（其他）","Kv7 (KCNQ)","NMDA 受体","GABA-A 受体","P2X3","CFTR"]),
])
cls("nr", "核受体与转录因子", "Nuclear receptors and transcription factors", [
 ("nr_hormone", "激素核受体", "Hormone nuclear receptors", ["ER (ESR1)","AR","GR（糖皮质激素受体）","盐皮质激素受体","THR-β","FXR"]),
 ("tf", "转录因子与蛋白降解靶点", "Transcription factors and degrader targets", ["HIF-2α","STAT3","STAT6","BCL6","TEAD","NRF2 / KEAP1","IKZF1/3 (Ikaros/Aiolos)","GSPT1"]),
])
cls("epi", "表观遗传", "Epigenetics", [
 ("epi_all", "写入、擦除、识别和染色质重塑", "Writers, erasers, readers, remodelers", ["EZH2","HDAC","BRD4 / BET","LSD1","PRMT5","KAT6","SMARCA2","SETDB1","WDR5","Menin","ARID1B"]),
])
cls("ddr", "DNA 修复、合成致死与有丝分裂", "DNA repair, synthetic lethality and mitosis", [
 ("parp", "PARP 家族", "PARP family", ["PARP（泛）","PARP1","PARP7"]),
 ("sl", "合成致死新靶点", "Emerging synthetic-lethal targets", ["POLQ (Polθ)","WRN","MAT2A","VPS4A","PELO","NXT1","CDS2"]),
 ("mitosis", "有丝分裂与核输出", "Mitosis and nuclear export", ["KIF18A","XPO1"]),
 ("death", "凋亡与铁死亡", "Apoptosis and ferroptosis", ["BCL-2","BCL-XL","GPX4"]),
])
cls("io", "免疫检查点与共刺激", "Immune checkpoints and co-stimulation", [
 ("io_inh", "T/NK 细胞抑制性检查点", "T/NK-cell inhibitory checkpoints", ["PD-1 / PD-L1","CTLA-4","LAG-3","TIGIT","TIM-3","NKG2A","ILT2 / ILT4 (LILRB)","HLA-G","CBL-B"]),
 ("io_myeloid", "髓系与腺苷免疫抑制", "Myeloid and adenosine suppression", ["CD47","SIRPα","CD39","CD73"]),
 ("io_costim", "共刺激受体", "Co-stimulatory receptors", ["OX40","OX40L","4-1BB","CD40","CD40L","NKG2D"]),
 ("io_innate", "先天免疫通路", "Innate immune sensors", ["STING","TLR7/8/9","TLR4","NLRP3"]),
])
cls("cyto", "细胞因子与免疫受体", "Cytokines and immune receptors", [
 ("cyto_t2", "2 型炎症", "Type 2 inflammation", ["TSLP","IL-33 / ST2","IL-4Rα","IL-13","IL-5 / IL-5R","IL-31 / IL-31RA"]),
 ("cyto_t17", "IL-23 / Th17 与 TNF", "IL-23 / Th17 and TNF", ["IL-23 / IL-23R","IL-17A/F","TNF","TL1A","IL-12","IL-36R"]),
 ("cyto_il1", "IL-1 / IL-6 炎症", "IL-1 / IL-6 inflammation", ["IL-1β / IL-1R","IL-18","IL-6 / IL-6R"]),
 ("cyto_gc", "γc 细胞因子", "Common-γ-chain cytokines", ["IL-2 (受体)","IL-15","IL-7R"]),
 ("cyto_ifn", "干扰素与 B 细胞因子", "Interferons and B-cell factors", ["IFNAR / I 型干扰素","BAFF / APRIL","BDCA2"]),
 ("cyto_traffic", "淋巴细胞归巢与抗体循环", "Lymphocyte trafficking and IgG recycling", ["α4β7 整合素","FcRn","VAP-1","半乳糖凝集素-3","GAD65（抗原特异性免疫）"]),
 ("tgfb", "TGF-β 超家族配体", "TGF-β superfamily ligands", ["TGF-β","激活素 / ActRII","Myostatin / GDF8","GDF15 / GFRAL"]),
])
cls("tsa", "肿瘤表面抗原（ADC、双抗、CAR-T 靶点）", "Tumour surface antigens (ADC, bispecific, CAR-T)", [
 ("tsa_heme", "血液肿瘤抗原", "Haematological antigens", ["CD19","CD20","CD22","CD3","BCMA","GPRC5D","FcRH5","CD38","CD123","CD33","CLL1 / CD371","CD7","CD30","CD70"]),
 ("tsa_solid", "实体瘤抗原", "Solid-tumour antigens", ["TROP2","B7-H3","B7-H4","Nectin-4","CLDN18.2","CLDN6","DLL3","PSMA","FRα (FOLR1)","CEACAM5","CDH6","CDH17","GPC3","Mesothelin","MUC1 / MUC16","EpCAM","ITGB6 / αvβ6","PTK7","STEAP1","ROR1","FAP","TfR1","组织因子 (TF)","KK-LC-1 / MAGE / NY-ESO-1 (TCR)"]),
])
cls("cvm", "心血管、代谢与肾脏", "Cardiometabolic and renal", [
 ("lipid", "血脂与载脂蛋白", "Lipids and apolipoproteins", ["PCSK9","Lp(a)","ANGPTL3","APOC3","CETP"]),
 ("metab", "代谢激素与肝脏代谢", "Metabolic hormones and liver metabolism", ["FGF21","PNPLA3","FASN","RBP4","SGLT2","Urat1 / 尿酸"]),
 ("raas", "RAAS 与血管张力", "RAAS and vascular tone", ["肾素 / AGT","醛固酮合酶 (CYP11B2)","sGC","CNP / NPR-B","APOL1"]),
 ("heart", "心肌与淀粉样变", "Myocardium and amyloidosis", ["心肌肌球蛋白","TTR"]),
])
cls("heme", "凝血、补体与血液", "Coagulation, complement and blood", [
 ("coag", "凝血与接触系统", "Coagulation and contact system", ["因子 XII","凝血因子 XI","FVIII 模拟 (FIXa × FX)","TFPI","抗凝血酶","VWF","Kallikrein (KLKB1)"]),
 ("compl", "补体", "Complement", ["C1s / C1q","MASP-2 / MASP-3","补体因子 B","补体因子 D","补体 C3","补体 C5"]),
 ("rbc", "红细胞与铁代谢", "Red cells and iron", ["丙酮酸激酶 (PKR)","Hb / HbF 诱导","TMPRSS6 / 铁调素"]),
])
cls("enz", "其他酶", "Other enzymes", [
 ("enz_onc", "肿瘤代谢酶", "Cancer metabolism", ["IDH1","IDH2","DHODH","ENPP1"]),
 ("enz_pde", "磷酸二酯酶", "Phosphodiesterases", ["PDE4","PDE10A"]),
 ("enz_other", "其他酶与蛋白酶", "Other enzymes and proteases", ["Elastase / DPP1","FAAH / MAGL","胆固醇 24-羟化酶","PAH","GCase / GBA","SARS-CoV-2 3CL 蛋白酶","SARM1"]),
])
cls("neuro", "神经退行与遗传病", "Neurodegeneration and genetic disease", [
 ("agg", "致病蛋白聚集", "Protein aggregates", ["β-淀粉样蛋白","Tau","α-突触核蛋白","SOD1"]),
 ("rna", "致病基因与 RNA 靶点", "Disease genes and RNA targets", ["HTT","C9orf72","DMPK","DUX4","MECP2","UBE3A","SMN2","Dystrophin（外显子跳跃）","Sortilin / 颗粒体蛋白","miR-124 (obefazimod)"]),
 ("neuro_other", "其他神经靶点", "Other neuroscience targets", ["Sigma-1","SV2A"]),
])

# 通路：按阶段排列，阶段内是并列的靶点；相邻阶段之间是上游 → 下游。只有一个阶段的是相关靶点分组，不画箭头
P = [
 ("ras_mapk", "RAS–MAPK", "RAS–MAPK", "生长因子受体经 SHP2 激活 RAS，再依次激活 RAF、MEK、ERK，驱动增殖。", "Growth-factor receptors activate RAS via SHP2, then RAF, MEK and ERK drive proliferation.",
  [["EGFR","HER2","HER3","c-MET","ALK","ROS1","RET","FGFR（泛）","TRK (NTRK)"],["SHP2"],["RAS（泛 / RAS-ON）","KRAS G12C","KRAS G12D","KRAS（泛 / 其他突变）"],["SHOC2","RAF（泛）","BRAF"],["MEK"],["ERK"]]),
 ("pi3k", "PI3K–AKT–mTOR", "PI3K–AKT–mTOR", "受体激活 PI3K，经 AKT 到 mTOR，调控生长和代谢。", "Receptors activate PI3K, signalling through AKT to mTOR to control growth and metabolism.",
  [["EGFR","HER2","HER3","胰岛素受体"],["PI3Kα","PI3K（其他）"],["AKT"],["mTOR"]]),
 ("angio", "肿瘤血管生成", "Tumour angiogenesis", "VEGF、Ang-2、PDGF 和 FGF 共同驱动血管新生。", "VEGF, Ang-2, PDGF and FGF drive new vessel growth.",
  [["VEGF / VEGFR","Ang-2","PDGFR","FGFR（泛）"]]),
 ("hormone_onc", "激素驱动肿瘤", "Hormone-driven cancers", "KAT6 调控雌激素受体的转录；雌激素受体驱动乳腺癌（经细胞周期蛋白 D 激活 CDK4/6），雄激素受体驱动前列腺癌。", "KAT6 controls ER transcription; ER drives breast cancer (via cyclin D and CDK4/6) and AR drives prostate cancer.",
  [["KAT6"],["ER (ESR1)","AR"],["CDK4/6"]]),
 ("cellcycle", "细胞周期", "Cell cycle", "G1/S 由 CDK4/6 和 CDK2 推进；G2/M 由 WEE1、PKMYT1 把关，Aurora A、PLK1、KIF18A 负责有丝分裂。", "CDK4/6 and CDK2 push G1/S; WEE1 and PKMYT1 gate G2/M; Aurora A, PLK1 and KIF18A run mitosis.",
  [["CDK4/6"],["CDK2","CDC7"],["WEE1","PKMYT1"],["Aurora A","PLK1","KIF18A"]]),
 ("ddr", "DNA 损伤应答", "DNA damage response", "ATM、ATR 感知损伤，经 WEE1 让细胞周期停下修复；PARP、Polθ、WRN 是不同修复途径，各自和特定缺陷合成致死。", "ATM and ATR sense damage and pause the cycle via WEE1; PARP, Polθ and WRN are repair routes that are synthetic-lethal with specific defects.",
  [["ATM","ATR"],["WEE1","PKMYT1"],["PARP1","PARP（泛）","POLQ (Polθ)","WRN"]]),
 ("apoptosis", "凋亡", "Apoptosis", "BCL-2 家族蛋白阻止线粒体凋亡。", "BCL-2 family proteins block mitochondrial apoptosis.",
  [["BCL-2","BCL-XL"]]),
 ("jak_stat", "JAK–STAT", "JAK–STAT", "细胞因子受体经 JAK 激活 STAT；IL-4/IL-13 走 STAT6，IL-6 和 IL-23 走 STAT3。", "Cytokine receptors activate STATs via JAKs; IL-4/IL-13 signal through STAT6, IL-6 and IL-23 through STAT3.",
  [["IL-4Rα","IL-13","IL-6 / IL-6R","IL-23 / IL-23R","IL-2 (受体)","IL-15","IFNAR / I 型干扰素","IL-12"],["JAK（泛）","JAK1","JAK2","TYK2"],["STAT3","STAT6"]]),
 ("type2", "2 型炎症", "Type 2 inflammation", "上皮受损释放 TSLP、IL-33，激活 Th2 和 ILC2，产生 IL-4、IL-13、IL-5，引起哮喘、特应性皮炎和 COPD 急性加重。", "Damaged epithelium releases TSLP and IL-33, driving IL-4, IL-13 and IL-5 — asthma, atopic dermatitis and COPD exacerbations.",
  [["TSLP","IL-33 / ST2"],["IL-4Rα","IL-13","IL-5 / IL-5R","IL-31 / IL-31RA"],["STAT6"]]),
 ("th17", "IL-23 / Th17", "IL-23 / Th17", "IL-23 维持 Th17 细胞，产生 IL-17A/F；TL1A 促进 Th17，TNF、IL-36 放大肠道、关节和皮肤炎症。", "IL-23 sustains Th17 cells producing IL-17A/F; TL1A promotes Th17, while TNF and IL-36 amplify gut, joint and skin inflammation.",
  [["TL1A","IL-23 / IL-23R","IL-12"],["IL-17A/F","TNF","IL-36R"]]),
 ("innate", "先天免疫与炎症小体", "Innate immunity and inflammasome", "TLR 经 IRAK4 激活 NF-κB；NLRP3 炎症小体产生 IL-1β 和 IL-18；STING 感知胞质 DNA，ENPP1 降解其信号分子 cGAMP。", "TLRs signal through IRAK4; the NLRP3 inflammasome makes IL-1β and IL-18; STING senses cytosolic DNA and ENPP1 degrades its messenger cGAMP.",
  [["TLR7/8/9","TLR4"],["IRAK4","NLRP3","STING","ENPP1"],["IL-1β / IL-1R","IL-18","IL-6 / IL-6R","IFNAR / I 型干扰素"]]),
 ("bcr", "B 细胞受体信号", "B-cell receptor signalling", "CD19、CD22 是 B 细胞受体的共受体，信号经 BTK 传递；CD20 是 B 细胞清除抗体的靶点。", "CD19 and CD22 are BCR co-receptors signalling through BTK; CD20 is the target for B-cell depletion.",
  [["CD19","CD22","CD20"],["BTK"]]),
 ("plasma", "浆细胞与致病抗体", "Plasma cells and pathogenic IgG", "BAFF/APRIL 维持浆细胞（BCMA、CD38），浆细胞产生 IgG，FcRn 让 IgG 循环延长半衰期；阻断 FcRn 可快速清除致病抗体。", "BAFF/APRIL sustain plasma cells (BCMA, CD38), which make IgG that FcRn recycles; blocking FcRn clears pathogenic antibodies.",
  [["BAFF / APRIL"],["BCMA","CD38"],["FcRn"]]),
 ("checkpoint", "T 细胞检查点", "T-cell checkpoints", "PD-1、CTLA-4 是第一代；LAG-3、TIGIT、TIM-3、NKG2A 是常见的联用尝试；CBL-B、HPK1 是胞内刹车。", "PD-1 and CTLA-4 came first; LAG-3, TIGIT, TIM-3 and NKG2A are the usual add-ons; CBL-B and HPK1 are intracellular brakes.",
  [["PD-1 / PD-L1","CTLA-4","LAG-3","TIGIT","TIM-3","NKG2A","ILT2 / ILT4 (LILRB)","CBL-B","HPK1"]]),
 ("adenosine", "腺苷免疫抑制", "Adenosine suppression", "ATP 经 CD39、CD73 降解成腺苷，作用于 A2A/A2B 受体抑制 T 细胞。", "CD39 and CD73 convert ATP to adenosine, which suppresses T cells through A2A/A2B.",
  [["CD39"],["CD73"],["Adenosine A2A/A2B"]]),
 ("dontEat", "“别吃我”信号", "“Don't eat me” signal", "肿瘤细胞上的 CD47 和巨噬细胞上的 SIRPα 结合，阻止吞噬。", "CD47 on tumour cells binds SIRPα on macrophages to block phagocytosis.",
  [["CD47"],["SIRPα"]]),
 ("costim", "共刺激", "Co-stimulation", "OX40/OX40L、4-1BB、CD40/CD40L 增强 T 细胞和抗原呈递；在自身免疫里则反过来阻断。", "OX40/OX40L, 4-1BB and CD40/CD40L boost T cells and antigen presentation; in autoimmunity they are blocked instead.",
  [["CD40","CD40L","OX40","OX40L","4-1BB"]]),
 ("incretin", "肠促胰素与体重", "Incretins and body weight", "GLP-1R、GIPR、胰高血糖素受体和胰淀素受体是减重药的主轴；MC4R 在下丘脑；GDF15、FGF21、肌肉保护（Myostatin/ActRII）是补充方向。", "GLP-1R, GIPR, glucagon and amylin receptors are the core of obesity drugs; MC4R sits in the hypothalamus; GDF15, FGF21 and muscle preservation (myostatin/ActRII) are add-ons.",
  [["GLP-1R","GIPR","胰高血糖素受体 (GCGR)","胰淀素受体","MC4R","GDF15 / GFRAL","FGF21","Myostatin / GDF8","激活素 / ActRII","ALK7"]]),
 ("lipid", "血脂", "Lipids", "PCSK9 降解 LDL 受体；ANGPTL3、APOC3 抑制脂蛋白脂肪酶；Lp(a) 和 CETP 是独立风险通路。", "PCSK9 degrades the LDL receptor; ANGPTL3 and APOC3 inhibit lipoprotein lipase; Lp(a) and CETP are separate risk pathways.",
  [["PCSK9","ANGPTL3","APOC3","Lp(a)","CETP"]]),
 ("masld", "代谢性脂肪肝", "Fatty liver (MASH)", "THR-β、FGF21、FXR 改善肝脏脂肪代谢；FASN 抑制从头合成脂肪；PNPLA3 是遗传风险基因。", "THR-β, FGF21 and FXR improve liver fat metabolism; FASN blocks de-novo lipogenesis; PNPLA3 is the genetic risk gene.",
  [["THR-β","FGF21","FXR","FASN","PNPLA3","GLP-1R"]]),
 ("raas", "RAAS 与血压", "RAAS and blood pressure", "肾素切 AGT 生成血管紧张素，作用于 AT1 受体；醛固酮合酶产生醛固酮，作用于盐皮质激素受体；内皮素是另一条缩血管通路。", "Renin cleaves AGT to make angiotensin acting on AT1; aldosterone synthase makes aldosterone acting on the mineralocorticoid receptor; endothelin is a separate vasoconstrictor axis.",
  [["肾素 / AGT"],["AT1 受体","醛固酮合酶 (CYP11B2)"],["盐皮质激素受体","内皮素受体"]]),
 ("coag", "凝血", "Coagulation", "接触途径从 FXII 到 FXI，外源途径由组织因子启动、TFPI 抑制；两者汇合后由 FVIII/FIX 放大生成凝血酶，抗凝血酶负责关停。血友病药物从 FVIII 模拟、TFPI、抗凝血酶三个方向重新平衡。", "The contact path runs FXII → FXI; the extrinsic path starts with tissue factor and is held back by TFPI; both are amplified by FVIII/FIX into thrombin, which antithrombin shuts off. Haemophilia drugs rebalance via FVIII mimetics, TFPI or antithrombin.",
  [["因子 XII","组织因子 (TF)"],["凝血因子 XI","TFPI"],["FVIII 模拟 (FIXa × FX)"],["抗凝血酶"]]),
 ("platelet", "血小板", "Platelets", "VWF 介导血小板黏附，P2Y12 介导血小板活化。", "VWF mediates platelet adhesion and P2Y12 platelet activation.",
  [["VWF","P2Y12"]]),
 ("kallikrein", "激肽释放酶–缓激肽", "Kallikrein–bradykinin", "FXII 激活血浆激肽释放酶，产生缓激肽作用于 B2 受体，引起遗传性血管性水肿发作。", "FXII activates plasma kallikrein, releasing bradykinin acting on the B2 receptor — the driver of hereditary angioedema attacks.",
  [["因子 XII"],["Kallikrein (KLKB1)"],["缓激肽 B2 受体"]]),
 ("complement", "补体", "Complement", "经典途径（C1s/C1q）、凝集素途径（MASP-2）、旁路途径（因子 B、因子 D）汇合到 C3，再到 C5 和膜攻击复合物。", "Classical (C1s/C1q), lectin (MASP-2) and alternative (factors B and D) paths converge on C3, then C5 and the membrane attack complex.",
  [["C1s / C1q","MASP-2 / MASP-3","补体因子 B","补体因子 D"],["补体 C3"],["补体 C5"]]),
 ("iron", "铁代谢与红细胞", "Iron and red cells", "TMPRSS6 抑制铁调素；TfR1 负责铁摄取；PKR 激活剂和 HbF 诱导用于溶血性贫血。", "TMPRSS6 suppresses hepcidin; TfR1 takes up iron; PKR activators and HbF inducers treat haemolytic anaemias.",
  [["TMPRSS6 / 铁调素","TfR1","丙酮酸激酶 (PKR)","Hb / HbF 诱导"]]),
 ("tgfb", "TGF-β 超家族", "TGF-β superfamily", "TGF-β、激活素、肌生长抑制素和 GDF 通过 ALK 受体激酶信号；ALK2 突变导致进行性骨化性纤维发育不良。", "TGF-β, activins, myostatin and GDFs signal through ALK receptor kinases; ALK2 mutations cause FOP.",
  [["TGF-β","激活素 / ActRII","Myostatin / GDF8"],["ALK2 (ACVR1)","ALK7"]]),
 ("hippo_wnt", "发育信号通路", "Developmental signalling", "Wnt、Hedgehog 和 Hippo–TEAD 通路在部分肿瘤里异常激活。", "Wnt, Hedgehog and Hippo–TEAD pathways are hijacked in some cancers.",
  [["Wnt 通路","Hedgehog / SMO","TEAD"]]),
 ("alz", "阿尔茨海默病", "Alzheimer's disease", "淀粉样蛋白级联假说：β-淀粉样蛋白沉积在先，随后 Tau 缠结扩散。", "Amyloid cascade: amyloid-β deposits first, then tau tangles spread.",
  [["β-淀粉样蛋白"],["Tau"]]),
 ("pd", "帕金森病", "Parkinson's disease", "LRRK2 和 GCase 是遗传风险，汇合到 α-突触核蛋白聚集。", "LRRK2 and GCase are genetic risks converging on α-synuclein aggregation.",
  [["LRRK2","GCase / GBA"],["α-突触核蛋白"]]),
 ("als", "ALS 与额颞叶痴呆", "ALS and FTD", "SOD1、C9orf72 是 ALS 的致病基因，颗粒体蛋白缺失导致额颞叶痴呆，SARM1 驱动轴突变性。", "SOD1 and C9orf72 cause ALS, progranulin loss causes FTD, and SARM1 drives axon degeneration.",
  [["SOD1","C9orf72","Sortilin / 颗粒体蛋白","SARM1"]]),
 ("psych", "精神与睡眠", "Psychiatry and sleep", "精神分裂症从多巴胺受体转向毒蕈碱 M1/M4 和 TAAR1；抑郁有 5-HT2A 致幻剂、NMDA 和 κ 阿片；睡眠是食欲素受体。", "Schizophrenia is moving from dopamine receptors to muscarinic M1/M4 and TAAR1; depression has 5-HT2A psychedelics, NMDA and κ-opioid; sleep is the orexin receptors.",
  [["多巴胺受体","毒蕈碱受体 M1/M4","TAAR1","5-HT2A","NMDA 受体","κ 阿片受体","GABA-A 受体","食欲素受体"]]),
 ("pain", "疼痛、癫痫与咳嗽", "Pain, epilepsy and cough", "Nav1.7/1.8 是外周痛觉通道；Kv7、SV2A 用于癫痫；P2X3 用于慢性咳嗽；CGRP 用于偏头痛。", "Nav1.7/1.8 carry peripheral pain; Kv7 and SV2A treat epilepsy; P2X3 treats chronic cough; CGRP treats migraine.",
  [["Nav1.7 / Nav1.8","Nav（其他）","Kv7 (KCNQ)","SV2A","P2X3","CGRP / CGRP 受体","FAAH / MAGL","CB1"]]),
 ("epi_onc", "表观遗传与转录依赖", "Epigenetic and transcriptional dependencies", "Menin–KMT2A 驱动特定白血病；EZH2、PRMT5、LSD1、BET 和 CDK7/CDK9 是转录调控的不同环节。", "Menin–KMT2A drives specific leukaemias; EZH2, PRMT5, LSD1, BET and CDK7/CDK9 hit different points of transcriptional control.",
  [["Menin","EZH2","LSD1","HDAC","SETDB1","WDR5","BRD4 / BET","CDK7","CDK9"]]),
]

# 额外关系：配体–受体、突变–泛靶点、合成致死、同一复合物
L = [
 ["KRAS G12C","RAS（泛 / RAS-ON）","variant"],["KRAS G12D","RAS（泛 / RAS-ON）","variant"],["KRAS（泛 / 其他突变）","RAS（泛 / RAS-ON）","variant"],
 ["BRAF","RAF（泛）","variant"],["PI3Kα","PI3K（其他）","variant"],["PARP1","PARP（泛）","variant"],["JAK1","JAK（泛）","variant"],["JAK2","JAK（泛）","variant"],
 ["FGFR2","FGFR（泛）","variant"],["FGFR3","FGFR（泛）","variant"],["FGFR4","FGFR（泛）","variant"],["5-HT2A","5-HT（其他）","variant"],["Nav1.7 / Nav1.8","Nav（其他）","variant"],
 ["CD47","SIRPα","ligand"],["CD40","CD40L","ligand"],["OX40","OX40L","ligand"],["GDF15 / GFRAL","ALK7","pathway"],
 ["BAFF / APRIL","BCMA","ligand"],["IL-13","IL-4Rα","ligand"],["TSLP","IL-33 / ST2","pathway"],["Myostatin / GDF8","激活素 / ActRII","ligand"],
 ["HLA-G","ILT2 / ILT4 (LILRB)","ligand"],["Hb / HbF 诱导","丙酮酸激酶 (PKR)","pathway"],
 ["MAT2A","PRMT5","synleth"],["WRN","PARP1","synleth"],["POLQ (Polθ)","PARP1","synleth"],["ATR","ATM","synleth"],["PKMYT1","WEE1","pathway"],
 ["SMARCA2","ARID1B","synleth"],["VPS4A","CDS2","synleth"],["SHOC2","SHP2","complex"],["Menin","KAT6","complex"],
 ["IKZF1/3 (Ikaros/Aiolos)","GSPT1","complex"],["BCL-2","BCL-XL","complex"],["TTR","RBP4","complex"],["CD3","CD19","engager"],["CD3","BCMA","engager"],["CD3","DLL3","engager"],
]
REL = {"variant": ("突变 / 亚型", "Mutant / isoform"), "ligand": ("配体–受体", "Ligand–receptor"), "synleth": ("合成致死", "Synthetic lethal"),
       "complex": ("同一复合物或功能互补", "Same complex / complementary"), "pathway": ("同一信号轴", "Same signalling axis"), "engager": ("双抗常见搭配", "Common bispecific pairing")}

out = {"_about": "靶点分类和关系。classes → families → targets；pathways 的 steps 是按上下游排列的阶段，同一阶段的靶点并列（只有一个阶段的是相关靶点分组，没有上下游）；links 是通路之外的直接关系。人工整理，新靶点在 build 时会报出来。",
       "rel_lbl": REL, "classes": [], "pathways": [], "links": L}
for cid, (zh, en, fams) in C.items():
    out["classes"].append({"id": cid, "zh": zh, "en": en, "families": [{"id": f, "zh": a, "en": b, "targets": ts} for f, a, b, ts in fams]})
for pid, zh, en, dzh, den, steps in P:
    out["pathways"].append({"id": pid, "zh": zh, "en": en, "dzh": dzh, "den": den, "steps": steps})
json.dump(out, open("data/target_taxonomy.json", "w"), ensure_ascii=False, indent=1)

# 核对
idx = [x["g"] for x in json.load(open("docs/targets_index.json"))["targets"]]
assigned = [t for c in out["classes"] for f in c["families"] for t in f["targets"]]
import collections
dup = [t for t, n in collections.Counter(assigned).items() if n > 1]
print("unassigned:", [t for t in idx if t not in assigned])
print("unknown in classes:", [t for t in assigned if t not in idx])
print("dups:", dup)
print("unknown in pathways:", sorted({t for p in out["pathways"] for s in p["steps"] for t in s} - set(idx)))
print("unknown in links:", sorted({t for l in L for t in l[:2]} - set(idx)))
