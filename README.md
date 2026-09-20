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

## 目录

```
规矩.md  agent.md            规矩（规矩.md 是范式，agent.md 位阶最高）
tools/run.py                 【唯一执行器】画布工作流 JSON → 跑 → 下产物
tools/widget_layout.json     widget 布局缓存（可 --refresh-layout 与后端对账）
.work/                       通用工具（命令执行器 / 分块下载 / 门禁 / 隧道 / 探测源）
ssh/                         通用 SSH 连接脚本
.zcode/skills/               6 个 agent skill
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
