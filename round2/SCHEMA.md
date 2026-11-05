# 二轮数据结构契约（round2）

所有脚本共享本契约，改动必须同步改这里。

## 文件位置

| 路径 | 内容 | 是否入库 |
|------|------|----------|
| `round2/tools/ocr_pdf.py` | PDF → 逐页 OCR 文本 | 入库 |
| `round2/tools/parse_entries.py` | OCR 文本 → `entries_r2.json` | 入库 |
| `round2/tools/gen_round2_deck.py` | JSON → apkg | 入库 |
| `round2/ocr/page_XXXX.txt` | OCR 中间产物，一页一文件 | **不入库** |
| `round2/ocr/units.json` | 单元 → PDF 页码区间映射 | 入库（小） |
| `round2/data/entries_r2.json` | 解析后的二轮数据 | 不入库 |
| `round2/data/mock_entries.json` | 造出来的假数据，供牌组脚本自测 | 入库（小） |
| `round2/红宝书二轮_*.apkg` | 产出的牌组 | **不入库** |

## OCR 中间产物格式

`round2/ocr/page_0040.txt`：UTF-8，纯文本。按**阅读顺序**（先左栏后右栏）拼接，
两栏之间用一个换行分隔，不保留页码/页眉（页眉「红宝书」与页码行应被丢弃）。
行内不得插入人工标注；不得做任何「纠错」——纠错属于下游脚本的事。

## `units.json`

```json
{"必考词": [{"unit": 1, "pdf_start": 9, "pdf_end": 15}, ...],
 "基础词": [{"unit": 1, "pdf_start": 199, "pdf_end": 206}, ...]}
```

`pdf_start` = 该单元单词表（勾选框清单）所在页；`pdf_end` = 该单元最后一页。
页码均为 PDF 物理页码，1 起。区间必须互不重叠且覆盖全部正文页。

## `entries_r2.json`

```json
{
  "meta": {"source": "2026 红宝书考研英语词汇", "pdf": "00-红宝书.pdf",
           "pages_ocr": 444, "generated": "2026-11-04T00:00:00"},
  "entries": [ { ...条目... } ]
}
```

条目字段（**除 `word` 外都可缺失/为空**，缺失用 `null` 或 `[]`，不要编造：

| 字段 | 类型 | 说明 |
|------|------|------|
| `word` | str | 词条原形，必须与一轮 `all_entries_v2.json` 的 `word` 完全一致（小写匹配） |
| `phonetic` | str\|null | 音标，去掉方括号，如 `streɪn` |
| `pos` | str\|null | 全书级词性汇总，如 `v./n.` |
| `section` | str | `必考词` 或 `基础词` |
| `unit` | int | 单元号 |
| `pdf_pages` | int[] | 该词条正文出现的 PDF 页码 |
| `mnemonic` | str\|null | 书上【助记】原文（没有则沿用一轮 JSON 的 mnemonic） |
| `senses` | obj[] | `[{"pos": "v.", "items": ["①使紧张，尽力使用：~ one's eyes 瞪大眼睛看", "..."]}]`，`items` 保留书上「中文释义：英文用法/例句 中文翻译」的原始写法，仅清空白 |
| `syn` | str[] | 【同义】里的英文词，按书上顺序 |
| `ant` | obj[] | 【反义】`[{"word":"relaxation","pos":"n.","meaning":"松弛，缓和"}]` |
| `deriv` | obj[] | 【派生】`[{"word":"strained","phonetic":"streɪnd","pos":"adj.","meaning":"紧张的；勉强的，不自然的"}]` |
| `phrases` | obj[] | 【词组】/【搭配】`[{"en":"be prey to sth.","zh":"被……捕食"}]` |
| `examples` | obj[] | 例句 `[{"en":"...","zh":"..."}]`，允许为空；从 senses 里尽力抽取 |
| `ocr_confidence` | float\|null | 该条目解析置信度 0–1，供人工抽查排序 |
| `flags` | str[] | 问题标记，如 `["no_senses"]`、`["word_not_in_unit_list"]`、`["ocr_garbled"]` |

## 硬约束

1. **不得编造书上没有的中文释义**。解析不到的字段留空，交给下游插件/人工补。
2. `deriv` / `syn` / `ant` 里的英文词必须能在书上 OCR 文本里找到对应字串（大小写不敏感），
   否则视为幻觉写进 `flags`。
3. 一个词在一轮 JSON 里唯一。解析结果必须能按 `word` join 回一轮数据；对不上的词
   （OCR 把 `strain` 认成 `strairn` 之类）走模糊匹配，匹配失败写入 `unmatched.json` 而不是硬塞。
4. 词条顺序按 `section`、`unit`、书上次序排列，便于按单元出牌组。
