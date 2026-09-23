---
type: guide
---

# 🔧 首次配置：周决策 → Google 日历（零延迟推送）

> **为什么不用 iCal 插件的 Gist 订阅**：Google 抓取订阅源要 8~24 小时。本脚本直接调用
> Google Calendar API 写入，**秒级**，并且在专用日历里「全量重建」——改时间、删任务都不会有重复事件。

## 日常用法

| 命令 | 作用 |
|---|---|
| `./同步日历.bat --dry-run` | **只看**会推送什么，不联网、不动日历 |
| `./同步日历.bat` | 真正同步（周日写完周决策后跑这一条） |
| `./同步日历.bat --check` | 检查凭据和日历是否可用 |
| `./同步日历.bat --completed drop` | 已完成的任务从日历移除（默认加 ✅ 前缀保留） |

也可以直接双击同目录下的 **`同步日历.bat`**。

### 🌐 代理：本脚本固定走本机 `7897`

**只有这个脚本走代理**（`127.0.0.1:7897`，Clash Verge），所以不用提前 `export http_proxy`，
**双击 `同步日历.bat` 也能用**：

| 想干嘛 | 怎么写 |
|---|---|
| 换端口 / 换机器 | `SYNC_PROXY=http://127.0.0.1:7890 ./同步日历.bat` |
| 临时直连 | `SYNC_PROXY=none ./同步日历.bat` |

- 环境变量只在「本脚本 + 它启动的 python」里生效：**不动系统代理、不动你的 shell、不影响别的脚本**
- 不写就是默认 `7897`；`--dry-run` 不联网（代理设了也无所谓）

---

# 授权方式二选一

| | **方案 A · 服务账号**（推荐） | 方案 B · OAuth 桌面客户端 |
|---|---|---|
| 同意屏幕 / 发布 / 验证 | **完全不需要** | 必须"发布为正式"，还要填首页+隐私政策+授权域名 |
| 令牌过期 | **永不过期** | 测试态 7 天过期；正式态不过期 |
| 权限范围 | 只能动你共享给它的那一个日历 | 可创建日历 |
| 配置耗时 | ~10 分钟 | ~15 分钟，且可能卡在域名要求 |
| 密钥文件 | `service-account.json` | `credentials.json` + `token.json` |

> 脚本会自动判断：**优先用 `service-account.json`**，没有才走 `credentials.json`。
> 想指定用哪个，在 `同步配置.json` 里写 `"credentials_file": "文件名"`。

---

# 方案 A · 服务账号（推荐）

### 1. 启用 API

<https://console.cloud.google.com/> → 左侧「**API 和服务**」→「**库**」→ 搜 `Google Calendar API` → **启用**

### 2. 建服务账号

「**IAM 和管理**」→「**服务账号**」→ **创建服务账号**
- 名称：`obsidian-sync` → 创建并继续 → 角色可跳过（**不用给任何角色**）→ 完成
- 记住它的邮箱：形如 `obsidian-sync@<项目ID>.iam.gserviceaccount.com`

### 3. 下载密钥

点进这个服务账号 →「**密钥**」标签 → **添加密钥** → **创建新密钥** → 选 **JSON** → 创建
- 下载到的文件**改名 `service-account.json`**，放到 `05-日程安排/_脚本/service-account.json`

### 4. 建一个专用日历

打开 <https://calendar.google.com> → 左侧「其他日历」旁的 **+** → **创建新日历**
- 名称：`日程安排 (Obsidian)` → 创建

### 5. 把日历共享给服务账号

左侧点开这个新日历 → **设置和共享** → 「**与特定用户或群组共享**」→ **添加用户**
- 填第 2 步的**服务账号邮箱**
- 权限选「**更改活动**」→ 发送

### 6. 把日历 ID 填进配置

同一页往下拉 → 复制「**日历 ID**」（形如 `xxxxx@group.calendar.google.com`）
填进 `05-日程安排/00-配置/同步配置.json` 的 `calendar_id`：

```json
"calendar_id": "xxxxx@group.calendar.google.com",
```

### 7. 验证

```bash
./同步日历.bat --check      # → ✅ 授权有效｜日历可用
./同步日历.bat              # → 写入事件
```

---

# 方案 B · OAuth 桌面客户端（如果你已经走到这一步）

### 1. 启用 API
同上：「API 和服务」→「库」→ 启用 **Google Calendar API**

### 2. Google Auth Platform → 品牌设置（Branding）

| 字段 | 填什么 |
|---|---|
| App name | `obsidian-sync` |
| User support email | 你的 Gmail |
| **Application home page** | **必填**，任意 https 页面（如你的 GitHub 主页） |
| **Application privacy policy link** | **必填**，一页说明"个人自用、仅访问本人日历数据、不收集不共享" |
| **Authorized domains** | **必填**，上面两个链接的域名（如 `github.com`） |
| **Developer contact information** | **必填**，你的 Gmail |
| App logo | ⚠️ **不要上传**，传了会被要求走 Google 验证 |

