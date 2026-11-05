# OCR 双文本层合并报告

生成时间：2026-11-05 10:58:03　脚本：`round2/tools/merge_layers.py`　页数：444　耗时：78s

## 输入

| 层 | 文件 | 强项 | 弱项 |
|----|------|------|------|
| 中文 | `[OCR]ch_00-红宝书_无文本层_20261104_2211.layered.pdf` | 汉字与 `【】` 标记准 | 英文单词粘连、无词间空格 |
| 英文 | `[OCR]_00-红宝书_无文本层_20261104_1728.layered.pdf` | 英文分词准、有词间空格 | 中文全废（`AE+`、`#0v.`） |

## 算法

1. 两层都按「先左栏（x 中心 < 863）后右栏、栏内按 `bottom` 升序、行内按 x」排成字符流；按 `bottom` 容差 8 pt 聚成视觉行，聚完再把同一行被 OCR 拆开的box 合回去（`bottom` 差 ≤14 pt 且 x 区间相接）。
2. 丢页眉（bottom ≤ 163 pt 的「红宝书」条带）与页脚页码（top ≥ 2360 pt，或整行只有数字/装饰符）。
3. 英文层只取 ASCII 字母数字拼成骨架串 `s`（记着每个字符到原字符的下标），中文层每行切成 Latin run / CJK run，CJK run 原样保留。
4. 先做**行级对齐**：把两层的行内容规范化后用 `difflib` 对行序列，能逐字对上的行直接配成一对，乱码行按比例单调分配。于是每个 Latin run 只会在它自己那行对应的英文区间（±40 字符）里找，指针不会漂到别的行去。
5. Latin run 规范化后在 `s` 里做**字符级**精确查找，命中区间取英文层**原文**（中间的空格是英文层真实字符，自动带回）。允许命中落在英文 token 内部：`（onupon）` 能从英文层的 `on/uponThe` 里取回 `on/upon`，剩下的 `The` 留给下一个 run。
6. 精确查找失败 → difflib 相似度 ≥0.80 兜底 → 仍失败则保留中文层原文（不丢内容）。
7. `~`（词条占位符）单独切 run，所以 `of~on` 能拼成 `of ~ on`；英文层把分隔符丢了（`become,fall` 认成 `becomefall`）时以中文层为准并在分隔符后补空格。
8. **拆残粘连**：如果某个 token 既不在词表里、也从未在英文层独立出现过，就按词库尝试切成 2–4 段（`inviewof -> in view of`、`contendwith -> contend with`）。词库 = 4292 词条 + 屈折形 + 内置高频词 + 英文层自己的分词结果；要求有一段是介词/小词，或两段都 ≥5 字母，且后缀（ing/ed/ion…）不许当一段——否则会把 `contradiction` 拆成 `contradict ion`。
9. 行内拼接：任一侧是 CJK 就不加空格，纯拉丁之间一个空格，多空格压成一个。

### 为什么不用按 x 坐标直接对齐

英文层的字形宽度是按 token bbox 均摊出来的。纯英文行两层坐标完全一致，但混排行里中文被认成垃圾 ASCII、token bbox 被撑大，整行坐标就废了：p40 的 `【词组】be（或become,fall）preytosth.被.捕食`，中文层 `top=194.8`、英文层 `top=177.5`（字号 26 vs 52.4），英文层把 `be` 画在了 `【词组】` 的位置。按 x 硬套会把 `be` 配给 `【词组】`，而「行级对齐 + 字符级顺序查找」不受影响。

## 指标

| 指标 | 中文层 | 英文层 | 合并后 | 目标 |
|------|--------|--------|--------|------|
| 【词组】/【搭配】行粘连率（指定口径） | 624/1189 = 52.5% | — | **188/1189 = 15.8%** | < 5% |
| 同上，白名单含屈折形/书内词 | — | — | 47.6% → **7.0%** | < 5% |
| 其中「硬粘连」行（不像真词、也拆不开） | — | — | 79/1189 = **6.6%** | — |
| 汉字数 | 281119 | 0 | 281113 (100.00%) | ≈283k，±5% |
| 4292 词条原形命中率 | 98.3% | 98.8% | **98.7%** | ≈99% ±1% |
| 耗时（444 页） | — | — | 78s | 5–10 min |

