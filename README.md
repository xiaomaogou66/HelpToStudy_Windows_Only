# AI 学习工作流

一套把「厚教材 → 能真正学会」的固定流程，封装成可一键复现的 Obsidian 库：
拆书 → 五级水平拆解 → 二八定律学习计划 → 十问测试 → 一页速查表。

这个仓库是**模板 + 一键安装器**：任何一台 Windows 电脑从 Release 下载
一个引导器（或克隆后运行 `install.ps1`），就会生成一个功能完全一致的
「AI 学习工作流」Obsidian 库，无需手动配路径、装插件、写启动器。

> 个人学习笔记（`03-学习主题/*`、`04-教材分块/*`、API 密钥、会话记录）
> 默认不会进入本仓库，也不会被安装脚本带入新库。

---
## 运行前提：两个 API

本项目是 AI 驱动的工作流，使用前需要准备以下两个 API：

| 需要 | 用途 | 怎么获得 |
| --- | --- | --- |
| AI 供应商的 API | 拆书、五级拆解、出学案、十问测试、生成速查表等全部 AI 功能 | 任选一种：① 本机安装并登录 Codex CLI 或 Claude Code；② 在 AI 供应商（如 Anthropic、OpenAI 等）后台申请 API Key，安装后粘贴到 cc-switch / Claudian 设置中 |
| MinerU 的 API Token | 扫描版、数学公式类教材的云端 OCR 解析（公式转 LaTeX） | 到 [MinerU 官网](https://mineru.net) 注册账号，免费领取 Token；安装后双击 `_工具\设置MinerU令牌.bat` 粘贴即可 

## 一键安装（Windows 10 / 11）

### 推荐方式：Release 单文件引导器

不用克隆仓库、不用手动解压。到本仓库的 **Releases** 页面下载最新的
`HelpToStudy-QuickInstall.bat`，双击运行即可。它会自动完成：

1. 从 Release 下载库压缩包并解压到临时目录
2. 检测/安装环境：**Obsidian、Python、Node.js、Git for Windows、
   Claude Code、cc-switch**（已装的最新版直接跳过；缺失的自动安装，
   版本来源优先级 winget > 官方接口 > 内置清单）
3. 安装「AI 学习工作流」Obsidian 库（默认
   `%USERPROFILE%\ObsidianVaults\AI学习工作流`；会弹出文件夹选择框，
   可自选位置，点「取消」则询问是否用默认位置）
4. 装完自动用 Obsidian 打开库

> 浏览器若提示「不常见下载」，点击**保留 / 仍要运行**即可（脚本未签名，
> 内容全部开源，可在仓库里直接审阅）。
> 不需要自动装环境时，可用 `-SkipEnv` 只装库，参数见下表。

#### 常用参数

在 cmd / PowerShell 中追加参数运行：

```powershell
.\HelpToStudy-QuickInstall.bat -VaultPath "D:\我的资料\AI学习工作流"
.\HelpToStudy-QuickInstall.bat -SkipEnv
.\HelpToStudy-QuickInstall.bat -SkipMineru -NoOpenObsidian
```

| 参数 | 作用 |
| --- | --- |
| `-SkipEnv` | 跳过环境检测/安装，只装库 |
| `-SkipClaude` | 跳过 Claude Code 安装 |
| `-VaultPath "路径"` | 指定库安装位置 |
| `-NoDialog` | 不弹文件夹选择框，用默认位置 |
| `-SkipPython` | 跳过 Python 虚拟环境与拆书依赖 |
| `-SkipMineru` | 不装 MinerU 云端 OCR 工具 |
| `-NoOpenObsidian` | 装完不自动打开 Obsidian |
| `-Force` | 目标目录已存在时不询问，直接继续 |

### 备用方式：手动 ZIP 或克隆

如果浏览器拦截下载、想离线安装，或想先看看内容再装：

1. 到 **Releases** 下载 `HelpToStudy-Vault-<版本>.zip`（或克隆本仓库）
2. 解压后先双击「**环境配置.bat**」，检测/安装环境
   （`环境配置.bat -CheckOnly` 只查不装；`环境配置.bat -SkipClaude`
   跳过 Claude Code；装完会自动打开 cc-switch 供粘贴 API Key）
3. 再双击「**安装.bat**」按提示安装（效果等同手动运行 `.\install.ps1`）

> 「安装.bat」会自动以「绕过执行策略」的方式启动 install.ps1，
> 只对本次生效、不修改系统设置，因此下载/解压的仓库也能直接双击安装。

### 装完之后的设置

1. 首次打开若提示「信任社区插件」，选**信任**（插件文件已随库装好，
   包含 Copilot、Dataview、QuickAdd、Templater、Claudian、Excalidraw CN）。
2. 打开右侧边栏的 **Claudian**，在设置中选择后端（本机 Codex 或 Claude Code）。
3. 大部分中英意文书都可以：双击 `_工具\设置MinerU令牌.bat`，
   粘贴 [MinerU](https://mineru.net) 的免费 Token。
4. 打开 `00-使用指南\📖 使用说明.md`，开始你的第一个学习主题。

---

## 这个库能做什么

| 命令 / 工具 | 用途 |
| --- | --- |
| `_工具\拆书.bat` | 拆书唯一入口：PDF → MinerU 云端 OCR（公式转 LaTeX）→ 按章拆分 |
| `_工具\设置MinerU令牌.bat` | 保存 MinerU Token（免费注册 mineru.net；Token 有有效期） |
| `/拆书` | 在 Claudian 里触发拆书（**先做令牌体检**，过期即停并提示续期） |
| `/新主题-拆解与计划` | 五级水平拆解 + 二八定律 10 次学习计划，一键写入笔记 |
| `/学案` | 每章生成学案 + Session 记录 |
| `/测试我` | 十问考官测试，记录分数和薄弱点 |
| `/速查表` | 生成一页速查表（开课前 5 分钟复习） |
| `/更新进度` | 自动更新主题主页的进度/级别/薄弱点 |
| `/周决策` | 周日跑：按上周完成率与各科进度生成下周决策（含日历任务行） |
| `/课表` | 每学期换课表：体检 → 备份旧表 → 差量同步 |
| `05-日程安排\_脚本\同步日程.bat` | 日程同步：`ics`（本机文件）与 `gcal`（Google 日历）两个地位同等的后端 |
| `05-日程安排\_脚本\自检.bat` | 烟测：配置/打卡/日记/两个后端/令牌 一次全检（不联网、不改数据） |

核心原则：**笔记就是记忆**。进度永远写在笔记里（frontmatter + 固定标记区），
AI 只负责读写，不把整个库塞进对话，因此省钱、可长期使用。

### 拆书引擎能力（全走 MinerU，不做本地提取）

- **仅支持 PDF**：MinerU 云端 OCR（扫描版）+ 公式转 LaTeX，自动按章拆分；
  英文书默认 `--mineru-language en`，中文书加 `--mineru-language ch`。
  本地文字层提取（pdfplumber / Word / EPUB）**已下线**：EPUB / Word 请先转成 PDF
- **大扫描件也传得上去**：上传按「≤200 页 且 ≤25 MB」分块（`mineru-open-api` 的
  上传超时窗口在 1–2 MB/s 的上行下只吃得下几十 MB）；每页平均体积一超上限，就先
  分块上传，单份上传超时还会自动对半切小重传；Token / 额度类错误立即判定，不再无谓重试。
  可调：`--mineru-chunk-mb 8`、`--mineru-dpi 150`、`--mineru-dpi 0`（不压缩直传）
  例：`_工具\拆书.bat "D:\书\某教材.pdf" --mineru-chunk-mb 8`
- **章节识别**支持中/英/意/西/法常见标题（含意大利语序数词课名、目录页码格式）；
  章标题被 OCR 整批打掉时（如某外语教材每课用了装饰字体的 UNIDAD 标题，16 课只认出 7 个），
  默认自动改走「每章固定收尾小节」定位：从正文里挖出每章都出现、只出现一次且间隔均匀的小节
  （如「作业 (Trabajos de casa)」）当章界锚点，实测 16 课一次切准；只有比通用识别
  切出更多章时才采用，正常书不受影响。可自己指定：`--chapter-end-pattern '习题\s*\(Ejercicios'`；
  关掉：`--chapter-end-pattern off`
- 正文标题只识别出编号时（`# 4 货币系统：…`）也能对上目录名（去掉「第N章 / N / N.」前缀再比）
- 识别不到章节时全书保存为一个文件并提示校准，绝不乱切；重切不耗额度（把
  `00-MinerU解析全文.md` 拖到 `_工具\拆书.bat` 即可），还可用 `--opener-pattern` 补充定位，
  `--mineru-dry-run` 可先看分块计划不耗额度
- 生成的章节笔记里图片统一使用 Obsidian 原生嵌入 `![[图片名]]`；
  前言/目录、书后总词汇表各自单独成块，分块字数合计 = 全文字数，不漏不重
- **旧分块会备份**：覆盖前把旧文件复制到库外 `%USERPROFILE%\obsidian_backups\拆书\<书名>\`
  （不在库里生成 `_备份\`，避免 Obsidian 关系图谱出现重复节点）

---

## 目录结构

```
AI学习工作流/
├── 00-使用指南/        首页、使用说明
├── 01-提示词库/        Step1-5 提示词原文（含合并版）
├── 02-模板/            新主题、Session 记录、速查表模板
├── 03-学习主题/        每个主题一个文件夹（主页/计划/测试/速查表）
├── 04-教材分块/        拆书结果（00-教材信息、00-目录、01-全书大纲、章节分块）
├── 05-日程安排/        日程安排层（第六层）
│   ├── 00-配置/         ← 人只改这里：规划配置.json（目标/里程碑/后端）· 底线规则.json · 同步配置.json · 多端同步.md
│   ├── 06-日志/         一周一个 <周号>\：<周号>.md（周决策）+ 打卡.md + 7 篇日记
│   ├── _脚本/           ← 引擎：同步日程.bat（ics/gcal 双后端）· 导出ics.py · sync_gcal.py · 打卡.bat · 周文件夹.bat · today.bat · 自检.bat
│   └── _资源/           课表示例.ics（换成你自己的课表即可）
├── _工具/              拆书脚本 + 相对路径启动器 + requirements.txt + .venv（可选）
├── .pi/skills/         同 8 条命令的 skill 版（供 pi 等 agent 使用）
├── copilot/            Copilot 插件自定义提示词
├── .claude/commands/   Claudian 斜杠命令（输入 / 触发）
└── .obsidian/          插件与配置（随库装好）
```


## 常见问题

**Q：引导器下载失败 / 离线环境怎么装？**
A：直接到 Releases 下载 `HelpToStudy-Vault-<版本>.zip`，解压后手动运行
「环境配置.bat」→「安装.bat」，效果与一键安装相同。

**Q：下载 .bat 时浏览器提示「不常见下载」？**
A：点击**保留 / 仍要运行**即可。引导器只做下载、解压和调用仓库里的开源脚本，
不修改系统设置，不放任何可疑内容。

**Q：装过旧版本，怎么升级？**
A：再次运行一键引导器（或解压新版 ZIP 后运行「安装.bat」）。目标目录已存在时
会询问是否继续，个人笔记保留，只覆盖/补充工作流文件。

**Q：装完打开 Obsidian 没有 Claudian 图标？**
A：确认 `.obsidian/community-plugins.json` 已复制且首次打开时选择了「信任」。
如果插件未加载，可在设置 → 第三方插件中手动启用。

**Q：Claudian 提示找不到 Codex / Claude？**
A：需要先安装 Codex CLI 或 Claude Code，并在 Claudian 设置里选择后端。
如果用的是 Codex 桌面版，Claudian 会自动发现本机的 codex 命令。

**Q：拆书报「找不到 MinerU 命令行工具」？**
A：安装时已自动执行 `pip install mineru-open-api`（可用 `-SkipMineru` 跳过）。
手动补救：运行 `_工具\.venv\Scripts\pip.exe install mineru-open-api`。

**Q：`install.ps1` 双击没反应 / 提示"禁止运行脚本"？**
A：直接双击仓库根目录的「安装.bat」即可，它已内置绕过执行策略的启动方式；
不需要修改系统设置。手动运行时用
`powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1`。

**Q：安装时可以自己选库的位置吗？**
A：可以。双击「安装.bat」后先弹出「选择文件夹」对话框，选中哪个文件夹，
库就装到哪；点「取消」可用默认位置或退出。想跳过对话框直接用默认位置，
运行 `.\install.ps1 -NoDialog`；想指定固定位置，运行
`.\install.ps1 -VaultPath "D:\我的资料\AI学习工作流"`。

**Q：拆书报 Token 过期 / 「user token expired」？**
A：MinerU 的 Token 有有效期（实测 ≥27 天仍有效）。重跑一次
`_工具\设置MinerU令牌.bat` 即可续期（覆盖写入，签发时刻会自动刷新）。
在 Claudian 里跑 `/拆书` 时，第 0 步就会先体检并告诉你「已签发多少天」。

**Q：装完想确认各部件都正常？**
A：双击 `05-日程安排\_脚本\自检.bat`（或终端运行它）：配置、打卡页、周文件夹、
today、ics / Google 两个后端、ics 结构、命令一致性、MinerU 令牌，一次全查，
不联网、不改数据。

**Q：以前能用 epub / Word 直接拆，现在不行了？**
A：本地文字层提取已下线，统一走 MinerU（识别质量、公式转 LaTeX、章节切分都更稳）。
请先把 EPUB / Word 转成 PDF 再拆。

**Q：macOS / Linux 能用吗？**
A：当前一键安装器面向 Windows（.bat 启动器 + PowerShell）。
拆书脚本 `split_textbook.py` 本身跨平台，可在任意系统手动运行。

## 从零开始维护

改了什么想同步回仓库？直接在仓库里改，然后：

```powershell
git add -A
git commit -m "更新说明"
git push
```

想在新电脑上再装一次：重复上面的「一键安装」步骤即可。

### 发布新版本

打 tag 并推送，GitHub Actions 会自动构建发布包并生成 Release：

```powershell
git tag v1.0.0
git push origin v1.0.0
```

也可以在本地生成资产后手动发布（Actions 不可用时的兜底）：

```powershell
.\scripts\build-release.ps1 -Tag v1.0.0 -Repo xiaomaogou66/HelpToStudy -OutDir .\dist
```

会生成 `HelpToStudy-Vault-<版本>.zip`、`HelpToStudy-QuickInstall.bat` 和
`release-notes.md`；手动发布时把前两个文件作为 Release 资产上传即可。

### 库可以随便拷贝、移动

`_工具` 里的拆书启动器全部使用**相对路径**（自动定位库目录、虚拟环境和
Token 文件），不依赖任何本机绝对路径。因此整个库文件夹可以拷贝到 U 盘、
换电脑、移动位置，双击 `_工具\拆书.bat` 依然能用；缺 Python 或依赖时
启动器会给出明确提示，不会像以前一样报"找不到路径"。
