# 红宝书考研词汇 — Anki 牌组

> 词源：**2026 版红宝书考研英语词汇**（必考词 26 单元 + 基础词 30 单元，共 4292 词）

## 牌组结构

导入后 Anki 牌组列表呈现层次结构：
R
```
红宝书考研词汇
├── 必考词
│   ├── Unit 01
│   ├── Unit 02
│   └── ... (共 26 单元)
└── 基础词
    ├── Unit 01
    ├── Unit 02
    └── ... (共 30 单元)
```

每个单元 70~80 词，总牌组顶部显示全部 4292 词总量。

## 文件说明

| 文件 | 内容 |
|------|------|
| `红宝书考研词汇_带发音_全套.apkg` | **推荐导入此项** — 含 56 个子牌组、完整释义、助记和 on-the-fly 发音 |
| `红宝书考研词汇_全套.apkg` | 同上但不含发音模板，适合手机端（手机不支持 AwesomeTTS 插件） |
| `必考词_Unit01.apkg` ~ `必考词_Unit26.apkg` | 独立单元导入（简化版，无发音） |
| `基础词_Unit01.apkg` ~ `基础词_Unit30.apkg` | 独立单元导入（简化版，无发音） |
| `all_entries_v2.json` | 结构化词条数据（含单词、音标、释义、助记） |
| `fetch_youdao.py` | 从有道词典补全缺失释义 |
| `gen_mnemonics.py` | 基于词根词缀生成中文助记（覆盖 72%） |
| `generate_anki_decks.py` | genanki 生成全部 apkg 牌组 |
| `adhd_plan.py` | 把牌组选项改成 ADHD 友好档（新词 30/复习 280 等），可重复运行 |
| `背诵计划.md` | ADHD 版背诵计划：配额、三档、断更恢复、周日保养 |

## 卡片字段

每张卡片正面显示单词，翻面后展示：

| 区域 | 内容 | 示例 |
|------|------|------|
| 音标 | `[]` 包裹 | `[rɪˈmoʊt]` |
| 释义 | 完整中文释义（含词性） | `（时间，距离）遥远的；偏僻的；…` |
| 助记 | 【助记】前缀 | `re（再）+ mote（尘埃）→ 疏远的` |

## 安装 Anki

### Linux（NixOS）

```bash
sudo nixos-rebuild switch --flake /home/cloudygirl/nixos
```

### Windows

[apps.ankiweb.net](https://apps.ankiweb.net) 下载安装 → 双击 `.apkg` 导入。

### 手机 / 平板

| 平台 | 应用 | 费用 | 下载 |
|------|------|------|------|
| Android | **AnkiDroid** | 免费 | [GitHub 官方下载](https://github.com/ankidroid/Anki-Android/releases) |
| iOS / iPad | **AnkiMobile** | ¥163 | [App Store](https://apps.apple.com/cn/app/ankimobile-flashcards/id373493387) |

> AnkiDroid 开源免费，国内可直接下载 apk 安装；iOS 端 AnkiMobile 为官方唯一 App（付费），
> 使用苹果设备的，可免费使用 [AnkiWeb 网页版](https://ankiweb.net) 代替苹果商店付费下载使用s。

## 导入牌组

1. 打开 Anki
2. **文件 → 导入** → 选 `红宝书考研词汇_带发音_全套.apkg`
3. 导入后牌组列表展开可看到必考词 / 基础词 → 各单元

## 多设备同步（AnkiWeb）

注册 [ankiweb.net](https://ankiweb.net) 免费账号，所有设备登录同账号。

> ankiweb无需魔法代理即可进行访问同步
> 也可以自建同步服务器，请自行查看[官方文档](https://open-spaced-repetition.github.io/anki-manual-zh-CN/sync-server.html)
> 首次同步牌组体积约 2MB，后续仅同步学习进度，几秒完成。

## 发音配置

### 桌面端（AwesomeTTS 插件）

安装附加组件代码 `1436550454`。牌组模板已内置 `{{tts en_US:Front}}` 标签，
导入后 AwesomeTTS 自动使用**有道词典 TTS**（美式发音，国内直连无需代理）。

### 手机端

AwesomeTTS 不支持手机端。替代方案：
- 桌面端导入后同步到手机 → 发音随 AnkiWeb 同步传输
- 或手机端用 AnkiDroid 自带的 TTS 引擎

## 外观插件

| 插件 | 代码 | 说明 |
|------|------|------|
| Review Heatmap | `1771074083` | 主界面显示学习热力图 |

## 学习建议（ADHD 版，已生效）

牌组选项预设已改为「ADHD · 每日」：**新词 30/天 + 复习 280/天**（点总牌组时的总量），
约 30 分钟做完。完整计划见 [`背诵计划.md`](背诵计划.md)。

必考词 26 个单元已全部学完，剩余 1603 个新词全在基础词（30 个单元）。
**30/天 ≈ 54 天学完**，按 12 月中下旬考试算刚好够、还剩一周缓冲。

四条硬规则：

- **点总牌组**（`红宝书考研词汇`）学就行：Anki 26 里总量由「你点开的那个牌组」的上限
  控制，子牌组的上限只限制各自最多贡献多少张，所以总量是 30+280，不会叠加；
  同时所有单元当天到期的复习都会带出来，不会漏掉上周的单元。
- **一天只点一个牌组**：配额是按点开的牌组算的，再点第二个（`基础词` 或某个单元）
  就等于再领一份。已顺手开启「Limits Start From Top」兜底。
- **到上限就关**，Anki 自己会停；做不完的由 FSRS 重排，逾期不会雪崩。
- **按电量选档**：`python3 adhd_plan.py --tier low|std|sprint`（低电量 10+100 / 标准 30+280 / 冲刺 50+400）。

改造前实测每天进 100+ 新词、日均 ~600 次复习、约一半按「忘记」——配额问题，不是自制力问题。
新词本身不贵（30 个≈10 分钟），真正占时间的是复习。Anki 手册的经验值是每 20 个新词
对应约 200 张复习/天，30 个新词对应约 300 张，所以上限设 280：够用，又能在某天 due 爆掉时截住。

## 数据详情

| 指标 | 数值 |
|------|------|
| 总词数 | 4292 |
| 释义完整 | 100%（含从有道词典补全的 821 条） |
| 助记覆盖 | 72%（原书数据 + 词根词缀生成） |
| 发音 | 有道 TTS 美式发音 |
| 拼写校验 | 全量 hunspell 检查，无误 |

## 维护与重新生成

```bash
# 从有道词典补全缺失的单词释义
python3 fetch_youdao.py

# 基于词根词缀生成助记
python3 gen_mnemonics.py

# 重新生成所有 apkg 牌组
uv run --with genanki python generate_anki_decks.py

# 将你在anki对牌组的修改同步到apkg本地包
python3 sync_from_anki.py --yes

# 调整背诵计划档位（会先备份 collection 到 backups/）
python3 adhd_plan.py --dry-run              # 先在副本上演练
python3 adhd_plan.py --tier std             # 应用标准档（新词 30 / 复习 280）
python3 adhd_plan.py --tier low             # 低电量档（新词 10 / 复习 100）
python3 adhd_plan.py --tier sprint          # 冲刺档（新词 50 / 复习 400）

```

## 许可证

词条版权归红宝书原出版社所有。本项目仅供个人考研学习使用。