口径说明：

- 粘连率：一行里出现「不在白名单且长度 ≥8」的拉丁 token 即判该行粘连。指定白名单只有 4292 词条 + 常见功能词，8 字母以上的**屈折真词**（`dividends`、`standards`、`privileges`、`startled`）不在其中，会被误判为粘连，所以指定口径偏保守；第二行把屈折形和书内词加进白名单后才是真实水平。
- 词条命中率：边界用「前后不是 ASCII 字母」而不是 `\b`——中文与英文紧邻时（`的steady`）`\b` 不认边界（CJK 也算 `\w`），会漏掉大量真实命中。

## 合并统计

- 拉丁 run 总数 **53496**
- 精确命中 **40811**（76.3%）
- 模糊兜底 **998**（1.9%）
- 退回中文层 **11687**（21.8%）——英文层同一行也是乱码时不可避免，如 p40 `【同义】frank,honest②plain, simple` 英文层作 `fraankh~onejstoplainbsim-pleI`；这类 run 后面还有拆粘连兜底
- `~` 占位符单独切 run 保留 **3704** 处
- 拆粘联动过 **486** 行

## 剩下没解决的

- 英文层也有认错成纯字母的时候（`Scentifc discoveries`、`inw viewa oyfs`），此时精确/模糊都命中不了，只能退回中文层原文，残粘连就留在那里。没有系统词典（机器上没有 words/hunspell）无法强行切。
- 两层都把 `~` 认丢的行（p300 `The mountain was too to climb.`）无法恢复占位符。
- 个别词条标题行两层都是乱码（p40 `relanceTrilarens` ← `reliance [rɪˈlaɪəns]`），交给下游 `parse_entries.py` 的模糊匹配。

## 人工抽查

### PDF 第 12 页（前 12 行）

```
③明显不同的人（或事物）（c）（to）：The northern weather
is quite a～to the south's.北方的天气与南方截然不同。
【词组】①by contrast相比之下
②in contrast with/to与...形成对比
【典型考题】Youractionyour principles.
AcomparedtoB. compared with
Cacontrasted with
D. in comparison to
【试题分析】答案C。译文：你的行为和原则有差别。本题
为近义词辨析题，也考查词语搭配。contrast常与with
sb./sth.连用，意为：（通过对比）显出差异，形成对照：
compare与lo连用，意为：比喻，比作，与with连用，意为：
```

### PDF 第 40 页（前 12 行）

```
【词组】be（或become, fall）prey to sth.被.捕食
【词性】?
【词义】（on/upon）捕食；掠夺；折磨，损害：The eagle ~ ed on
the snake.老鹰捕食蛇。
reliable[rr'laiobl] adj.
[词义]可靠的:It's not ~ to judge a man only by his clothes and
appearance。单凭衣着和容貌来判断一个人是不可靠的。
【反义】unreliableadj不可靠的，不能信赖的
relanceTrilarens
【词义】（on）依靠，依赖（u）：Long terms of ~ on sleeping pills
is dangerous。长期依赖安眠药是危险的。
religionEri lid3onI n.
```

### PDF 第 300 页（前 12 行）

```
sheerJie(r)l adi
【词义】①完全的，十足的He won his position by ~ ability.
他赢得地位全凭才干。
②陡峭的，垂直的：The mountain was too to climb.
这山太陡峭了，无法攀登。
sheet
[Jit] n.
【词义】①被单（c）：He tore the old into cleaning rags.
他把旧被单撕成抹布。
②（一）张，（一）片，薄片（c）：There isaof ice over
the lake.湖面有一层薄冰
shepherd［Jepad]
```

