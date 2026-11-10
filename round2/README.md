# 二轮牌组（红宝书 2026）

一轮只背单词释义（见仓库根 `README.md`）。二轮补的是**变形、派生、同义反义、词组搭配、例句**——
即「认识这个词」升级为「会用这个词」。2026-11-10 起二轮改成**多向提问**：一轮已经考过「单词 → 中文」，
所以二轮默认反过来考（中文 → 单词、默写变形、短语填空），不再重复出「看单词想中文」的卡。

## 怎么用

```bash
# 导入（Anki → 文件 → 导入）
round2/红宝书二轮_全量.apkg
```

导入后牌组：`红宝书二轮` → `必考词` / `基础词` → `Unit 01 …`（与一轮的 56 个子牌组一一对应，
可以按单元挑着做）。

| 牌组 | 卡片数 | 说明 |
|---|---|---|
| 默认（④⑤⑥③） | 4292 notes / **8703 cards** | 只出反向题，和一轮不重复 |
| `--all` | 4292 notes / **17951 cards** | 再加 ①②（与一轮重复）和 ⑦ 派生反推 |

七个模板的分工（**默认只出 ③④⑤⑥**，正面绝不出现答案）：

| 模板 | 正面 | 背面 | 默认 |
|---|---|---|---|
| ①词义卡 | 单词 + 音标 + 词性 + 发音 | 释义、变形、派生、同义反义、词组、例句、助记 | ✗（一轮已考过） |
| ②变形派生卡 | 单词（只有词头） | 变形（不规则标 ✱）+ 派生 + 同义反义 + 词组，**不含释义** | ✗ |
| ③例句填空卡 | 例句挖空 `____` + 中文提示 | 单词 + 全信息 | ✓ |
| ④中译英 | 词性 + 中文释义（`ZhAsk`）+「↑ 想出对应的英文单词」 | 单词 + 音标 + 发音 + 释义 + 变形 + 派生 + 同义反义 + 词组 + 例句 | ✓ |
| ⑤变形默写 | 单词 + 词性 +「写出变形：过去式 · 过去分词 · 现在分词」 | 变形（不规则标 ✱）+ 例句 + 词组 | ✓ |
| ⑥短语填空 | 固定搭配里挖掉本词（`in ＿＿ with`）+ 中文 | 单词 + 词组全列表 + 例句 | ✓ |
| ⑦派生反推 | 派生词 + 词性 + 中文（`strained adj. 紧张的`）+「↑ 它的母词是？」 | 单词 + 派生全列表 + 释义 | 需 `--with-deriv` / `--all` |

命中数（2026-11-10 版，`--all`）：④ 3340 / ⑤ 2642 / ⑥ 989 / ⑦ 664（③ 1732）。
**有料才出**：题面字段为空就不出这张卡（qfmt 整体包在 `{{#字段}}` 里，靠 Anki 的模板 req 生效），
所以 902 个没有 `senses` 的词不出 ④，只有单一变形的词不出 ⑤。

```bash
# 默认：④⑤⑥③（和一轮不重复）
uv run --with genanki python3 round2/tools/gen_round2_deck.py \
    --data round2/data/entries_r2.json --out round2/红宝书二轮_全量.apkg

# 挑模板：-t 可选 card/extra/cloze/chinese/forms/phrase/deriv
uv run --with genanki python3 round2/tools/gen_round2_deck.py --data round2/data/entries_r2.json \
    --out /tmp/r2.apkg -t chinese,forms,phrase,cloze --with-deriv   # 默认 + ⑦
uv run --with genanki python3 round2/tools/gen_round2_deck.py --data round2/data/entries_r2.json \
    --out /tmp/r2.apkg --all                                        # 1~7 全部
```

换 `--templates` 重新导入时，Anki 按模板名匹配已有模板，不会凭空多出一套卡；但旧模板集的卡会被
一并更新/删除，所以建议**一次定好模板集**，之后只重新生成同一个档位。

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

