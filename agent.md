# agent.md — 给 AI 助手的工作规矩

**本文件是硬性约定，位阶最高。** 冲突时以本文件为准，其次 [`规矩.md`](规矩.md)。

**接手顺序**：本文件 → [`规矩.md`](规矩.md)（范式：目录 / 执行器 / 门禁 / 协作模式）
→ `projects/<项目>/项目卡.md`（当前项目）。

---

## 一、动手前先查用法（2026-09-18 新增，血泪教训）

**使用任何工具、模型、LoRA、节点、命令之前，先查它的官方用法和参数格式，不要自己盲目试。**

反面案例（真实发生，白花了几个小时）：

> 用 `Qwen-Edit-2509-Multiple-angles.safetensors` 换视角，我连续试了
> "中文散文写机位" → "T2I 逐格拼帧" → "denoise/LoRA 强度参数扫描" 好几轮，
> 视角都几乎不动、布景还被重画。
> 最后去查官方文档才发现：**这个 LoRA 有严格训练语法**
> `<sks> [方位角] [仰角] [距离]`，文档明确写「`<sks>` 触发词是必需的」。
> 我一直用中文散文，等于从没对它说过话。换成官方语法后立刻正常。

推论，按顺序执行：

1. **先找文档**：模型/LoRA 看它的 HuggingFace model card（`.../raw/main/README.md` 最完整）、
   节点看 ComfyUI 的 `/object_info`、CLI 看 `--help`。
2. **再确认版本匹配**：底座与 LoRA 的版本号要对得上（我们踩过 2509 底座 + 2511 文档的坑）。
3. **然后才动手**，并且先跑最小验证（1 个样本），不要一上来铺满。
4. **测量 ≠ 结论**：我多次用代理指标（立体声/电平/没削波/ASR 转得出字）宣布成功，
   结果人耳一听就废。**感知类的东西必须让人来判断**，不要用数字代替。

> **搜索端点 `web_search` 在本机因 API key 无效而报 401**（2026-09-20 复测仍是）。
> 替代办法（按好用程度排）：
> 1. **GitHub REST API 直连** —— `https://api.github.com/search/repositories?q=<url编码>&sort=stars`
>    （看仓库内容用 `/repos/<owner>/<repo>/git/trees/<branch>?recursive=1`，取文件用
>    `raw.githubusercontent.com`）。今天全网调研就是靠它做的。
> 2. **官方文档加 `.md` 后缀拿纯文本** —— 例如
>    `https://developers.openai.com/api/docs/guides/image-generation.md`
>    （不加后缀是 JS 渲染的，只能拿到导航栏）。
> 3. **DuckDuckGo HTML 结果页** —— `https://html.duckduckgo.com/html/?q=<url编码>`
> 4. HuggingFace 用 `/raw/main/` 路径。
>
> ⚠️ 已知抓不到的：`docs.volcengine.com`（JS 渲染，回来是空页）。

---

## 二、默认不用 PowerShell 内联命令（2026-09-18 新增）

**PowerShell 内联命令的引号/转义极易出错**，尤其是：
- `python -c "..."` 里再套引号
- SSH 远程命令里的 `|`、`'`、`"`、`$`
- 中文路径与 `\` 结尾

我因此反复浪费整轮时间在修语法上（SyntaxError、unterminated string、
"terms not recognized"、"missing mandatory parameters"）。

**约定：命令走参数调用 Python 脚本，不写内联 shell。**

通用调用器：**`.work/run.py`**

先装依赖（**新机器 clone 后必须先做这一步**）：

```bash
pip install -r requirements.txt      # 只需要 paramiko
```

然后（用 `python`，**不要写死 `.work\venv\Scripts\python.exe`** —— 那个 venv 不入库，
换机器/换系统就不存在，这正是"换系统就废"的典型）：

```bash
# 跑远程命令（整条命令作为一个参数传入，不需要在 shell 里转义）
python .work/run.py ssh "nvidia-smi --query-gpu=memory.used --format=csv,noheader"

# 传文件
python .work/run.py put local.png /root/autodl-tmp/ComfyUI/input/x.png
python .work/run.py get /root/x.wav .work/x.wav

# 上传并运行远程 Python（远程脚本参数按 argv 传，不经 shell）
python .work/run.py rpy .work/some_script.py arg1 arg2

# ffmpeg / git
python .work/run.py ff -i in.mp4 -vn out.wav
python .work/run.py git status --short

