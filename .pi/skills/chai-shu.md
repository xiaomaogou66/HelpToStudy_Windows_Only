---
name: chai-shu
description: "导入教材 PDF 并按章节拆书，生成全书大纲与分块笔记（MinerU 云端）（参数：[教材 PDF 路径]）"
allowed-tools: Read Write Edit Bash
---

> 本 skill 由 Claude 命令 `/拆书` 自动生成，请勿直接编辑。
帮我导入一本教材 PDF 并按章节拆分，让 AI 能一章一章地读完。

## 步骤

0. **先做令牌体检，并把结果反馈给我**（MinerU Token 有有效期）。运行：

   ```bash
   TF="_工具/mineru_token.txt"
   if [ -s "$TF" ]; then
     days=$(( ( $(date +%s) - $(stat -c %Y "$TF") ) / 86400 ))
     code=$(curl -s -m 15 -o /tmp/.mineru_probe -w '%{http_code}' \
              -H "Authorization: Bearer $(cat "$TF")" \
              https://mineru.net/api/v4/extract/task/0)
     if [ "$code" = 401 ] && grep -q A0211 /tmp/.mineru_probe; then
       echo "MinerU 令牌：❌ 已过期（已签发 ${days} 天）"
     else
       echo "MinerU 令牌：✅ 可用（已签发 ${days} 天）"
     fi
   else
     echo "MinerU 令牌：⚠️ 还没有保存 Token（先运行 _工具/设置MinerU令牌.bat）"
   fi
   ```

   - 这一行结果**用中文原样汇报给我**（可用 / 已过期 + 已签发多少天），再继续后面的步骤。
   - 探测只查一个不存在的任务，**不消耗 MinerU 额度**，也不会改动任何文件。
   - 如果结果是「已过期」或「还没有保存 Token」：**停下来**，让我重跑一次
     `_工具/设置MinerU令牌.bat` 续期后再继续，不要把整本书的解析跑到失败为止。

1. 确认教材来源：如果我在对话里附了文件路径或 @ 了文件就用它；否则问我要路径。
   Linux 版只支持 **PDF**（扫描版 / 数学书均可，MinerU 云端识别，公式转 LaTeX）。
2. 运行拆书：
   - 交互式：`_工具/拆书.bat`（选择 PDF 后自动完成 MinerU 解析 + 章节拆分）
   - 命令行：`_工具\.venv\Scripts\python.exe _工具/split_textbook.py "<路径>" --out "04-教材分块" --ocr mineru --split-mode chapter`
     （没有 .venv 时用系统 `python3` 代替）
   - 已有 `00-MinerU解析全文.md` 时可直接重切分，不消耗 MinerU 额度：
     `_工具\.venv\Scripts\python.exe _工具/split_textbook.py "<00-MinerU解析全文.md>" --out "04-教材分块" --split-mode chapter`
3. 拆分成功后：
   - 在 `04-教材分块/<书名>/` 下应生成：`00-教材信息.md`、`00-目录.md`、
     `01-全书大纲.md`、若干 `章节XXX-*.md` 分块。
   - 用中文汇报：书名、识别到的章节数、分块数、书文件夹路径，并贴出
     [[01-全书大纲]] 的章节清单（只列章节名，不贴正文）。
4. 询问用户下一步：是否基于这本书创建学习主题（运行 /新主题-拆解与计划），
   还是先从第一章开始逐章学习。

## 注意事项

- 不要一次把整本书的内容读进对话；分块笔记就是给 AI 逐块阅读用的。
- 如果书已经拆过（书文件夹已存在），不要重复新建文件夹，原地更新即可，
  旧分块会自动备份到库外 `~/obsidian_backups/拆书/<书名>/`（不在库内建 `_备份/`）。
- 首次使用需先运行 `_工具/设置MinerU令牌.bat` 保存 Token（免费注册 mineru.net）。
  Token 有过期时间（实测 ≥27 天仍有效），**续期就是再跑一次设置脚本**，
  它会覆盖写入 `_工具/mineru_token.txt`；步骤 0 的「已签发多少天」就是倒计时。
- 中文回复，解释要通俗。
