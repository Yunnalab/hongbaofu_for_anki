# 红宝书考研词汇 — Anki 牌组

> 词源：**2026 版红宝书考研英语词汇**（必考词 26 单元 + 基础词 30 单元，共 4292 词）

## 牌组结构

导入后 Anki 牌组列表呈现层次结构：

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
| Android | **AnkiDroid** | 免费 | [Google Play](https://play.google.com/store/apps/details?id=com.ichi2.anki) |
| iOS / iPad | **AnkiMobile** | ¥163 | [App Store](https://apps.apple.com/app/ankimobile-flashcards/id373493387) |

## 导入牌组

1. 打开 Anki
2. **文件 → 导入** → 选 `红宝书考研词汇_带发音_全套.apkg`
3. 导入后牌组列表展开可看到必考词 / 基础词 → 各单元

## 多设备同步（AnkiWeb）

注册 [ankiweb.net](https://ankiweb.net) 免费账号，所有设备登录同账号。

> **国内用户注意**：AnkiWeb 需代理访问。NixOS 上已在 Anki 内配好代理
> `127.0.0.1:10808`。Windows 在 Anki → 首选项 → 网络 → 手动代理中输入同样地址。
>
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

## 学习建议

- **每日新卡**：20~30 张，按 56 单元约 3~4 个月完成一轮
- **复习优先**：Anki 自动按间隔重复算法安排，务必完成每日复习
- **单元学习**：在牌组列表展开子牌组，按单元逐日推进

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
```

## 许可证

词条版权归红宝书原出版社所有。本项目仅供个人考研学习使用。