# 3) 出牌组（默认 ④⑤⑥③；--all 出 1~7 全部）
uv run --with genanki python3 round2/tools/gen_round2_deck.py \
    --data round2/data/entries_r2.json --out "round2/红宝书二轮_全量.apkg" --all
```

## 四个题面字段（④~⑦）是怎么抽的

都在 `gen_round2_deck.py` 里现算，不改数据契约（`SCHEMA.md` 不动）：

| 字段 | 来源 | 规则 |
|---|---|---|
| `ZhAsk` | `senses[].items[]` | 取「序号 + 冒号前的中文部分」，丢掉冒号后的英文用法/例句；括注里的英文噪声（`(c/u）`）整段丢；`~`→`＿＿`；按 sense 分组标词性（`vi.`→`v.`）；最多 5 条 |
| `FormAsk` | `inflect.forms()` | 只列**哪几种**变形要考（过去式→过去分词→第三人称单数→现在分词→复数→比较级→最高级），不给答案、不暗示是否不规则；只有 1 种变形的词不出卡 |
| `PhraseAsk` | `phrases[]` | 挑 1–2 条含本词（或其变形，按词边界、大小写不敏感）的短语，挖成 `＿＿`，后面附中文；挖完还残留词形（`go ape/apeshit`）或中文栏带本词的，换下一条 |
| `DerivAsk` | `deriv[]` | 派生词 + 词性 + 中文，最多 3 条；OCR 把音标错当派生词的（`kanfai`、`taa'ri`）用「长得像英文词 + 词首 3 字母相同或带派生后缀」挡掉 |

正面漏答案有测试卡：④ 抽 200 张 / 全量 3340 张、⑥ 全量 989 张的题面均不含本词任何词形，
⑤ 2642 张题面不含变形答案也不带 ✱。

数据契约见 [`SCHEMA.md`](SCHEMA.md)；OCR 合并的质量报告见 `data/merge_report.md`，
词条解析的报告见 `data/parse_report.md`（含 5 个词条的人工核对）。

## 英文间距修补（`repair_spacing.py`）

OCR 在「中文 + 英文」混排行里会吞掉空格。修补器用「4292 词条 + 各词性变形 + 功能词」
做词表、DP 切分，只动英文 run，中文不碰；并且刻意保守——**切出来的每一段必须含一个功能词**，
否则宁可不切（避免把 `fireflies` 切成 `Fire flies`）。

一轮效果：改动词条 198 个、切分 275 处（2 段 194 / 3 段 75）、`syn` 拆开 16 个，
例句里 `TheMonument` → `The Monument`、`Thereis ahigh` → `There is a high` 这类修复。

## 可搜索 PDF（中英混排）

`英语红宝书26/[OCR]mix_00-红宝书_无文本层.layered.pdf`（444 页 / 380 MB）是把中文层
（汉字准、英文粘连）在不改行框的前提下就地修补英文间距后写回成**不可见文本层**的版本：

```bash
PYTHONPATH=<pymupdf 与 mupdf 的 site-packages> \
python3 round2/tools/make_mixed_layer.py      # 约 20 s，需 pymupdf
```

- 汉字 273,849，`【词义】5558 / 【词组】1267 / 【派生】887 / 【同义】489 / 【助记】1550`，
  与中文层逐项一致；4292 词条原形命中 4283。
- 页图与原扫描逐像素一致（`maxdiff = 0`），文本层不可见，不改变阅读观感。
- 位置上不再出现「文本块错位」：只借中文层行框，不做跨层逐行配对——试过塞合并结果，
  两边行分组不同会错行/丢行。

## 已知残缺

- OCR 整页丢失 4 页：**p204 / p292 / p357 / p388**，这些页上的词条只剩一轮释义。
- 445 个词条没有解析出正文块（`no_body`），457 个没有 `senses`（`no_senses`）。
- 词条音标一律用一轮数据；`pos` 有 58% 能解析出，其余靠释义与词尾推断，用于生成变形。
- 派生词的中文释义偶有错字（`松驰` 之类），不影响理解，发现可顺手在 Anki 里改。
