# 二轮牌组（红宝书 2026）

一轮只背单词释义（见仓库根 `README.md`）。二轮补的是**变形、派生、同义反义、词组搭配、例句**——
即「认识这个词」升级为「会用这个词」。

## 怎么用

```bash
# 导入（Anki → 文件 → 导入）
round2/红宝书二轮_全量.apkg
```

导入后牌组：`红宝书二轮` → `必考词` / `基础词` → `Unit 01 …`（与一轮的 56 个子牌组一一对应，
可以按单元挑着做）。

| 牌组 | 卡片数 | 说明 |
|---|---|---|
| 全量 | 4292 notes / **10311 cards** | 每词 2 张基础卡 + 有合格例句的再加 1 张填空卡（1727 张） |

三张卡的分工：

| 模板 | 正面 | 背面 | 用途 |
|---|---|---|---|
| ①词义卡 | 单词 + 音标 + 词性 + 发音 | 释义、变形、派生、同义反义、词组、例句、助记 | 主体 |
| ②变形派生卡 | 单词（只有词头） | 变形（不规则标 ✱）+ 派生 + 同义反义 + 词组，**不含释义** | 专攻二轮增量 |
| ③例句填空卡 | 例句挖空 `____` + 中文提示 | 单词 + 全信息 | 检验「会用」 |

二轮牌组也已经接进 `adhd_plan.py`：它按名字匹配 `红宝`，所以一轮、二轮会一起套同一个档位；
只想改其中一个就加 `--match`：

```bash
python3 adhd_plan.py --tier std --match 二轮    # 只改二轮牌组的每日上限
python3 adhd_plan.py --tier std --dry-run      # 先在副本上演练
```

建议：一轮没做完的单元先别开二轮（二轮是重建，不是复习）。**新词上限沿用一轮的档位**
（`python3 adhd_plan.py --tier std` 会一并改到 `红宝书二轮`），全量 4292 词按 30/天约 143 天，
所以实操上是**按单元推进**：一轮背到哪个单元，二轮就跟到哪个单元，用「自选学习」或
按单元点开子牌组即可。

## 数据质量（2026-11-05 版）

词条来自扫描件 OCR（`00-红宝书_无文本层.pdf` 的两层文本合并），逐字段填充率：

| 字段 | 覆盖 | 上卡情况 |
|---|---|---|
| 释义 `senses` | 3390 / 4292 = 79.0% | ✅ 直接上 |
| 助记 | 29.1% | ✅ 直接上 |
| 词组 `phrases` | 1052 = 24.5% | ✅ 直接上（书上只有部分词条带词组） |
| 派生 `deriv` | 685 = 16.0% | ✅ 直接上 |
| 例句 `examples` | 2305 = 53.7% | ⚠️ 约 2% 有 OCR 粘连（`Itwas a. privilege tohear`），其余可用 |
| 同义 `syn` | 363 = 8.5% | ⚠️ 单词偶有粘连（已按词表切分过一次） |
| 反义 `ant` | 248 = 5.8% | ⚠️ 中文释义偶有错字 |
| 音标 | 回退一轮数据 | ✅ 书上的音标 OCR 后是乱码，不用 |

没有 `senses` 的 902 个词只剩「词义卡」，背面用一轮释义兜底——这些词本来就是书里只给了一行释义的
简单词。

## 重新生成

```bash
# 1) 合并中英两层文本层（输入是两个 layered PDF，已固化在脚本里）
python3 round2/tools/merge_layers.py

# 2) OCR 文本 → 结构化词条（2.5 s，4292 词）
python3 round2/tools/parse_entries.py            # 生成 data/entries_r2.json
python3 round2/tools/parse_entries.py --units    # 重算 ocr/units.json

# 2.5) 修补英文间距（OCR 把 `oldkindrope` / `breaksb.s` 这类粘在一起）
python3 round2/tools/repair_spacing.py           # 原地改写 entries_r2.json，自动留 .bak

# 3) 出牌组
uv run --with genanki python3 round2/tools/gen_round2_deck.py \
    --data round2/data/entries_r2.json --out "round2/红宝书二轮_全量.apkg"
```

数据契约见 [`SCHEMA.md`](SCHEMA.md)；OCR 合并的质量报告见 `data/merge_report.md`，
词条解析的报告见 `data/parse_report.md`（含 5 个词条的人工核对）。

## 英文间距修补（`repair_spacing.py`）

OCR 在「中文 + 英文」混排行里会吞掉空格。修补器用「4292 词条 + 各词性变形 + 功能词」
做词表、DP 切分，只动英文 run，中文不碰；并且刻意保守——**切出来的每一段必须含一个功能词**，
否则宁可不切（避免把 `fireflies` 切成 `Fire flies`）。

一轮效果：改动词条 198 个、切分 275 处（2 段 194 / 3 段 75）、`syn` 拆开 16 个，
例句里 `TheMonument` → `The Monument`、`Thereis ahigh` → `There is a high` 这类修复。

## 已知残缺

- OCR 整页丢失 4 页：**p204 / p292 / p357 / p388**，这些页上的词条只剩一轮释义。
- 445 个词条没有解析出正文块（`no_body`），457 个没有 `senses`（`no_senses`）。
- 词条音标一律用一轮数据；`pos` 有 58% 能解析出，其余靠释义与词尾推断，用于生成变形。
- 派生词的中文释义偶有错字（`松驰` 之类），不影响理解，发现可顺手在 Anki 里改。
