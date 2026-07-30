# 红宝书考研词汇 — Anki 牌组

> 词源：**2026 版红宝书考研英语词汇**（必考词 26 单元 + 基础词 30 单元，共 4292 词）

## 文件说明

| 文件 | 内容 |
|------|------|
| `红宝书考研词汇_全套.apkg` | 56 个单元合并牌组，不含发音 |
| `红宝书考研词汇_带发音_全套.apkg` | 同上，含 AwesomeTTS on-the-fly 发音 |
| `必考词_Unit01.apkg` ~ `必考词_Unit26.apkg` | 按单元拆分（必考词），不含发音 |
| `基础词_Unit01.apkg` ~ `基础词_Unit30.apkg` | 按单元拆分（基础词），不含发音 |
| `红宝书考研词汇_全部.txt` | 纯文本词表（TSV 格式） |
| `all_entries_v2.json` | 结构化词条数据（含单词、音标、释义、助记） |
| `fetch_youdao.py` | 从有道词典补全缺失释义 |
| `gen_mnemonics.py` | 基于词根词缀生成中文助记 |
| `generate_anki_decks.py` | genanki 生成 apkg 牌组 |

## 卡片字段

每张卡片包含以下字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| Front / 单词 | 英文单词 | `remote` |
| Back / 背面 | 音标 + 词性 + 释义 + 助记 | `rɪˈmoʊt` → 遥远的；偏远的；疏远的 |

翻卡逻辑：正面显示单词 → 翻面显示释义和助记。

## 安装 Anki

### Linux（NixOS）

```bash
sudo nixos-rebuild switch --flake /home/cloudygirl/nixos
```

其他发行版：`sudo pacman -S anki` / `sudo apt install anki` / Flatpak: `flatpak install flathub net.ankiweb.Anki`

### Windows

1. 访问 [apps.ankiweb.net](https://apps.ankiweb.net) 下载安装包
2. 安装后打开 Anki，语言选中文
3. 双击 `.apkg` 文件即可自动导入，或在菜单 **文件 → 导入**

> Win 10/11 均可使用，Anki 自动适配系统深色模式。发音功能同样通过 AwesomeTTS 插件实现（见插件章节）。

### 手机 / 平板

| 平台 | 应用 | 费用 | 下载 |
|------|------|------|------|
| Android | **AnkiDroid** | 免费 | [Google Play](https://play.google.com/store/apps/details?id=com.ichi2.anki) / [F-Droid](https://f-droid.org/packages/com.ichi2.anki/) |
| iOS / iPad | **AnkiMobile** | 付费（¥163） | [App Store](https://apps.apple.com/app/ankimobile-flashcards/id373493387) |
| 任意浏览器 | **AnkiWeb** | 免费 | [ankiweb.net](https://ankiweb.net) |

> iOS 付费是官方唯一收入来源，支持开发。嫌贵可用浏览器版 AnkiWeb，功能基本够用。

#### 手机导入步骤

1. 将 `.apkg` 文件传到手机（微信发送、数据线、或从 GitHub 下载）
2. 打开 AnkiDroid / AnkiMobile
3. 点击文件 → 系统会弹出导入对话框
4. 选择 `.apkg` 文件完成导入

或者直接用手机浏览器访问本仓库，下载 `.apkg` 文件后打开。

## 多设备同步

所有设备共享学习进度，推荐注册 AnkiWeb 免费账号：

1. 访问 [ankiweb.net](https://ankiweb.net) 注册账号
2. 在桌面端 Anki 点击 **同步** 按钮（右上角），用同账号登录
3. 在手机端同样登录
4. **每次学习前后各点一次同步**，避免冲突

> 发音文件体积较大，桌面端导入 `带发音_全套.apkg` 后首次同步可能需要 5~10 分钟。手机端同步时会自动下载媒体文件。

## 导入牌组

1. 打开 Anki
2. **文件 → 导入**（手机端：点击牌组列表底部的 `+` 或直接打开 `.apkg` 文件）
3. 选择 `.apkg` 文件
4. 推荐先导 `红宝书考研词汇_带发音_全套.apkg`（一个文件包含全部 4292 词）
5. 如需按单元学习，导入对应的 `Unit` 文件

导入后在主界面可看到「红宝书」牌组。

## 推荐插件

插件仅桌面端（Linux / Windows / macOS）支持，手机端不兼容。

### AwesomeTTS — 单词发音（必装）

**安装**：工具 → 附加组件 → 获取插件 → 输入代码 `1436550454`

**功能**：翻卡片时自动朗读单词发音（有道词典 TTS，`en-US` 美式发音，国内直连）

**桌面端配置**：NixOS 上已预配好（有道 TTS + `{{tts en_US:Front}}` 卡片模板）。Windows 首次安装后，进入工具 → AwesomeTTS → Options → 添加有道词典预设（Voice 选 `en-US`），然后重启 Anki。

> 手机端不支持 AwesomeTTS 插件。如需手机端发音，使用 `红宝书考研词汇_带发音_全套.apkg` 导入后通过桌面端同步过去（发音文件会随同步传输）。

### Review Heatmap — 学习热力图

**安装**：工具 → 附加组件 → 获取插件 → 输入代码 `1771074083`

**功能**：在主界面显示每日学习量热力图（类似 GitHub 贡献图），直观追踪学习进度。

> 手机端替代：AnkiDroid 自带 **统计** 页面，可查看学习图表。

## 学习建议

- **每日新卡量**：20～30 张，按 56 单元约 3～4 个月完成一轮
- **复习优先**：Anki 自动按间隔重复算法安排，务必完成每日复习
- **自定义**：可在浏览器中按 `Unit` 字段筛选特定单元复习

## 数据来源与生成

原始数据来自 2026 版红宝书词条，处理流程：

```
all_entries_v2.json (结构化数据)
    │  fetch_youdao.py → 从有道词典补全缺失释义 (821 条)
    │  gen_mnemonics.py → 基于词根词缀生成中文助记 (覆盖 72%)
    │
    ▼ generate_anki_decks.py (genanki)
    │
    ├── 红宝书考研词汇_全套.apkg          (简化版，无 TTS)
    ├── 红宝书考研词汇_带发音_全套.apkg    (模板嵌入 {{tts en_US:Front}})
    ├── 必考词_Unit01~26.apkg
    └── 基础词_Unit01~30.apkg
```

### 维护命令

```bash
# 从有道词典补全缺失的单词释义
uv run --with genanki python fetch_youdao.py

# 基于词根词缀生成助记
python3 gen_mnemonics.py

# 重新生成所有 apkg 牌组
uv run --with genanki python generate_anki_decks.py
```

## 许可证

词条版权归红宝书原出版社所有。本项目仅供个人考研学习使用。
