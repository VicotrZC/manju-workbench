# manju-workbench · 漫剧制作台

用 **AI agent ＋ ComfyUI** 做漫剧 / 短剧的工作台。多项目并行，共用一个执行器。

> **名字里没有模型名，是故意的。** 这个工作台换过三代生图模型
> （SDXL → Qwen-Image-Edit-2509 → Qwen-Image-2512 ＋ Edit-2511），
> 模型会继续换，工作台不该跟着改名。

## 从哪开始

| 想干什么 | 读什么 |
|---|---|
| **接手干活** | [`规矩.md`](规矩.md) → [`projects/<项目>/项目卡.md`](projects) |
| 用户手写的硬约束 | [`agent.md`](agent.md)（**位阶最高**） |
| 跑一个生成任务 | `python tools/run.py <项目slug> <工作流名>` |

**新 AI / 新电脑 / 新聊天**：`git clone` 之后读上面那两个文件就能开工，
不需要旧聊天记录。一切状态都在 git 里。

### 开新聊天时，把下面这段原样发给新窗口

```text
工作区：E:\Learn\manju-workbench

先读两个文件，它们是唯一入口，读完直接开工，不要再问我背景：
1. 规矩.md
2. projects/美食：全市巡摆，馋哭食客/项目卡.md

现状：仓库只有小说原文（50 章）和规矩/skill/通用工具，项目内容按范式从零重走。
云机开着，隧道已就绪（python .work/launch_tunnel.py --status 可自查）；
ssh_pass.txt 已放在仓库根，不要提交、不要打印。

按 规矩.md §3 的流程走，从「戏层」开始。
有需要我拍板的（画面好不好看、要不要花钱、要不要删东西），停下来问我。
```

> 别把旧聊天记录贴给它 —— 那正是这个仓库要消灭的东西。
> 一切状态要么在 git 里，要么在 `项目卡.md` 里；两处都没有的，就是不存在的。

## 目录

```
规矩.md  agent.md            规矩（规矩.md 是范式，agent.md 位阶最高）
tools/run.py                 【唯一执行器】画布工作流 JSON → 跑 → 下产物
tools/widget_layout.json     widget 布局缓存（可 --refresh-layout 与后端对账）
.work/                       通用工具（命令执行器 / 分块下载 / 门禁 / 隧道 / 探测源）
ssh/                         通用 SSH 连接脚本
skills/                      6 个 agent skill（148 个文件，含 skill 自带示例图）
pipeline/docs/  docs/  h3res/ 权威文档（规矩.md §11 那张表）
projects/<项目>/              一个项目 = 一个文件夹（见 规矩.md §1）
```

## 环境

```bash
pip install -r requirements.txt
```

⚠️ **`ssh_pass.txt` 不在仓库里**（`.gitignore` 已排除，规矩第 2 条）。
换机器要自己放一份在仓库根，`ssh/` 下的脚本都从那里读密码。

## 硬规矩速查

跑 GPU 之前**先过门禁**：

```bash
python .work/check_before_gpu.py --file projects/<项目>/workflows/<工作流>.json
```

有 ERROR 不许开跑。完整 17 条见 [`规矩.md`](规矩.md) §5。
