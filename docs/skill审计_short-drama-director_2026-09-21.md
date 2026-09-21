# 安全审计：`short-drama-director`（漫剧老李 AIGC 全流程 Skill V6.9.8）

> **审计时间**：2026-09-21
> **来源**：`https://github.com/lixiaoxiao9888-create/manju-laoli-skill`（commit `079df68`）
> **审计人**：AI agent（本仓库会话）
> **审计方式**：克隆到隔离目录 `/tmp/skill_audit/` 后静态审计 ＋ 隔离运行自检
> **结论**：✅ **未发现安全问题，可以安装。**

## 一、为什么这件事要单独审计

**skill 是「我的 agent 会照着执行的指令」** —— 它的风险不在能不能跑，而在**它让我做什么**。
一个恶意 skill 可以让我去读 `ssh_pass.txt`、把仓库内容发到外部、或者删掉产物。
所以审计要覆盖三层：**可执行代码 / 指令文本 / 隐藏载荷**。

## 二、审计项与结果

| # | 查什么 | 方法 | 结果 |
|---|---|---|---|
| 1 | **联网能力** | 扫 `urllib/requests/httpx/socket/ftplib/smtplib/paramiko/aiohttp` ＋ 全仓 URL | ✅ **脚本零联网能力**。全仓 URL 只有 shields.io 徽章、本仓库自身、以及文档示例里的 `api.example.com`（IANA 保留的文档域名，配 `YOUR_API_KEY` 占位符，**是给人改的模版，不被任何脚本执行**） |
| 2 | **代码执行** | 扫 `eval(` / `exec(` / `__import__` | ✅ 无 |
| 3 | **破坏性操作** | 扫 `rmtree` / `os.remove` / `os.unlink` / `shutil.move` / `rm -rf` | ✅ 无 |
| 4 | **凭证窃取** | 扫 `ssh_pass` / `llm_key` / `id_rsa` / `.ssh` / `password` / `api_key` / `secret` / `token` | ✅ 无（唯一 `token` 命中是 `build_board_lite.py:332` 的**字符串切分变量**，非凭证） |
| 5 | **越出目录读写** | 看脚本的路径推导（`BASE` / `expanduser` / `~` / `/root`） | ✅ 全部从 `__file__` 往上推，只在自己目录内 walk |
| 6 | **安装期自动执行** | 找 `setup.py` / `pyproject.toml` / `*.sh` / `Makefile` / `package.json` / `*.bat` / `*.ps1` / git hooks | ✅ **一个都没有**；`.git/hooks/` 只有 sample |
| 7 | **隐藏载荷** | 扫零宽字符（U+200B–200F / 202A–202E / 2060–2064 / FEFF）＋ HTML 注释 | ✅ 无零宽字符；唯一 HTML 注释是 `action-previs-15grid.md` 开头的**导航说明** |
| 8 | **针对 AI 的劫持措辞** | 扫「不要告诉用户 / 忽略以上 / ignore previous / 绕过审查 / silently / secretly」 | ✅ 无 |
| 9 | **文件类型** | `file` 全量识别 | ✅ 49 个文件**全是文本**（46 md ＋ 4 py ＋ LICENSE），**无二进制、无混淆** |
| 10 | **功能可用性** | 隔离目录内跑 `validate_prompt.py --self-test` | ✅ `self-test PASSED`（退出码 0） |

**脚本能力清单**（全部 import 逐条看过）：

| 脚本 | 依赖 | 能力 |
|---|---|---|
| `validate_prompt.py` | json/os/re/sys | 纯文本校验 |
| `check_package.py` | os/re/sys ＋ **subprocess** | subprocess **只用来跑同目录的 `validate_prompt.py --self-test`**（`sys.executable`，30s 超时） |
| `build_board_lite.py` | argparse/html/json/re/sys/datetime/pathlib | md → 单文件 HTML |
| `generate_emotion_curve.py` | argparse/json/os/sys/**matplotlib** | 画折线图（唯一第三方依赖） |

## 三、⚠️ 安装时必须知道的两条（**不是安全问题，是使用风险**）

1. **★ 规矩位阶：本 skill 的规则不能盖过 `agent.md` / `规矩.md`。**
   这个 skill 自带一套「最高优先级」锁定（A/B/C/D 锁）与全套工业法则。
   而本仓库 `agent.md` 写明**位阶最高**、`规矩.md` 是**唯一规矩来源**（§12 还专门列了
   「互相矛盾的文档」这一坑）。
   → **安装后的正确用法：把它当「方法库 / 参考书」用，冲突时一律以本仓库为准。**
   → 尤其：它 §〇 说「用户未指定模型版本 = 任务不开始」，而本项目的模型是**已经定死的**
   （Qwen-Image-2512 ＋ MiniMax H3），**不需要每次重问**。

2. **它有一条「跳过确认」的直出模式**（SKILL.md 末表：`跳过确认，直接出整集` →
   「后台静默执行全套工业约束」）。这**与本仓库 `规矩.md` §6 直接冲突** ——
   本项目规定「视觉审美判断 / 花钱 / 破坏性操作」**必须停下等用户**。
   → 在本项目里**不使用该模式**；本项目的「出图必须先过门禁 ＋ 等用户拍板」优先。

> 另：它的主推模型是 **Seedance 2.5/2.0**，本项目用的是 **Qwen-Image（图）＋ MiniMax H3（视频）**。
> 与本项目直接相关的是它的 **`references/h3-adapter.md`（H3 格式支线）** 那一条线，其余部分
> 属于另一套模型契约，**不要照搬**。

## 四、安装记录

| 项 | 值 |
|---|---|
| 仓库内位置 | `skills/short-drama-director/`（随 git 走，符合 `规矩.md` §1） |
| agent 可发现位置 | `~/.dsh/skills/short-drama-director/`（会话 skill 目录只读这里） |
| 规模 | 49 个文件 / 756 KB / SKILL.md 233 行 / references 41 个 |
| 许可 | MIT |
| 安装前处理 | 已删除我跑自检产生的 `__pycache__`，安装的是干净副本 |
| 未安装 | 无（仓库里没有任何需要排除的文件） |

> ✅ **装完当场就被发现了** —— 本会话的 skill 目录已刷新出 `short-drama-director`
> （原先我按经验写的是「要新开会话才生效」，**实测不需要**，已更正）。
> 另按 `规矩.md` §10：`skill` 工具**调不到仓库内** `skills/` 下的 skill，
> 仓库那一份要用 read 直接读 `SKILL.md`；能被我按名字调用的是 `~/.dsh/skills/` 那一份。
