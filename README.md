# Hit or Miss

临床试验读出追踪网站：主要终点达到（hit）还是落空（miss）。

同一条读出，研发、BD / 投资、临床医生各看各的重点。

## 内容

**精选解读**：人工整理的重要读出（III 期成败、同类联动、催化剂日历），每条按三种视角给出点评，并附来源。

**注册库全量**：来自 [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api) 的企业申办 II/III 期试验，分四类：

| 分区 | 说明 |
|---|---|
| 新公布结果 | 最近 180 天在注册库登记结果的试验，附主要终点 p 值 |
| 刚完成待公布 | 主要完成日在最近 120 天、尚未登记结果 |
| 即将完成 | 未来 180 天内到达主要完成日的 III 期（催化剂日历） |
| 提前终止 | 最近更新为终止 / 暂停 / 撤回，附停止原因 |

## 目录

```
docs/index.html          网站（GitHub Pages 从 /docs 发布）
site/template.html       网站模板，不含数据
data/trials.json         抓取到的注册库数据
scripts/fetch_trials.py  抓取 ClinicalTrials.gov，只用 Python 标准库
scripts/build_site.py    把 trials.json 内嵌进模板，生成 docs/index.html
run_update.command       macOS 双击运行：抓取 + 重建
.github/workflows/       每周一自动更新数据
```

## 本地更新

```bash
python scripts/fetch_trials.py --out data/trials.json          # 默认仅企业申办，回看 180 天
python scripts/fetch_trials.py --all-sponsors --days 365 ...    # 包含学术申办、回看一年
python scripts/build_site.py site/template.html data/trials.json docs/index.html
```

只改了分类规则、不想重新联网时：

```bash
python scripts/fetch_trials.py --reclassify data/trials.json
```

## 说明

- 治疗领域和药物形式按疾病关键词与药名后缀自动分类；只有研发代号的分子归为「代号分子（形式待定）」。
- p 值取自注册库登记的主要终点统计分析，只作信号参考，不等于官方「达到 / 未达到」判定。
- 注册库要求结果在主要完成后约一年内登记，因此「新公布结果」通常晚于新闻稿。
- 精选解读的点评是编辑观点，不构成投资或诊疗建议。