# 服务器快照（GPU/显存/队列/磁盘）
python .work/run.py probe
```

需要新的常用操作时，**往 `run.py` 里加子命令**，不要在 shell 里现编。

> 跑生成任务用**另一个**入口：`python tools/run.py <项目slug> <工作流名>`
> （见 `规矩.md` §2）。两者分工不同：`.work/run.py` 管远程命令，`tools/run.py` 管跑工作流。

---

## 三、项目硬约束（一直有效）

1. **严禁删除云端任何文件**（用户硬性要求）。实验随便做，产出写新目录。
2. **`ssh_pass.txt` 永不提交、永不打印**。服务器地址在 `ssh/server.txt`，
   **租用机重启后地址/端口会变**，每次先核实再连。
3. **图片/音视频默认被 `.gitignore` 忽略**，这是**故意的**（`规矩.md` §1：文本层进 git、产物层不进）。
   **换机器靠"文本层 ＋ 工作流 JSON ＋ `state.json` 里的哈希"重出产物**，不是靠搬文件。
   例外只有一种：**参考图不可确定性重出**（例如从参考片裁的身份基准），那必须单独搬，
   并在 `source/README.md` 里写清**在哪、怎么取**。
   ⚠️ 旧写法是"必要时 `git add -f`" —— 2026-09-20 废止：`-f` 会把大产物塞进历史，且**不可逆**。
4. **一次只跑一个占用显存的任务**。H3（约 28 GB）与 Qwen（约 20 GB）不能并发。
5. **长任务先做前置检查**（依赖是否齐、文件是否存在、语法是否对），
   再启动；不要把长任务启动后等超时才发现缺东西。
   demo：**`.work/check_before_gpu.py`**（算力门禁，跑 GPU 前必过，`规矩.md` §7）、
   `.work/probe_source.py`（下载前探测源）。
   （旧 demo 指向 `preflight_server.py` / `render_ambience.py` —— 那是音频分离线的，已换掉。）
6. 复刻的验收口径：**一致性 > 镜头语言 > 细节缺陷**，
   不是 1:1 逐动作复刻（用户 2026-09-17 明确）。
7. **下载前必须先探测下载源**（用户 2026-09-19 明确要求）——见第四节。

---

## 四、下载前必须先探测下载源（2026-09-19 新增，用户明确要求）

**任何超过约 50 MB 的下载，动手前先探测源。不许"先下着看看"。**

### 为什么（都是有实测证据的）

- **同一个文件，不同镜像能差几十倍**：同一批 Qwen 权重，ModelScope 实测 **15–17 MB/s**，
  而 hf-mirror 只有 **0.2–0.4 MB/s**。
- **1 MB Range 测速不代表真实速度**：握手/重定向开销占比过大，
  曾报 **1.9 MB/s** 而实际 **17 MB/s**。→ **探测样本必须够大（≥16 MB）**。
- **单连接速度也会严重低估，必须试并行**（2026-09-19 实测，281 MB 的 LoRA）：
  同一台机、同一个文件，hf-mirror 单连接 196 KB/s（要 24 分钟），
  **gitee 16 路并行 4.16 MB/s（68 秒）——差 21 倍**。
  → 选源之后**一律用分块并行下**（`.work/dl_chunked.py`），别用单连接硬拖。
- 盘只剩个位数 GB 时，顺序必须是 **先探测 → 再算盘 → 后下载**；
  **源不通就一个字都不删**。

### 标准动作（按顺序，缺一不可）

1. **列候选源**：ModelScope / hf-mirror / 官方 HF / GitHub Release / 官方 OSS。
2. **每个源做 HEAD**：看 HTTP 状态码、`Content-Length` 是否与预期大小一致。
3. **每个源做 ≥16 MB 的 Range 实测**，算**真实 MB/s**（不是 1 MB 的小样本）。
4. **算盘**：用 `Content-Length` 算所需空间，与 `df` 可用空间比对，**留 10% 余量**。
5. **并行下载**：用 `.work/dl_chunked.py <URL> <输出路径> <总字节数> [分块数]`
   （默认 16 块，实测 4.16 MB/s）。**不要用单连接 curl/wget 硬拖。**
6. **下完校验文件**：
   - safetensors：必须能解出 JSON 头部（张量数、dtype）；
   - 与预期大小逐字节比对。
7. **下完把实际速度记下来**（写进当轮交接），下次同类下载可以直接复用结论。

### 工具

- `.work/probe_source.py <规格名>` —— 通用探测器，规格表写在脚本顶部（新增目标往里加一条即可）。
- `.work/dl_chunked.py <URL> <输出路径> <总字节数> [分块数]` —— **分块并行下载 + 大小/头部校验**。
- 旧的 `.work/probe_lora_sources.py` 是单文件专用版，样本只有 1 MB，**只作历史参考**。