> 卡点通常在这里：授权域名可能要求你**证明域名所有权**（Search Console）。
> 所以**建议直接用方案 A**，跳过整个同意屏幕。

### 3. 受众群体（Audience）
- 「测试用户」→ 添加你自己的 Gmail
- 「发布应用」→ 发布状态改成 **正式**（停在测试态，令牌 7 天过期）

### 4. 客户端（Clients）
- 创建客户端 → 应用类型 **桌面应用** → 创建 → 下载 JSON
- 改名 `credentials.json`，放到 `05-日程安排/_脚本/credentials.json`

### 5. 首次授权
```bash
./同步日历.bat --check
```
浏览器里若出现「Google 未验证此应用」→ **高级 → 继续前往**。

---

# 同步配置.json 可调项

```json
{
  "calendar": "日程安排 (Obsidian)",
  "calendar_id": "",
  "credentials_file": "",
  "timezone": "Asia/Shanghai",
  "scope": "app",
  "reminder_minutes": 10,
  "completed": "prefix",
  "window_past_days": 14,
  "window_future_days": 180,
  "task_globs": ["05-日程安排/06-日志/*/????-W??.md"]
}
```

| 字段 | 说明 |
|---|---|
| `calendar_id` | **服务账号模式必填**；OAuth 模式留空即自动查找/创建 |
| `credentials_file` | 留空 = 自动找 `service-account.json` → `credentials.json` |
| `scope` | 仅 OAuth 模式用：`app` 最小权限（推荐）／`full` 完整日历权限 |
| `reminder_minutes` | 定时事件的提前提醒分钟数 |
| `completed` | `prefix` 加 ✅ 保留（推荐）／`drop` 移除／`keep` 原样 |
| `task_globs` | 扫哪些文件 |

---

# 任务写法（脚本只认这种）

```markdown
- [ ] 外语精读 4h 📅 2026-09-17 13:30 - 17:30
- [ ] 导入日历 📅 2026-09-13
```

- 必须有 `📅 2026-09-13` 形式的日期，否则跳过
- 时间区间写在同一行 → **定时事件**；不写时间 → **全天事件**
- `- [x]` 已完成 → 加 ✅ 前缀保留（或按配置移除）
- 不认 `🔁`（不做循环）

---

# 注意事项

1. **专用日历是全自动的**：每次同步会清空「过去 14 天 ~ 未来 180 天」窗口内的全部事件再重建
   → **不要往这个日历手动加事件**，会被下次同步删掉
   → 脚本会**硬拒绝**指向主日历（`primary` / `@gmail.com`），但你自己也别忘了别填错
2. **别和 Gist 订阅同时开**：否则 Google 里会出现两个日历各一套事件（重复）。
   要走零延迟就把 iCal 插件的「Save calendar to GitHub Gist」关掉
3. `service-account.json` / `credentials.json` / `token.json` 都含账号权限 → **别外传、别放公开位置**
4. 专用日历自身的时区（日历设置 → 时区）建议设成 `(GMT+08:00) 中国标准时间`。
   脚本写入的每条事件都带 `timeZone: Asia/Shanghai`，所以**不管日历时区是什么，事件时间都是对的**；
   日历时区只影响你手动新建的事件、以及全天事件的显示（Google 按你账号的时区显示）。
5. 依赖已固定在同目录 `requirements.txt`：环境重建后要按它重装，否则会踩代理超时（详见常见问题）

---

# 常见问题

| 现象 | 解决 |
|---|---|
| **`❌ 直连和所有代理候选都连不上 Google API`** ／ 终端 / 双击 `.bat` 时超时 | 代理客户端没开。脚本固定走 `127.0.0.1:7897` → 打开 Clash Verge，确认它在听（`ss -ltn \| grep 7897`）；端口不是 7897 就 `SYNC_PROXY=http://127.0.0.1:7900 ./同步日历.bat` |
| **`SSLEOFError` / `TimeoutError` / 打印「⏳ 网络抖动，等 Ns 重试」** | 本机代理（7897）节点抖动，**脚本会自动退避重试最多 6 次**。若最终仍失败：换节点/重启代理再跑。实测同一分钟内 3 次里约 1 次通，重试基本都能过 |
| **请求卡 20 秒后 `TimeoutError`** | 走了 http 代理但 venv 里没 PySocks（httplib2 会静默直连）→ `../_工具\.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| `To publish your app, you must complete your configuration on the Branding page` | 补 Branding 的首页/隐私政策/授权域名/开发者邮箱；或**改用服务账号** |
| `403` / `insufficient permission` | 没启用 Calendar API；或（服务账号）没把日历共享给它 |
| `invalid_grant` / 刷新失败 | OAuth 应用还在测试态（令牌 7 天过期）→ 发布为正式，或改用服务账号 |
| `找不到 calendar_id` | 服务账号模式必填，见方案 A 第 6 步 |
| Google 日历里没看到事件 | 确认日历左侧已勾选；手机 App 下拉刷新一次 |
| 事件重复 | iCal 插件的 Gist 订阅还开着，见「注意事项 2」 |
