# MiniMax H3 使用与避坑手册

> 本机环境：ComfyUI 0.35.1，单卡 32GB vGPU（RTX 4080 SUPER 档），
> 权重 `minimax_h3_ref2va_pruned_int8_convrot.safetensors`（int8 量化）＋
> `minimax_h3_ref2v_turbo_4step_v0.1` LoRA。
>
> **证据等级标注**（每条结论后面都标了来源，请按等级采信）：
> 【官方】官方文档 / 节点自带说明　【实测】本机跑过并留了证据文件　
> 【社区】网上资料（见第 12 节链接）　【未证实】只听说、没验证
>
> ⚠️ **两条先看的**：① 许可证**禁止在美国/欧盟/英国/韩国**使用或分发本模型**及其产出**（§13.1）；
> ② 官方模板默认是 **20 步**，我们一直用的 4 步是官方定义的**最低质量加速档**（§3.2）。

---

## 0. 一句话理解 H3

**H3 是音视频一体的参考生成模型**：一次前向同时生成画面和声音（对白＋环境声＋配乐），
不是"先出画面、再配音"的两段式管线。

理解这一点，后面大部分坑都能解释：
- 为什么对白会重复、会丢句——它是在**视频 latent 旁边并排生成音频 latent**；
- 为什么想只保留环境声却很难——对白和环境声在**同一条音轨**里；
- 为什么"挂着的肉时有时无"用提示词治不好——那是**时间维度的属性**，不是外观属性。

## 1. 模型与节点全景

### 1.1 需要的权重（本机实际在用的四件套＋1 个 LoRA）

| 用途 | 文件 | 说明 |
| --- | --- | --- |
| 主模型 | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | int8 量化版，**不是 BF16**，显存友好 |
| 文本编码器 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | CLIPLoader 的 `type` 必须选 **`minimax`** |
| 视频 VAE | `minimax_h3_video_vae_fp16.safetensors` | 解码画面 |
| 音频 VAE | `minimax_h3_audio_vae_fp32.safetensors` | 解码音轨，**没有它就没有声音** |
| 加速 LoRA | `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | 4 步预览档专用，强度 1.0 |

> **官方目录布局与两套权重（别下错）**（`docs.comfy.org/.../minimax-h3-native`）：
>
> ```
> ComfyUI/models/
> ├── diffusion_models/  minimax_h3_fl2va_pruned_int8_convrot.safetensors   ← T2V / I2V 用
> │                      minimax_h3_ref2va_pruned_int8_convrot.safetensors  ← R2V（我们）用
> ├── text_encoders/     qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
> ├── vae/               minimax_h3_video_vae_fp16.safetensors
> │                      minimax_h3_audio_vae_fp32.safetensors
> ├── loras/             minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
> │                      minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
> └── embeddings/        minimaxh3_art_is_explosion.safetensors
> ```
>
> **fl2va 与 ref2va 是两套不同的权重**，用 R2V 模板就必须下 ref2va 那个。
> "pruned" = AdaLN 剪枝，体积小约 40%，**只能在 ComfyUI 里用**，社区绝大多数量化都基于它。

### 1.2 节点有多少个（实测 `/object_info`）

从本机 ComfyUI 抓到的事实：

- **核心 H3 节点 79 个**：三个推理节点（`MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo` /
  云端的 `ComfyCloudMiniMaxH3TextToVideoNode` 系列）、`MiniMaxH3SigmaShift`、`MiniMaxH3AddGuide`、
  `MiniMaxH3TokenCounter`、`MiniMaxH3MemoryEfficientSageAttentionPatch`、`MiniMaxChunkFeedForward`、
  以及社区/工作室加的 `*T8` 系列（长视频、音频窗口、提示词标签、AV 解码……）。
- **`*T8Advanced` 扩展节点 241 个**，覆盖长视频拼接、颜色匹配、人脸修补窗口、RAFT 运动审计、
  FlashVSR/RealBasicVSR 修复、DLSS 超分、世界模型动作时间线等等。

> **不要被节点数量吓到。** 一条能出片的 H3 图只有 5 类节点：**加载器 → 推理节点 → 采样链 →
> 解码（画面＋音频）→ 封装保存**。其余 300 多个节点是在解决"更长、更稳、更清晰"的工程问题，
> 全都不影响你先把一个 5 秒镜头跑出来。
> 复现命令：`.work/run.py py .work/dump_h3_nodes.py --list`

### 1.3 三种输入模式，先选对

| 模式 | 节点 | 输入 | 什么时候用 |
| --- | --- | --- | --- |
| 图生视频 / 首尾帧 | `MiniMaxH3ImageToVideo` | `first_frame`（可选）、`last_frame`（可选） | 有合格首帧、只要动起来；**起步建议** |
| 多模态参考 | `MiniMaxH3ReferenceToVideo` | `ref_images` 0–9、`ref_videos` 0–3、`ref_video_audios`、`ref_audios` | 需要人物/风格/动作/音色参考 |
| 文生视频（云） | `ComfyCloudMiniMaxH3TextToVideoNode` | 纯文本 | 没有本地卡、走 Comfy Cloud |

**本项目的选择：`MiniMaxH3ReferenceToVideo`（Ref2VA）**，因为我们需要同时喂
"首帧 + 角色身份 + 场景"三类参考。

> 【官方】三种模式不要简单排优劣：FL2VA 用于关键帧条件，Ref2VA 用于多模态参考，
> FunControl 是额外控制手段。**普通参考图不等于严格首帧，也不能靠提示词把它宣称为硬锁定。**

#### 两个底座变体的差别（社区索引，值得知道）

| 变体 | 接受什么 | 社区说法 |
| --- | --- | --- |
| **H3-Base-FL2VA** | 0 / 1 / 2 张图（文生视频 / 首帧或尾帧 / 首尾帧） | **只用关键帧训练，原始画质通常更好** |
| **H3-Base-Ref2VA** | 最多 **9 张图 ＋ 3 段视频（各 2–15 秒）＋ 3 段音频**，合计 12 个文件 | 参考能力更强，但**基础画质更低**；社区有 "Ref Patch" 部分弥补 |

> 【社区】这条对我们有直接含义：**如果一镜只需要首帧，FL2VA 可能比 Ref2VA 更干净**；
> Ref2VA 的优势在"要同时喂角色 / 场景 / 动作 / 音色"的时候。
> 单镜上限：**2K 分辨率、15 秒**（来自同一份社区索引）。


## 2. 实证配方：一条能出片的 Ref2VA 图（可直接抄）

这是我们四镜成片（`.work/EP01_meat_FINAL.mp4` 及后续版本）实际用的链路，
画布文件在 `workflows/video_h3_s0*_*_r2v.json`，构造代码 `.work/render_v6_r2v.py`。

| # | 节点 | 关键参数 | 说明 |
| --- | --- | --- | --- |
| 1 | `UNETLoader` | int8 主模型 | |
| 2 | `LoraLoaderModelOnly` | turbo 4step，强度 1.0 | **4 步必须配这个 LoRA** |
| 3 | `CLIPLoader` | qwen3vl_32b…，type=`minimax` | type 选错直接报错 |
| 4 | `VAELoader` | `minimax_h3_video_vae_fp16` | |
| 5 | `VAELoader` | `minimax_h3_audio_vae_fp32` | 第二个 VAE，别漏 |
| 6+ | `LoadImage` ×N | 每张参考图一个节点 | 接到 `ref_images.ref_image_0..N` |
| 7 | `MiniMaxH3ReferenceToVideo` | `width=1344, height=768, length=N, ref_image_size=max` | 输出 `positive` + `LATENT` |
| 8 | `RandomNoise` | seed，`fixed` | |
| 9 | `BasicGuider` | model ← LoRA 输出，conditioning ← positive | |
| 10 | `KSamplerSelect` | `res_multistep` | |
| 11 | `BasicScheduler` | `simple`，`steps=4`，`denoise=1.0` | 4 步预览档 |
| 12 | `SamplerCustomAdvanced` | noise/guider/sampler/sigmas/latent | |
| 13 | `VAEDecode` | 视频 VAE | 出 IMAGE |
| 14 | `VAEDecodeAudio` | 音频 VAE | 出 AUDIO |
| 15 | `CreateVideo` | `fps=24.0` | 画面＋音轨合成 |
| 16 | `SaveVideo` | 前缀，`format=auto`，`codec=auto` | |

**成品规格**：1344×768、24fps、32kHz 立体声。

> **⭐ 帧数必须落在 `17k + 5` 网格上（官方文档原文）**：
> "the duration input **snaps** to the model's 17-frame-per-block (**17k+5**) grid at 24fps"
> —— `docs.comfy.org/tutorials/video/minimax/minimax-h3-native`。
> 合法值：5, 22, 39, 56, 73, 90, 107, **124**, 141, 158, **175**, 192, **209**, 226 … 362。
> 节点本身允许 5–3600、步长 17（`/object_info`），默认 124；5 秒 = 124 帧、15 秒 = 362 帧，
> 与官方"单片段最长 15 秒"一致。

**【实测】不在网格上的帧数会被"向上吸附"，片子比你要的长**——我们四镜踩得结结实实：

| 镜 | 我请求的帧数 | 网格值 | 实际时长 | 实际帧数 |
| --- | ---: | ---: | ---: | ---: |
| S01 | 162 | → **175** | 7.29s | 175 |
| S02 | 198 | → **209** | **8.71s** | 209 |
| S03 | 170 | → **175** | 7.29s | 175 |
| S04 | 94 | → **107** | 4.46s | 107 |
| 合计 | 624（我以为是 26.0s） | **666** | **27.78s** | 666 |

测量方式：`tools/ffmpeg.exe -i`，四个片段与 `EP01_meat_FINAL.mp4`（27.78s）完全对得上。

> 这条直接解释了用户抱怨的 **"S02 有约 6.6 秒空场"**：
> 我按 198 帧（8.25s）写提示词和台词，模型实际给了 **209 帧 = 8.71s**，
> 多出来的 0.46 秒是白送的，而台词本来就只写到 2.1 秒。
> **教训：先选网格上的长度，再按这个真实秒数写台词和动作节拍。**

## 3. 参数详解与边界

### 3.1 `MiniMaxH3ReferenceToVideo` 的全部输入（实测 `/object_info`）

| 输入 | 类型 | 默认 / 范围 | 怎么理解 |
| --- | --- | --- | --- |
| `clip` | CLIP | 必填 | 文本编码器 |
| `prompt` | STRING（多行） | 必填 | 六段式，见第 4 节 |
| `width` / `height` | INT | 1344 / 768，步长 32 | **1344×768 是 7:4，不是 16:9**，最终画幅要自己决定裁切还是补边 |
| `length` | INT | 124，范围 5–3600，步长 17 | 帧数；**必须落在 `17k+5` 网格上**（5/22/39/…/124/141/158/175/192/209/…/362），否则会被**向上吸附**；24fps 下 124 帧 ≈ 5.17 秒 |
| `ref_image_size` | COMBO | `match` / `max`，默认 `match` | **官方语义**：`match` 把参考图缩到生成分辨率（快）；`max` 保留到**短边 2048px**（身份更像、更慢） |
| `vae` | VAE | 可选 | **不接：参考图只影响文本编码器**，不参与真正的视觉 conditioning |
| `audio_vae` | VAE | 可选 | 同上，音频参考同理 |
| `ref_images` | 自动增长 | 0–9，前缀 `ref_image_` | 参考图；**提示词里必须逐张点名**，否则模型不知道它是干什么的 |
| `ref_videos` | 自动增长 | 0–3，前缀 `ref_video_` | 参考视频；**要的是 IMAGE 帧序列（24fps、2–15 秒），不是文件路径** |
| `ref_video_audios` | 自动增长 | 0–3 | 参考视频对应的音频 |
| `ref_audios` | 自动增长 | 0–9 | 单独的音色/音频参考 |

> 【官方（节点说明）】不接 `vae` / `audio_vae` 时，参考图和参考音频**只条件化文本编码器**——
> 这是很多人"明明喂了参考图却没效果"的第一个原因。

### 3.2 采样参数

| 参数 | 我们用的 | 备注 |
| --- | --- | --- |
| `sampler_name` | `res_multistep` | 配合 4 步 LoRA |
| `scheduler` | **`simple`** | 【实测】4 步时用 `beta` 会出整帧品红偏色与涂抹 |
| `steps` | 4（预览） / 8 或 20（质量） | 4 步只是**预览档**，低清结果不能证明正式质量 |
| `cfg` | 1.0（走 `SamplerCustomAdvanced` 时不暴露） | |
| fps | 24 | 参考视频也要按 24fps 重抽 |

**【官方】官方模板的默认档与我们不同，别搞混：**

| | 官方模板默认 | 官方 turbo 模式 | 我们（预览档） |
| --- | --- | --- | --- |
| 步数 | **20 步**（文档建议提到 25 步以改善运动质量） | FL2VA：`turbo_steps` 默认 **8**；Ref2VA：**4** | 4 |
| 开关 | 关 | 节点上的 `turbo_mode` / Lightning LoRA 勾选框 | 直接挂 LoRA 节点 |
| 强度 | — | `turbo_model_strength` 默认 1.0 | 1.0 |
| 代价 | 慢 | 官方原话：**音频和运动质量会略降**（slightly lower audio and motion quality） | 同左 |

> 换句话说：**我们一直在用官方定义的"最快、质量最低"那一档。**
> 用户抱怨"画面不如前面几版"时，先确认是不是该上 20/25 步再下结论。
>
> ⚠️ **而且这一档还带一个确定性缺陷**：4 步 LoRA `ref2v_turbo_4step_v0.1` 会让**相机不受控地漂移**
> （主体甚至出画），且**不报任何错**；同 seed 下 8 步 LoRA 或不用 LoRA 的 30 步都正常。
> 详见 §13.11 —— 这条直接关系到"我们明明写了 camera holds still 却还在推拉"。

> 【官方（模板注释）】参考类提示词下 `beta` / `normal` 调度器**往往**优于 `simple`——
> 但那是 20 步的结论。**4 步 + beta 实测翻车**，不要把高步数的结论搬到低步数档。

**低步数档的社区经验（都是一句话能省几天时间的）**【社区】：

- Turbo 4 步档在 **6–8 步**下动感涂抹（motion smear）会明显减少；
- 除了 Turbo，还有两条加速线：**PDD 8-step Acc LoRA**（被认为是更稳的默认档）
  和 **FastH3 4-step**（更快，但纹理损失更多）；
- 4 步产物只当**预览**：构图、动作、台词对了就往下走，别拿它评画质。


## 4. 提示词：必须用对模式

### 4.1 两种 schema

| 模式 | 字段 |
| --- | --- |
| **基础模式** | `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music` |
| **完整参考模式（Ref2VA 用这个）** | `subject_definitions` / `summary` / `retention_analysis` / `detailed_description` / `overall_soundscape` / `non_diegetic_music` |

> 【实测】v1–v5 一直把**三段式提示词喂给 Ref2VA 节点**，等于只给了模型基础模式的信息；
> 更糟的是 v5 接了 3 张参考图却在提示词里**一次都没提到**，结果与只用首帧的 v4 几乎一模一样。
> **槽位喂了不等于模型知道它是什么。**

### 4.2 四种标签（官方原文要点）

| 标签 | 含义 |
| --- | --- |
| `<Subject N>` | 从参考素材里抽象出来的**可复用可见内容**（人、动物、物体、场景、服装、道具、风格、动作、表情、姿势） |
| `<Picture N>` | 作为**具体目标帧**或分镜锚点的参考图 |
| `<Video N>` | 提供剪辑源、续接起点或**整片时间结构**的参考视频 |
| `<Audio N>` | 被复制或被参考的音频信号 |

> 官方原文关键句：**"Once a reference label is assigned to a piece of content, it keeps the same
> meaning across all six sections."**（标签一旦分配，六段里含义必须一致。）

- `<Picture N>` **只有当它本身就是某一镜的首帧/关键帧/尾帧/构图锚点时才单独成条**；
  如果只是用来定义角色长相、场景、服装、风格，就写进对应 `<Subject N>` 的定义里。
- 一个 `<Subject N>` 可以由多个素材共同定义（如"长相来自 `<Picture 1>`，走路动作来自 `<Video 1>`"）。
- `<Video N>` 与 `<Audio N>` **各自独立编号**，编号不表示配对关系；
  同一个参考视频可以同时是 `<Video 1>` 和 `<Audio 2>`。
- **普通参考视频不会因为文件里有声音就自动产生 `<Audio N>`。**

### 4.3 `summary` 的任务类型前缀（官方枚举）

`[reference generation]`、`[keyframe completion]`、`[video editing]`、`[video continuation]`、
`[audio reuse]`、`[audio reference]`；多关系时用 ` + ` 连接且不重复。

我们四镜用的是：`[reference generation + keyframe completion]`
——首帧是具体帧锚（keyframe completion），其余素材提供生成指导（reference generation）。

### 4.4 `retention_analysis` 的固定标记（官方枚举）

**可见内容**（`<Subject N>` / `<Picture N>` / `<Video N>`）：

| 标记 | 含义 |
| --- | --- |
| `fully_preserved` | 定义的角色被完整保留 |
| `partially_preserved` | 仍在用，但部分特征被改动或只保留一部分 |
| `attribute_transfer` | 参考特征被转移到另一个可识别的目标主体上 |
| `weak_reference` | 只保留风格/类别/构图/氛围上的大致相似 |

**音频**（`<Audio N>`）：`fully_copy` / `partially_copy` / `reference` / `weak_reference`。

格式示例（官方）：

```text
<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - ...
<Picture 2> ([Shot 1] first frame): fully_preserved - ...
<Audio 1>: reference - the target speaker follows <Audio 1>'s voice timbre and measured delivery without copying the original signal.
```

### 4.5 `detailed_description` 的写法

- 正文英文；**对白、歌词、画面里可见的文字保留原语言**。
- 风格用一两句英文写在 `[Shot 1]` **之前**（这是完整参考模式与 T2VA 的差别之一：
  T2VA 的风格句写在 `[Shot 1]` 之后）。
- `[Shot 1]` 不带时间码；后续镜头写 `[Shot N] At MM:SS.mmm, ...`。
- 说话人给稳定 ID：`(S1)`、`(S2)`…；对白写 `<d>[语言] 台词</d>`。
  参考主体说话时**同时保留视觉标签和说话人 ID**：`<Subject 2> (S1) turns toward ... and says, <d>…</d>`。
- 跨切口的对白用 `<scenetrans>`；被结尾截断的话用 `<cutoff>`。
- 听不清的地方写 `[unclear]`，**不要猜、不要改写**。
- 字数：生成任务通常 **350–500 英文词**；对白密集的内容优先保证"说完整条时间线"，
  而不是机械凑字数。单镜头不代表就该写短。

### 4.6 对白写法与"烧字幕"

- 对白写在 `detailed_description` 里，格式 `<d>[Chinese] 台词。</d>`，并交代音色与语速。
- 【实测】**提示词里出现 `<d>…</d>` 时，模型有概率把台词当成"画面里可见的文字"画进画面**。
  解法：在 `detailed_description` 结尾写死一句
  `No subtitles, captions or on-screen text appear at any point.`
- 场景里本来就有的文字（价签"生猪肉 28 元"）**应当保留**，官方指南明确要求保留场景可见文字，
  并要把它的语言原样写进提示词。

### 4.7 完整示例（我们的真实提示词，S02 第 6 版）

见 `.work/render_v6_r2v.py` 里的 `PROMPT` 常量，六段齐全，可直接对照抄结构。

## 5. 坑点清单（现象 → 根因 → 解法）

> 这一节是全篇最值钱的部分。每条都注明证据文件。

| # | 现象 | 根因 | 解法 |
| --- | --- | --- | --- |
| 1 | **加参考图/改提示词都没用，人物长相始终等于首帧里的人** | 当首帧里已经有一张具体的脸，`<Picture N>` 身份参考**压不过首帧** | 只能改**首帧本身**；改不动就承认"身份基准 = 首帧的来源"。实测 9 种配置（denoise 0.5/0.65/0.8/1.0 × empty/encode × 换种子）全部无效 |
| 2 | 越改越乱、比前几版还差 | 在参考片原帧上一直漂移，模型不能重建 | 先确认首帧是不是"别人的原帧"（我们曾逐像素验证：与参考片帧 **max abs diff = 0**） |
| 3 | 整帧品红偏色 + 涂抹 | 4 步 + `beta` 调度器 | 4 步固定 `simple`；要试 `beta` 就上 20 步 |
| 4 | 画面里烧进字幕 | 提示词里的 `<d>` 被当成画面文字 | 加 `No subtitles…` 那句；场景自带文字保留 |
| 5 | **挂着的肉/菜板时有时无** | "必须持续存在"是**时间属性**，静态参考图管不了 | 用 `ref_videos` 给"随时间怎么变"的参考。方向已被四镜验证；**具体百分比因对照构图不同不可比**（早先报的 −70.6%/−39.7% 已撤回） |
| 6 | 参考视频接进去动作变慢 | 参考片是 30fps，没重抽 | **先按 24fps 重抽**再喂 `ref_videos`，否则动作被读慢约 20% |
| 7 | 镜头中间大段"死气" | ①台词说完镜头还没完；②**帧数请求不在 17k+5 网格上，被向上吸附，镜头比你以为的长** | 用网格值（124/141/158/175/192/209…），**按真实秒数**对齐台词与动作节拍。实测 S02 请求 198 帧 → 实得 209 帧 = 8.71s，多送 0.46s |
| 8 | 台词丢失 / 重复 | 音频和画面同时生成，长镜头里模型会自己"补戏" | 逐镜 ASR 核对（我们有一次 11/12 句、一次 11 句全在）；发现丢句就补提示词或改首帧 |
| 9 | 想只保留环境声、去掉对白 → 音轨废掉 | 用 demucs 分离，结果**整条混音都进了 `vocals`**，`no_vocals` 比原轨低 28–39dB，放大后全是底噪 | 别用音乐分离模型拆"对白 vs 环境声"；改用**H3 再渲一遍纯环境声**（提示词剥掉 `<d>` 段），实测 PASS |
| 10 | 配音叠了三层、听起来"乱七八糟" | 把原生音轨＋TTS＋环境声直接叠加 | 先定"以哪条为准"，再谈混音；最干净的是**从未混过的 H3 原生轨** |
| 11 | TTS 说不出人话、不结尾 | `indextts2` CLI 走 **2.0 代码路径**加载 2.5 权重 → 212 个权重随机初始化 | 直接用 `from indextts.infer_v2_5 import IndexTTS2`；**别用 CLI** |
| 12 | 语速不对 | 克隆继承了参考音的拖腔 | `infer(..., duration_factor=…)`；**男女主方向相反**：男主 ≈1.0，老板要 0.50–0.60 |
| 13 | 克隆出来是别人的声音 | 参考音本身串了说话人/几乎是静音 | 先量电平与 ASR：`C04_vendor_short.wav` 实测 −33.4 dBFS、ASR 无语音，**不能用** |
| 14 | 单镜结论当全局结论 | 个别镜头基线本来就稳 | 至少四镜平均再下结论（我们曾据 S02 单镜误判"参考图治不了挂肉"） |
| 15 | 提示词里写死数量/物件与实际不符 | 模型按文字重新分配 | 提示词里**别点名首帧里不存在的东西**（写"one large slab"而首帧有好几块 → 挂肉数量来回跳） |
| 16 | 多视角 LoRA 不生效 | 它有**严格训练语法**：`<sks> [方位角] [仰角] [距离]`，`<sks>` 必需 | 写中文散文等于从没对它说话；另实测**只擅长方位角**，距离/仰角几乎无感 |
| 17 | 灰底规范角色卡当身份参考无效 | 参考图压不过首帧（同 #1） | 想让资产生效，必须让资产成为**首帧的一部分** |
| 18 | 画布 JSON 直接当 API 提交失败 | 两者格式不通用（`widgets_values` 顺序、前端专用字段） | 用 `tools/run.py`（唯一执行器，内部做转换），**别手写 API JSON** |
| 19 | 装依赖服务器卡死 | `pip` 解析依赖去拉 2GB CUDA 版 torch | 一律 `--no-deps`，torch 借 ComfyUI 的 venv；长任务前先跑前置检查 |
| 20 | 换电脑后素材不见了 | `*.png` / `*.mp4` / `*.wav` 被 `.gitignore` 排除 | **产物不进 git 是刻意的，不是 bug**：从文本层（工作流 JSON ＋ 提示词 ＋ 种子）重出。只有**不可确定性重出的**（参考片、身份基准图）才单独搬，并在项目卡的资产表里标出来（规矩.md §1 / §4） |
| 21 | "这版画面还不如前面几版" | **一直用官方 turbo 4 步预览档**（官方原话：音频和运动质量略降）；官方模板默认是 20 步 | 拿同一 seed 跑 **20/25 步**或 **PDD 8 步**再对比；4 步产物只用来验构图/动作/台词 |
| 22 | 用 R2V 模板却报缺少模型 | T2V/I2V 用 `fl2va`、R2V 用 `ref2va`，**两套权重** | 按第 1.1 节官方目录布局核对文件名 |
| 23 | API 提交时参考图/参考音频**像没生效** | API 图里参考输入是**点分命名空间** `ref_images.ref_image_0` | **写裸名 `ref_image_0` 会被静默忽略**（能出片但没引用），见 §13.3 |
| 24 | 改了提示词，画面**一模一样** | 已知 bug #15805：提示词对输出零影响，同 seed 不同 prompt 可出像素相同结果 | 换 seed 再试；若仍然完全一致，别怀疑自己的提示词，先怀疑版本 bug |
| 25 | 长片跑到一半被系统杀 | **主机内存**不够（不是显存） | 加 `--disable-pinned-memory`；官方称优化后总占用可降到 42.5 GB |
| 26 | 4 步档音频发炸/失真 | ComfyUI 0.30.0 把音视频放在同一条 schedule 上，4 步**过步进音频** | 由 kijai **PR #15243**（2026-08-06，`ModelSamplingAV`）修复；**升级版本**或改用更高步数 |
| 27 | **相机自己摇、主体漂出画面**（明明写了"camera holds still"） | **4 步 turbo LoRA `ref2v_turbo_4step_v0.1` 的已知确定性缺陷**（已合并的 InvokeAI PR #228 受控对照证实；见 §13.11） | 同一 seed 换 **LightX2V 8 步 v1.0**，或不用 LoRA 跑 30 步对照；**这是无报错的失败** |

---

## 6. 角色资产：身份锁到底锁在哪一层

### 6.1 优先级（社区/研究结论，与我们的实测吻合）

> **首帧垫图 ＞ LoRA / FaceID ＞ 固定 Seed ＞ 纯文字**
> —— `research/REPORT-AI叙事视频管线与质量控制.md`

我们的实测把这条钉死了：**参考图、参考视频、提示词三者都改不动首帧里已有的那张脸**
（第 5 节 #1）。所以"角色一致性"的正确做法是：

1. **先把角色的脸做进首帧**（首帧是唯一真正硬的身份锚）；
2. 再用 `ref_images` 补**首帧看不到的角度/服装**；
3. 文字提示词只做最后一道保险。

### 6.2 参考图槽位顺序：⚠️ 这条要更正

**官方规则只有两条**【官方】：

1. **接线顺序 = 呈现顺序**（presentation order），所以 `<Picture N>` 的编号由连线决定；
2. **给每个参考显式分配职责**（哪张管身份、哪张管风格、哪张管运动/运镜、哪张管音色）。

> ❌ **更正**：本手册早期版本、以及我们内部的
> `research/REPORT-AI叙事视频管线与质量控制.md` 里写的
> **"场景图 → 道具图 → 人物定妆图"固定槽位约定，在官方文档和社区来源里都查不到**
> （深度调研用两条独立检索都得到否定结论）。它是**本项目自己的约定**，
> 不是行业标准——照它做没问题，但不要说成"官方要求"。

一条确实值得遵守的**我们自己的**纪律：**空镜纪律——场景图里严禁出现人物**，
否则人物参考会被污染（我们的 `SCN-pork_stall_hero.png` 就是无人物空摊位，九宫格也全部无人物）。

### 6.3 我们现在有什么

| 资产 | 位置 | 内容 |
| --- | --- | --- |
| 角色 5 视图 | `assets/CHR/C01_*`、`C04_*` | 头正/侧/3-4、身体正/背（**身体卡按 SOP 砍头**，避免两个取脸来源） |
| 表情 | 同上 | C01 九个、C04 四个 |
| 服装细节 | 同上 | C01 五张、C04 两张 |
| 场景 | `assets/SCN/` | hero 空镜、9 宫格（**由 hero 用 `<sks>` 语法同源派生**）、平面/机位调度图 |
| 道具 | `assets/PRP/` | 砍刀、五花肉、砧板、浅蓝踏板车、手机 |
| 文字卡 | `assets/character/CHAR_BOY.md`、`CHAR_VENDOR.md` | 参数、提示词、踩坑、迭代记录 |
| 参考片裁的角色卡 | `assets/CHR/FILM/` | **已弃用**（是"让资产跟随参考片"那轮方案的遗留） |

### 6.4 转身卡/身份卡该包含什么

见 `.work/FINDINGS_角色身份卡_网络调研.md`（含 6 个网络来源）。核心要素：
多视角转身图、表情、服装/道具拆解、色板、道具与握持关系、**标注 callouts**、
身份锁（不可改特征逐条列出）、视觉 ID 说明；版式 **16:9、白底、图解式**。

**两个必须分开的东西**：
- **给人看的卡**（带标签、色板、标注）→ 资产锁、验收、给下游绑定；
- **喂模型的图**（干净、无字）→ 因为图生图模型会把卡上的文字/色块/网格当画面内容画进去。

## 7. 镜头与光线

### 7.1 画幅

- 1344×768 = **7:4**，不是 16:9。最终画幅必须显式决定**裁切还是补边，不要拉伸**。
- 首帧准备时就把画幅做成模型输出画幅，省一次重采样。

### 7.2 机位与遮挡（我们踩得最狠的一条）

- **主角的脸不能被前景道具挡住。** 参考片 S02 的"凑近闻悬挂的肉"这段里，
  肉块在画面中央挡了 8 秒，换帧解决不了（整段都挡）——
  最后是**改调度**：从"闻悬挂的肉"改成"低头看案板上的肉"，遮挡消失。
- 静态机位最稳："The camera holds still for the whole shot." 写进去；
  没有明确需要就不要让模型自己推拉。
- 越轴问题在**前期调度图**里解决（我们有 `SCN-pork_stall_plan/cams` 两张程序化调度图：
  A/B 分界线、机位视锥、锚点物编号、1m 比例尺）。

### 7.3 光线

**官方要求**：完整参考模式的 `detailed_description` 里，每个镜头都必须交代
**环境与光线**（官方原文列的要素：current composition, subject appearance and position,
**environment and lighting**, actions and state changes, camera movement, current sound）——
光不是"风格形容词"，是要在镜头描述里写清楚的东西。

- **H3 的光线主要继承首帧**【实测】：首帧是暖色红吊灯 ＋ 湿地面反光，成片就保持这个调子。
  想换光 → **换首帧**，或在镜头描述里写明确的光位/色温/光比，不要指望靠两三个形容词改。
- **参考视频的调色会覆盖提示词里的打光**【社区】——用 `ref_videos` 时别指望提示词能主导色调。
- 实用写法（我们的经验）：写**光源类型与位置**（顶部红色伞形吊灯、摊位内实用光、
  地面湿反光）、**色温倾向**（暖）、**光比**（面部阴影柔和），比写"电影感光线"有效得多。
- ⚠️ **别做低照度大光比**：H3 在 32× 网格上推理，暗部细节本来就少；
  人脸再被压暗，出来就是"塑料脸"（社区也把 plastic look 归到这一档问题上）。
- 场景一致性优先于单帧好看：**九宫格同源派生**（同一张 hero 派生出 8 个方位）
  在定义上就保证了"是同一个摊位"，连带光线也一致。
- 【实测】Multiple-Angles LoRA 语法：
  `<sks> [方位角] [仰角] [距离]`，方位角如 `front view` / `right side view`，
  仰角 `low-angle shot` / `eye-level shot`，距离 `close-up` / `medium shot` / `wide shot`；
  **`<sks>` 必需**。实测**只擅长方位角**（灰度差 25–37），距离/仰角几乎无感（2.6–6.3），
  所以九宫格应该铺满方位角。

### 7.4 节奏

- 用户口径：**不必 1:1 复刻**，不要求逐帧对齐参考片切点，"整体没有问题"即可。
- 验收优先级：**跨镜一致性 ＞ 镜头语言 ＞ 细节缺陷**。

## 8. 音频：H3 的一半，也是最容易被忽略的一半

### 8.1 能力与边界

- H3 **一次前向同时生成画面和音频**；音频是"对白 ＋ 环境声 ＋ 配乐"混在**一条轨**里。
- 提示词侧的控制字段只有两个：`overall_soundscape`（环境声）和 `non_diegetic_music`（配乐），
  对白写在 `detailed_description` 里用 `<d>[Chinese] …</d>`。
- 输出链路：`VAEDecodeAudio`（音频 VAE）→ `CreateVideo(audio=…)` → `SaveVideo`。
  成品 32kHz 立体声。

### 8.2 三条常见需求怎么做

| 需求 | 做法 |
| --- | --- |
| 只要环境声、不要对白 | **重新渲一遍**：提示词剥掉所有 `<d>` 段，其余照抄。实测 PASS |
| 要换配音 | ① 最省事：整轨替换（丢掉原生环境声）；② 想保环境声：用**独立的纯环境声渲染**当床，不要用音乐分离模型去拆 |
| 只想改语速/音色 | 用 TTS 重配，参考音要挑干净窗口（见第 5 节 #13） |

> 【实测】不要用 `htdemucs` 拆"对白 vs 环境声"：它是为音乐/人声分离训练的，
> 我们那次的结果是**整条混音都留在 `vocals`**，`no_vocals` 比原轨低 28–39 dB，
> 放大 +16…+27 dB 之后只剩底噪。当时的"验证通过"是假阳性——只检查了"没有对白"，
> 没检查"环境声还在不在"。

### 8.3 混音顺序（建议）

1. 先定**基准轨**（哪一版对白是准的）；
2. 对白轨按镜对齐（每镜单独一条，便于微调）；
3. 环境声床来自"H3 纯环境声渲染"，音量压在对白之下；
4. 用 EBU/峰值做校验：参考片人声语音带能量约 70%，TTS 结果落在 67–75% 属正常；
5. **不要叠三层**独立生成的对白（我们试过，听感直接崩）。

---

## 9. 手把手：第一次跑通的最小路径

> 目标：在一台已经装好 ComfyUI + H3 权重的机器上，从零跑出一个 5 秒镜头并验收。

**Step 0　确认机器是活的**

```powershell
.work/run.py probe          # 服务器时间/GPU/显存/磁盘/ComfyUI 队列一次看完
```

看到 8188 有响应、显存基本空闲，再往下走。**一次只跑一个 GPU 任务。**

**Step 1　准备四类输入**

| 输入 | 说明 | 放哪 |
| --- | --- | --- |
| 首帧 | 该镜头的第一帧，**身份的真正来源** | 云端 `ComfyUI/input/` |
| 角色参考 | 首帧里看不清的角度（正脸/侧脸） | 同上 |
| 场景参考 | 空镜或九宫格，**画面里不能有人** | 同上 |
| 提示词 | 六段式，见 Step 3 | 直接填节点 |

上传示例（本机 → 云端）：

```powershell
.work/run.py py .work/make_own_ff_workflows.py --upload
```

**Step 2　打开工作流**

画布文件用 `workflows/video_h3_s0*_*_r2v.json`（能在 ComfyUI 里直接打开、看见连线）。
注意：**API 提交用的 JSON ≠ 可导入画布的工作流 JSON**，两者不要混用。

**Step 3　填提示词（六段骨架，可整段套用）**

```text
subject_definitions:
<Subject 1> is the <场景> in <Picture 1>: <陈设逐项列出>.
<Subject 2> is the <角色A> in <Picture 1> and <Picture 2>: <年龄/脸型/发型/服装>.
<Subject 3> is the <角色B> in <Picture 1>: <年龄/发型/服装>.
<Picture 1> is the first frame of [Shot 1]: <两人站位与朝向>.

summary:
[reference generation + keyframe completion] The target video holds one <景别> shot ... <一两句说清这一镜发生什么>.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - <哪些陈设必须原样保留>.
<Subject 2> (appears in [Shot 1]): fully_preserved - <脸/发型/服装>.
<Subject 3> (appears in [Shot 1]): fully_preserved - <脸/发型/服装>.
<Picture 1> ([Shot 1] first frame): fully_preserved - <开场帧与它一致>.

detailed_description:
The target video is <风格> with <光线>.
[Shot 1] <景别与机位>。 <角色A> (S1) <动作>。 <角色B> (S2) <动作>，用<音色><语速>说，<d>[Chinese] 台词。</d>
<后续动作节拍，按秒推进>。The camera holds still for the whole shot.
No subtitles, captions or on-screen text appear at any point.

overall_soundscape:
<环境声：远处人声、托盘碰撞、布料摩擦、脚步……>

non_diegetic_music:
N/A
```

**Step 4　核对参数**：按第 11.2 节速查表过一遍（1344×768 / length ≥124 / fps 24 /
`res_multistep` + `simple` + 4 步 + turbo LoRA / `ref_image_size=max`）。

**Step 5　跑**

排队后看日志：进度条每步一格，4 步档很快；**中途不要并行开第二个任务**。

**Step 6　取回**

`SaveVideo` 的 `filename_prefix` 决定输出路径；用 API 跑的话：
`tools/run.py`（唯一执行器）会自动下载到 `projects/<项目>/outputs/`。

**Step 7　验收（四查）**

1. **一致性**：把四镜各抽一帧并排看，人和陈设是不是同一套；
2. **镜头**：主角的脸有没有被前景挡住、机位有没有乱动；
3. **缺陷**：有没有烧字幕、品红帧、多手多指；
4. **声音**：逐镜 ASR 核台词（`.work/verify_v12_dialogue.py` 是现成脚本）。

**Step 8　记录**

把 seed、帧数、提示词、参考图清单写回资产卡（`assets/character/CHAR_*.md` 的格式），
否则第二天你自己都不知道这条是怎么出来的。

---

## 10. 主流工作流怎么做

### 10.1 官方教程给了这些路线

ComfyUI 官方文档（`docs.comfy.org/tutorials/video/minimax/*`，每页都带**可下载的模板 JSON**）：

| 页面 | 模板 | 用什么权重 |
| --- | --- | --- |
| 总览 | — | — |
| 原生工作流 | `video_minimax_h3_t2v` / `_i2v` / `_r2v` 三个基础模板 | T2V/I2V 用 **fl2va**；R2V 用 **ref2va**（两套不同权重） |
| 多帧参考 Multiframe | 基于 `MiniMaxH3AddGuide` 的现成工作流 | ref2va |
| Fun ControlNet Union | 姿态/深度/边缘控制 | 另加控制分支 |
| 提示词指南 | — | — |
| FastVideo FastH3 | 4 步加速 | — |

选择顺序建议：**先跑官方原生模板**（证明环境可用）→ 再换自己的输入 →
需要动作控制再上 FunControl → 需要更长/更快再碰长视频与加速节点。

官方文档里的两条"进阶原生技巧"（需要较新的 ComfyUI）：

1. **任意帧锚定 `MiniMaxH3AddGuide`**（PR #15439）：以前关键帧只能锚首尾帧，现在可以在
   **任意帧**上锚一张图或一段片段（含音频），还能串联多个 `AddGuide`。
   多帧批次会被裁到合法片段长度（5 / 22 / 39 … 即 `17k+5`）；
   `frame_idx` 支持负数（从结尾数）。**首尾帧锚定的坐标与旧行为一致，老工作流不受影响。**
2. **latent 噪声遮罩做局部重绘/延长**（PR #15375）：给采样器的 `denoise_mask` 接一个遮罩，
   `0` = 保留原 latent，`1` = 重绘。视频遮罩会对齐到 2×2 latent patch 网格，音频遮罩按整帧对齐。
   可用于局部 inpaint、去物体、或在保持已有内容稳定的前提下延长片段。


### 10.2 多镜连续性：`context_pin` / `MiniMaxH3MotionContext`

公开模板里的做法是**把上一镜的尾部 latent 当作下一镜的上下文**，让相邻镜头在动作和声音上接得住：

| 参数 | 公开模板值 | 节点默认 |
| --- | --- | --- |
| `continuity` | `context_pin` | — |
| `pin_frames` / `context_length` | 22 | 22（可选 22 / 5 / 39 / 56） |
| `pin_noise` | 0.05 | — |
| `pin_renorm` | true | — |
| `master_normalize` | `luma+contrast` | — |
| 分镜分隔 | 独立片段用 `---` 分隔 | — |
| 缓存 | 首跑 `rebuild_cache`，之后 `use_cache` | — |

> 【实测（本仓库 `workflows/H3_PUBLIC_PATTERN_V1.md`）】两片段快速样例跑完 226 帧 ≈ 9.4 秒，
> 日志确认**第 2 段确实收到了第 1 段的 22 帧视频 latent ＋ 22 帧音频 latent**。
> 另一个实测结论：**只给身份参考，画风会漂**；把"具体的场景关键帧"一起接进去，画风才守得住。

### 10.3 两条主流生产路线

| 路线 | 做法 | 优点 | 代价 |
| --- | --- | --- | --- |
| **逐镜生成 + 剪辑**（我们用的） | 每镜单独跑 5–8 秒，最后按节奏拼 | 失败可单镜重跑，成本可控 | 跨镜一致性要靠资产和首帧守 |
| **多镜连续生成** | 用 `context_pin` 串起来，或直接写多 `[Shot N]` | 动作/声音接得顺 | 一镜崩全段崩，重跑贵 |

社区经验是：**"抽卡"应该发生在图片层，不是视频层**——先多出几张图、人挑一张锁定，
再拿这张图去生成视频；而不是在视频层反复抽。锁定 seed 出全片，是多个公开工作流的共同做法。

### 10.4 参考素材的组织（行业约定）

- **槽位顺序固定**：`场景图 → 本场道具图 → 人物定妆图`；
- **空镜纪律**：场景参考图里**严禁出现人物**；
- 角色卡锁定后**不要改**——官方 skill 明确警告：改了会让镜头表、单镜分镜、
  所有单镜视频、成片**全部作废重做**；
- 验收做成**门禁**而不是事后检查：生成前查资产齐套 → 生成中锁参考槽位顺序 →
  生成后多 take 择优分级。

### 10.5 控制与增强（节点生态告诉我们大家在解决什么）

从 241 个 `*T8Advanced` 节点的分布能看出社区的真实需求，按需取用：

| 需求 | 现成节点 |
| --- | --- |
| 动作/深度控制 | `MiniMaxH3FunControlApplyT8Advanced`（`control_kind=depth`、strength 0.7、0.0–0.75 生效区间）、`MiniMaxH3TrajectoryControl*`（轨迹控制） |
| 更长视频 | `MiniMaxH3LongVideo*` 系列（规划、上下文存取、候选验收、颜色匹配、接缝漂移检测） |
| 更清晰 | `MiniMaxH3FlashVSR*`、`MiniMaxH3RealBasicVSRRestore*`、`MiniMaxH3DLSSNR*`（超分/降噪） |
| 人脸/局部修 | `MiniMaxH3FaceRefineWindow*` 系列（窗口化重绘 + 人工复核 + 逐窗提交） |
| 运动体检 | `MiniMaxH3RAFTMotionAuditT8Advanced`（光流幅度、p95、切点计数） |
| 显存/速度 | `MiniMaxH3ResidencyStrategy*`、`MiniMaxLowVRAMAttention`、`MiniMaxH3MemoryEfficientSageAttentionPatch`、`MiniMaxChunkFeedForward` |
| 风险体检 | `MiniMaxH3OfficialRiskDiagnosticT8Advanced`（给出参考素材数、说话人数、隔离音色参考数等，输出风险计数） |

> 一条实用建议：**先用 `MiniMaxH3OfficialRiskDiagnosticT8Advanced` 和 `MiniMaxH3TokenCounter`
> 做体检，再开跑。** 它们便宜，能提前告诉你这组参数是不是要炸。

### 10.6 社区生态速览（数字都是各项目**自报**的，不是独立复现）

来源：官方社区索引 `MiniMax-AI/awesome-minimax-h3-integration`（见 12.1）。

| 你想解决什么 | 社区现成方案 |
| --- | --- |
| 多镜 / 长视频接续 | `ComfyUI-H3-Motion-Context`（把上一段的**末帧和音频**一起往前传，保住运动方向与速度）；`Smite79/MiniMax-H3-LongVideos`（ComfyUI 之外的另一条路）。H3 本身按**最长 15 秒**分块生成 |
| 姿态 / 深度 / 边缘控制 | `alibaba-pai/MiniMax-H3-Fun-Controlnet-Union`（一个约 6.8 GiB 的控制分支覆盖 Canny / Depth / HED / MLSD / Pose / 视频修补）＋ `ComfyUI-H3-FunControl` |
| 分镜 / 时间线模板 | `ComfyUI_MiniMaxH3_Director`（t2v / fl2v / r2v / v2v / rv2v 五个可导入模板） |
| 局部重绘（画面＋声音） | `scraed/LanPaint`（免训练的视频**和音频** inpainting） |
| 角色转身图 / 多视角 | LoRA `minimax-h3-turnaround`：**把 H3 的时间轴当成"格子轴"用**，一张参考图 ＋ 一条指令，一次生成 5 个连续旋转的视角（512² 约 10 秒） |
| 加速 | VDN（混合注意力，自报 2.6–2.9×／步）、Sol-H3（4 步蒸馏，8×B300 上 124 帧 T2VA 中位 1.65 秒）、Spectrum（谱外推跳步）、`ComfyUI-Ref2VA-VSA`（Ref2VA 稀疏注意力）、SolAttn Triton 内核 |
| 极低显存 | 12–16GB 可用 Q4_K_M GGUF / nvfp4 量化＋Q2_K 文本编码器；8GB 走 DiffSynth NF4（慢，靠 offload） |
| 托管版 | **H3 Max / Max Director / Max Turbo**（fal 后训练，**闭源、只有 API**），ComfyUI 里通过 Partner Nodes 调用 |

> ⚠️ 提醒：这些项目**改的、量化的、加速的都不是官方权重**；用之前先确认
> 它要求的 ComfyUI 版本和补丁，以及许可证（索引里明确标了 GPL-3.0 等差异）。

---

## 11. 一页速查表

### 11.1 起手检查（每次开跑前）

1. 显存/队列/磁盘看一眼：`.work/run.py probe`
2. **一次只跑一个 GPU 任务**（H3 吃满显存，和别的任务并行必炸）
3. 参考图上传到云端 `ComfyUI/input/`，文件名和画布 JSON 里写的一致
4. 提示词自检：六段齐？每张参考图都被点名？`<Picture N>` 编号＝连线顺序？风格句在 `[Shot 1]` 前？
5. 画幅 1344×768（7:4）、`length` 是否 ≥124、fps 24
6. 结尾有没有 `No subtitles…` 那句

### 11.2 参数速查

| 项目 | 值 |
| --- | --- |
| 分辨率 | 1344×768（7:4，步长 32） |
| fps | 24 |
| 帧数 | **必须落在 `17k+5` 网格**：5/22/39/56/73/90/107/**124**/141/158/**175**/192/**209**/226…362；不在网格上会被**向上吸附**（我们请求 198 → 实得 209） |
| 采样器 | `res_multistep` |
| 调度器 | 4 步→`simple`；20 步可试 `beta`/`normal` |
| 步数 | 4（预览，配 turbo LoRA）/ 8 / 20（质量） |
| `ref_image_size` | `match`（默认）/ `max`（更强身份、更慢） |
| 参考图 | 0–9（`ref_image_*`） |
| 参考视频 | 0–3（`ref_video_*`），**IMAGE 帧序列、24fps、2–15 秒** |
| 音频 | 32kHz 立体声，对白＋环境声＋配乐同轨 |

### 11.3 出片失败/不好看时的排查顺序

```
画面里脸不对        → 首帧里是谁？换首帧，别加参考图
道具时有时无        → 上 ref_videos（24fps 重抽），别改提示词
画面有字幕          → 加 No subtitles 那句
整帧品红/涂抹       → 调度器从 beta 换回 simple
台词丢了/重复       → 逐镜 ASR 核对，按秒对齐台词与镜头长度
太糊                → 4 步只是预览；换 8/20 步质量档再判
声音不对            → 先确认用哪条轨为准；不要用音乐分离模型拆对白
```

---

## 12. 来源清单

### 12.1 官方（模型与节点）

| 内容 | 链接 |
| --- | --- |
| ComfyUI 官方 H3 教程总入口 | https://docs.comfy.org/tutorials/video/minimax/minimax-h3 |
| ComfyUI 支持 H3 的 day-0 公告（含官方模板说明） | https://blog.comfy.org/p/minimax-h3-day-0-support-in-comfyui |
| 原生工作流 | https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native |
| 多帧参考（Multiframe Reference） | https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe |
| Fun ControlNet Union | https://docs.comfy.org/tutorials/video/minimax/minimax-h3-fun-controlnet |
| 官方提示词指南（ComfyUI 版） | https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide |
| FastVideo FastH3（加速） | https://docs.comfy.org/tutorials/video/minimax/minimax-h3-fastvideo |
| 基础模式提示词指南（HF） | https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md |
| **完整参考模式提示词指南（HF）** | https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md |
| 生态索引（发现用，非质量认证） | https://github.com/MiniMax-AI/awesome-minimax-h3-integration |
| FunControl 作者仓库 | https://github.com/wyzborrero/ComfyUI-H3-FunControl |
| 官方 `h3-prompt-writing` skill | https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing |
| 官方 `3d-animation-short-generator` skill | https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/3d-animation-short-generator |

### 12.2 每条结论的原始出处（**证据文件在旧仓库，不在本仓库**）

> ⚠️ 下表这些文件**本仓库里没有**。它们是上一条产品线的项目记录，按范式（§"只带规矩＋skill＋通用脚本＋小说"）
> 没有带过来。要用就从 GitHub 取：
>
> ```bash
> git clone https://github.com/VicotrZC/MiniMax-H3-Short-Drama.git
> # 或只取一个文件：
> git -C <旧仓库> show HEAD:<路径> > 本地文件
> ```
>
> 所以：**本文的结论可信度分两种** —— 有出处且你能在旧仓库里核到的，是实测；
> 核不到的，按"未经复核的说法"对待，别当既成事实用。

| 文件 | 内容 |
| --- | --- |
| `.work/FINDINGS_v4_v7.md` | 首帧=参考片原帧（逐像素）、身份参考压不过首帧（9 种配置）、4步+beta 品红、烧字幕、TTS 2.0/2.5 混用、duration_factor |
| `.work/FINDINGS_refvideo_道具闪烁.md` | 挂肉闪烁的解法＝`ref_videos`；Multiple-Angles LoRA 语法与局限；"单镜结论不要当全局结论" |
| `.work/FINDINGS_角色身份卡_网络调研.md` | 角色身份卡的主流要素（含 6 个网络来源） |
| `SESSION_2026-09-17_买肉四镜_交接.md` | 当日交接：验收结论、待修问题、服务器/音源分离操作 |
| `START_HERE_MANUAL_COMFYUI.md` | 方法与口径更正（复刻口径、六段式、simple、烧字幕、IndexTTS、pip） |
| `assets/README_资产结构.md` | 资产 SOP：5 视图命名、灰底平光、**全身图必须无头**、后处理与砍头 |
| `workflows/H3_PUBLIC_PATTERN_V1.md` | 另一条公开模板路线（context_pin 22 帧的连续性设置） |
| `research/REPORT-AI叙事视频管线与质量控制.md` | 行业调研：身份锁优先级、参考图槽位顺序、空镜纪律、门禁点（⚠️ 槽位顺序那条已被第 6.2 节更正） |
| `minimax-h3-comfyui-handbook.md`（仓库根目录） | **深度调研汇编**：850 行、逐条附源链接。模型架构与许可证原文、源码级节点语义、13 条音频 issue、多镜头串联实测、放大/插帧、以及明确的"未能证实"清单 |
| `.work/dump_h3_nodes.py` | 从 `/object_info` 导出节点契约的脚本（本文档参数表的来源） |
| `.work/compare_official_r2v.py` | dump 官方 R2V 模板并逐节点对照（§13.10 的来源）；模板 JSON 在 `h3res/` |
| `h3res/`、`_research/h3/` | 一手抓取物：官方 8 个模板 JSON、`nodes_minimax_h3.py` 源码、LICENSE、HF README、LoRA 卡 |
| `h3-comfyui-practice-report.md` | 调研：多镜头、槽位约定（含**否定结论**）、锚定/续写、放大插帧、拼接与 32kHz 同步 |
| `h3_findings_report.md` | 调研：HF discussions 12–60 的用户实测问题（运动/漂移/音频/低步数/显存/LoRA/已知 bug） |

### 12.3 怎么自己复核本文档

```powershell
# 节点与参数（不需要显卡）
.work/run.py py .work/dump_h3_nodes.py --list
.work/run.py py .work/dump_h3_nodes.py MiniMaxH3ReferenceToVideo --md

# 服务器 / GPU / ComfyUI 队列
.work/run.py probe
```

> 规矩：**用工具前先查用法，不要盲试**；**默认不写内联 PowerShell，命令走 `.work/run.py` 参数调用**。
> 这两条是本项目 `agent.md` 的硬约束，血泪换来的。

---

## 13. 深度调研补充

> 本节是把另一份**带逐条来源链接**的深度调研（本仓库根目录
> `minimax-h3-comfyui-handbook.md`，850 行）里最关键、能直接改变做法的部分摘出来。
> 需要原始出处时去那份文件里查对应小节。

### 13.1 ⚠️ 许可证（先看这条，它可能决定项目能不能发）

- 许可：**MiniMax-H3 Community License**；`Excluded Territories` 定义为
  **欧盟、英国、韩国、美国**；`Applicable Territory` = 全世界减去这些地区。
- **§V.4 把限制延伸到 Outputs**：不得在 Applicable Territory 之外使用、复制、修改、分发、展示
  H3 的产物或结果。
- §IV.1：**年营收超过 2000 万美元**需另行取得书面授权；产出归你，MiniMax 不主张权利（§VI.4）；
  管辖法为香港。
- 文本编码器 Qwen3-VL-32B 是 Apache 2.0（与主模型许可不同）。

→ 结论：**如果片子要给排除地域的客户/平台用，先走授权**。这是项目级风险，不是技术问题。
> 另有一条**商业使用**的门槛说法（本地产出商用需 MiniMax 商业许可、只能经 Comfy 获取），
> 但只见于 Comfy 单方文档，见 §13.11.7。

### 13.2 模型到底是什么（架构要点）

- H3 是 Hailuo 线第三代，也是**首个开放权重版本**；系统三模块：
  H3-Context-IR（托管提示词改写，**未开源**）、**H3-Base（开源，768p）**、
  H3-Regenerate-2K（**未开源，仅 API**）。
- 开源两个 checkpoint：**FL2VA**（t2va/fl2va）与 **Ref2VA**（ref2va），BF16、**CFG-distilled**。
- 33B dense single-stream，其中约 13B 在 AdaLN 分支，**推理时可以不加载**。
- 文本编码器 = **Qwen3-VL-32B 第 50 层 hidden state**（不走 chat template），
  参考标签与 **2fps 时间戳视频块**一起进编码器。
- VisualVAE `f16t4d24` ＋ 1×2×2 patchify → **等效 32× 空间压缩**；
  AudioVAE = DAC 编码器 ＋ BigVGAN 解码器，32 kHz 立体声 → **40 Hz latent**。
- 规格：**4–15 秒、24fps、32kHz 立体声、短边 768、11 种语言**。
- Ref2VA 上限：图 ≤9、视频 ≤3（各 2–15s、总 ≤15s）、音频 ≤3、
  **混合文件总数 ≤12**。

### 13.3 节点与参数（源码级，纠正几处常见误解）

| 事实 | 含义 |
| --- | --- |
| **没有独立的 T2V 节点** | `MiniMaxH3ImageToVideo` **不接** first/last frame 就是 T2V |
| `first_frame` 是**几何锚点，直接拉伸**到画布；`last_frame` 保持比例 cover-crop | 首帧比例不对会被拉变形，先做成目标画幅 |
| API 图里参考输入是**点分命名空间**：`ref_images.ref_image_0` | **写裸名 `ref_image_0` 会被静默忽略**——能出片，但等于没引用任何东西 |
| `MiniMaxH3SigmaShift`（显示名 ModelSamplingMiniMaxH3）：`shift_video` 12.0 / `shift_audio` 3.0 | **基础模板不用它**，只有 FastH3 用 —— 别以为它是必调项 |
| turbo 不是核心节点输入，而是 `LoraLoaderModelOnly` ＋ If/Else 开关 | r2v：20 → **4** 步；fl2v：20 → **6** 步（配 8 步 LoRA）。**只看 widget 会误读**（t2v 模板 widget 写 4，实际被链接覆盖成 20） |
| 分辨率：短边 768、面积上限 768×1344 | 官方警告"别填 1.0 MP，会得到 1376×768 超上限"；模板默认 0.4 MP（864×480）用于快速预览，正式档 **0.98 = 1344×768** |
| 本地模板其实有 **8 个**（文档只列 5 个） | t2v / i2v / **i2v_continuation** / r2v / multiframe_reference / fun_controlnet_union / fasth3_t2v / fasth3_i2v |
| **没有 `SaveAudio`** | 音频一律 `VAEDecodeAudio → CreateVideo → SaveVideo` |

### 13.4 参考编号 = **呈现顺序**（presentation order）

① 所有图像按时间线顺序 → `<Picture 1..>`；
② 然后是各视频，**每个视频之前先放它自己声轨的 `<Audio j>`**；
③ 然后是独立音频，沿用同一 `j` 序列。

所以"一个带声视频 ＋ 一个独立音频"的正确写法是：
`<Audio 1>`（视频声轨）→ `<Video 1>` → `<Audio 2>`（独立音频）。

> **搞错不会报错，只会悄悄生成错的视频。** 这是最难自查的一类问题。

### 13.5 音频：两条必须知道的事

1. **音频不是透传，是重新合成。** `fully_copy` 只是"目标"而不是保证——
   每条参考音频都会被编码进 conditioning。**要原声，必须把原声旁路接到
   `CreateVideo` 的 audio 输入。**
2. **"4 步音频失真"是版本条件性的，不是模型缺陷。** ComfyUI 0.30.0 时 stock sampler 把
   音视频两条流放在同一条 schedule 上，4 步会**严重过步进音频**；
   由 kijai 的 **PR #15243（2026-08-06，"Fix sampler issues for audio with minimax"）**
   加入 `ModelSamplingAV` 修复。→ 我们若在旧版本上遇到音频怪，先查这一条。

**已归档的音频 issue（详见深度调研 §4.5）**：麦克风爆音（#15283 / #15614）、
音频支路全死（#15799，VAEDecodeAudio 全 −1.0，SaveVideo 报 `avcodec_send_frame()=22`）、
参考音频被重生成成"伪中文"人声、EasyCache 静默劣化音频（视频 SSIM 几乎不变但音频明显变差，#15326）、
AudioVAE 中心裁剪丢开头 ~266 samples（~8.3ms，#15970）、声音克隆说胡话（#16155）、
多说话人音色串味（#15454）、**API 提交时参考音频/图被静默忽略**（#15667）、
唇同步在 0.35+ 回归（#16387）、画外音提示 8 种写法全部无效（HF discussion 44）、
接缝 dead air（根因是"台词字数不够填满窗口"，不是接缝本身）。

### 13.6 画面质量与稳定性（社区实测，数字是他们自报的）

- **人脸细节有物理上限**：32× 网格下，864×480 的中景里一张脸 ≈ **2 token**、
  一只眼 ≈ **0.3 token**。→ **拍近景，分辨率 ≥1024×576**，别指望全景里的小脸。
- **身份漂移的"纹理棘轮"**：长链续写每接一次约 **+13%** 细纹理。
  **`seed_per_shot` 必须开**——复用同一个 seed 会让脸和声音一起漂。
- **切点不精确**：实测一边界早 1 帧、另一边晚 9 帧；要求 static 的片段照样会推镜；
  "整条变成一个长镜头"是模型行为，不是参数错误。
- **严重 bug（多为单报告，但后果大，值得记住症状）**：
  提示词对输出零影响、同 seed 两条不同 prompt 出**像素完全相同**的结果（#15805）；
  Ref2VA 的**安全长度随参考数塌缩**且失败会报成功（#15738：4090 上 328 帧=RGB 噪声、
  345 帧=静默空白、362 帧=illegal memory access）；
  **每 17 帧一次周期性暗帧**（亮度降约 30，#15426）；
  离网格 latent 解码伪影（#15416）；bf16 出全黑帧而 int8 正常（#15563）。
- **VRAM 与内存**：官方称优化后总占用从 123.6 GB 降到 **42.5 GB**，可跑 RTX 3060；
  但**主机内存才是真正的瓶颈**（4090 采样期常驻显存仅约 6.6 GB；有 3090 运行被内核杀，
  加 `--disable-pinned-memory` 后峰值 7.5 GB、23 分 17 秒跑完）。
- **LoRA 可以加载，也可以训练**（ostris/ai-toolkit 2026-08-03 已支持）——
  **不要写"H3 不支持 LoRA"**。
- 社区警告：**不要安装 `ComfyUI-MiniMaxH3-Cache`**（全局 monkey-patch）。
- ⚠️ 官方 T2V 模板里**预置了一整段示例提示词**（vaporwave），常规 UI 里看不见。
  **用官方模板前先把 prompt 清空。**

### 13.7 两个"无法调和"的冲突（用的时候必须自己 A/B）

1. **scheduler**：官方模板预置 `simple`，但模板自带的 Note 说"参考密集的提示词下
   `beta`/`normal` 往往优于 `simple`"；社区多镜头包用 `euler` + `beta57` 14 步，
   代价是**唇同步 8/10 而不是 10/10**；也有 wiki 说低于约 15 步明显掉质量。
   → **T2V 与 R2V 可能需要不同 scheduler，别把一处的结论搬到另一处。**
2. **SageAttention**：官方说约 2× 加速、质量损失极小；社区说它会破坏 H3 的注意力
   （Sage 2 出纯噪声、Sage 1 掉高频细节），需要 opt-out 补丁，issue #15263 标题即
   "above ~160k tokens on sm_120 会产生噪声"。
   → **画面/音频出怪时，先把 SageAttention 关掉做对照。**

### 13.8 多镜头与后期（社区做法）

- **官方路线 = 一次生成里写多镜头**（`[Shot N] At MM:SS.mmm`，切点严格递增）；
  **但社区压倒性地逐镜生成再串联**。两条串联技术：
  - `first_frame` **帧中继**：上一镜末帧 → 下一镜首帧（走模型训练过的续写路径），
    裁掉重复的边界帧 ＋ 40 ms equal-power 音频焊缝；
  - `context_pin` **原始 latent 锚定**：把上镜最后 **22 帧**按位送进下一镜，
    代价是重生成的 **0.92 秒头部必须裁掉**——**这就是"每个链接镜头开头 1 秒是丢弃重放"的原因。**
- **边界铁律**：每镜以上一镜的确切收尾开场 ＋ 约 2 秒安静；**台词绝不跨镜**；
  **台词 ＋ 4 秒安静必须装进镜头时长**（362 帧≈27 词、243 帧≈15 词、**124 帧不够**）。
- **参考图槽位**：官方**只有**两条规则——"接线顺序 = 呈现顺序"和"给每个参考显式分配职责"。
  **"场景图→道具图→人物定妆图"这套语义槽位约定，在任何官方或社区来源里都查不到**
  （两条独立检索都给出否定结论）。→ 见 §6.2 的更正。
- **放大与插帧**：latent 放大 `MinimaxH3LatentUpscaler3D` ＋ refine（省时间不省显存）；
  解码后用 Lanczos / ESRGAN / SeedVR2；插帧走 RIFE（48/60fps，保持与原生 24fps 音频同步）。
- **拼接**：H3 音频是 **32 kHz**——用硬编码 48000 做 stream-copy 拼接会
  **静默截断长片尾部，而所有时长检查仍然通过**。接缝用 40 ms equal-power。

### 13.9 参考视频到底能"给"什么

- 格式：**IMAGE 帧批次**，24fps、2–15 秒；**少于 5 帧直接抛错**；会被向下裁到 17k+5。
- 社区实测：**可靠携带运动**，但**不携带**颗粒/调色/细质感，而且**它的调色会覆盖提示词的打光**；
  **接了参考视频会让"换脸"完全失效**（换脸要用静帧）。
- ⚠️ `LoadVideo → GetVideoComponents` 这条接线在官方文档、官方模板、社区仓库里
  **都没有明文教程**；官方 R2V 模板只预置了 2 个 `LoadImage`。
  ——**但我们在本机实测这条链路可用**（见第 5 节 #5、`.work/FINDINGS_refvideo_道具闪烁.md`）。

### 13.10 官方 R2V 模板 vs 我们的图（从原始 JSON 逐节点核对）

方法：官方模板 JSON 就在本地 `h3res/video_minimax_h3_r2v.json`，用
`.work/run.py py .work/compare_official_r2v.py` 直接 dump，**不是二手转述**。

**官方 R2V 模板的节点与取值**：

| 环节 | 官方模板 |
| --- | --- |
| 主模型 | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` |
| 文本编码器 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`，type=`minimax` |
| VAE | 视频 `minimax_h3_video_vae_fp16` ＋ 音频 `minimax_h3_audio_vae_fp32`（两个 VAELoader） |
| 推理节点 | `MiniMaxH3ReferenceToVideo`，widgets `[prompt, 1344, 768, 124, "match"]` |
| 参考图 | `ref_images.ref_image_0` / `_1` ← 两个 `LoadImage`（**点分命名空间**） |
| 采样器 | `KSamplerSelect` = **`res_multistep`** |
| 调度器 | `BasicScheduler` = **`simple`，steps = 20，denoise = 1** |
| 引导 | **`BasicGuider`**（没有 CFGGuider、没有 negative、没有 cfg） |
| 分辨率 | `ResolutionSelector`，默认 **0.4 MP = 864×480**（预览档；表里 0.98 → 1344×768） |
| 时长 | `PrimitiveFloat(Duration)` = 5 秒 → `ComfyMathExpression` → `length` |
| 加速 | `LoraLoaderModelOnly`（`ref2v_turbo_4step`）＋ **If/Else 开关**，默认**关**；两个 `PrimitiveInt`：Full=**20**、Lightning=**4** |
| 输出 | `VAEDecode` ＋ `VAEDecodeAudio` → `CreateVideo(24fps, 8bit)` → `SaveVideo` |

**官方换算"秒 → 合法帧数"的表达式（照抄即可，这是网格的官方解法）**：

```
max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17      # a = 想要的秒数
```

代入 a=5：`round(120)` → `120 % 17 = 1` → `(5-1) % 17 = 4` → **124** ✓

**和我们图的差别（只有四处）**：

| 项 | 官方默认 | 我们 | 要不要改 |
| --- | --- | --- | --- |
| 步数 | **20** | 4（turbo LoRA 常开） | **出正式质量时必须改**，4 步只是官方定义的加速档 |
| `ref_image_size` | `match` | `max` | 身份优先保留 `max`，但要知道它更慢、更吃显存 |
| 分辨率 | 0.4 MP（864×480）预览 | 1344×768 | 我们要的是成片规格，保持 |
| 参考图数量 | 2 | 3–4（首帧＋角色＋场景） | 保持，但**每张都要在提示词里点名** |
| 采样器 / 调度器 / Guider | `res_multistep` / `simple` / `BasicGuider` | **完全一致** | ✅ 这点我们本来就对 |

> 一句话：**我们的图和官方模板在结构上是对的，唯一的实质性偏差是"常开 4 步加速"。**
> 这也解释了为什么用户觉得"越做画面越不如前"——我们一直待在最低质量档上做对比。

### 13.11 后期增补与更正（含一条直接影响我们的证据）

#### ⭐ 1. 4 步 turbo LoRA 有**确定性**运动缺陷（最该看的一条）

`invoke-ai/InvokeAI-7` **PR #228（已合并，2026-09-08）**给出一张受控隔离表
（同 seed、同 prompt、6 秒参考尾窗、345 帧 @768×768）：

| 运行 | 结果 |
| --- | --- |
| `ref2v_turbo_4step_v0.1` ＋ 视频&音频参考 | **相机右摇，主体出画** |
| v0.1 ＋ 水平翻转参考 | 仍右摇，幅度较小 |
| v0.1 ＋ 仅视频参考 | 右摇 |
| **不用 LoRA，30 步** | **静态相机，正确** |
| **LightX2V Ref2V 8 步 v1.0** | **静态相机，正确** |

PR 说明 conditioning 路径已逐操作比对 diffusers 0.40.0 与 DiffSynth-Studio 且一致，
**偏差出在 v0.1 蒸馏本身**。→ 可操作结论：

- 用 **`minimax_h3_ref2v_turbo_4step_v0.1`**（**就是我们一直在用的那个**）时，
  要警惕"**相机不受控漂移、主体出画**"，**而且它是无报错的失败**；
- 换成 **8 步 v1.0** 或**干脆不用 LoRA 跑 30 步**即可消除（同 seed 可直接对照）。

**这个缺陷后来修了吗？——没有修 v0.1，只是被绕开。**（2026-09-18 查 `lightx2v/Minimax-h3-Turbo`
仓库文件列表 + 本机 loras 目录，结论如下）

| 观察 | 事实 |
| --- | --- |
| Ref2V 4 步 LoRA 的版本 | **只有 v0.1**（`minimax_h3_ref2v_turbo_4step_v0.1_*`），没有 v0.2 / v1.x |
| 迭代发生在哪条线 | **全在 FL2V**：`fl2v_turbo_4step` 已从 v0.1 → **v1.0 → v1.1 → v1.2**，另有 8step v1.0 |
| Ref2V 的替代品 | 仓库里有 **`minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors`**（约 1.96 GB）——这就是 InvokeAI 换上的那个 |
| 我们机器上有什么 | `/root/autodl-tmp/ComfyUI/models/loras/`：`fl2v_4step_v1.0`、`fl2v_8step_v1.0`、**`ref2v_4step_v0.1`**（有缺陷的那个）；**8 步替代品还没下** |

→ 所以三条路：① 下 8 步 v1.0（约 2 GB）走 8 步；② 不用 LoRA 跑 20–30 步（最稳、最慢）；
③ 继续用 4 步 v0.1，但接受相机漂移风险。
**注意**：8 步 v1.0 "无此问题"目前只有 InvokeAI PR #228 那一份受控对照，属单一来源。

#### 2. 长链上的"对白幻觉"（部分关闭一项未证实）

`ComfyUI-MiniMax-H3-Motion-Director` issue #18：**约 8 段之后（总时长约 1:20）台词退化为
胡言乱语/幻觉**，即使台词很短很简单；视觉连续性仍相对可用；**开新项目、从上段视频续接可重置音频质量**。

> ⚠️ 强度限定：**单一用户、第三方串联节点包、非受控测量**。
> 正确写法是"长链＋音频连续性场景下有用户报告"，**不是**"H3 必定在第 8 段后幻觉"。
> 另外"逐字重复同一句"那种多出对白**仍然没有任何来源**。

#### 3. INT8 注意力量化吃细节（候选解释，**不是**官方结论）

- 症状：**片段末尾变形 ＋ 画面文字乱码**。
- 机制（投稿者说法）：H3 最后几个 block 把注意力 key 信号集中在少数通道，
  按整行共用 scale 舍入的 INT8 kernel 会丢信号。
- 候选缓解：换 **Comfy Kitchen attention**（`Model Attention Backend` 节点或
  `--use-ck-attention`，它在量化前做通道旋转）；备选是把受影响的 block 跑 bf16。
- ⚠️ 出处是 `Comfy-Org/docs` **PR #1698——仍是 open、未合并的社区文档投稿**，
  只能当**旁证/提案**，不能称"官方修复"。另有一条"INT8-convrot 与 Comfy Kitchen
  不兼容崩溃"的说法在该 PR 正文里找不到，**不采信、不采用**。

#### 4. `ref_image_size` 确实有 bug，但不是 OOM

ComfyUI 0.35.0 上会出现
`TypeError: MiniMaxH3ReferenceToVideo.execute() got multiple values for argument 'ref_image_size'`
（自定义节点直接调核心 `execute()` 时触发），同族还有 `...argument 'vae'` 以及
`normalize_guide()` / `build_guide()` 里的 `unsupported operand type(s) for //: 'str' and 'int'`——
属于较广的位置参数/签名冲突。**仍然没有任何把 OOM 归因于它的报告。**

#### 5. 两条小而干净的结论

- **prompt embeddings 按文档正常工作**：`embedding:minimaxh3_art_is_explosion`，随仓库发布 10 个；
  除"纯 T2V 下似乎被忽略"这一条外零失败报告。
- **LoRA 训练支持再获第三个独立确认**（`kohya-ss/musubi-tuner` PR #1106/#1110/#1116）。
  另有反直觉发现：用**蒸馏训练**的人物 LoRA 时，**30 步反而比 6 步更模糊**——
  作者明确警告该结论不可外推。

#### 6. 引用纪律（本轮最重要的一次自我纠错）

深度调研曾把两条**未合并的社区投稿**误述为"官方确认"：

| 被误述为 | 实际状态 |
| --- | --- |
| "ComfyUI PR #15353 官方确认了 shift 12/3 过步进音频" | 作者 `author_association: NONE`，**closed、`merged: false`**；那段话是投稿者本人说明 |
| "官方 docs 记录了 INT8 修复 ＋ Comfy Kitchen" | `Comfy-Org/docs` **PR #1698 仍 open、`merged: null`** |

→ **机制描述与已合并的 PR #15243（音频 schedule 修复）一致，可作旁证；但不能称官方。**
本手册凡写"官方"的地方，都已按此标准复核过。

#### 7. 商业使用的门槛（Comfy 单方声明，待 MiniMax 侧确认）

ComfyUI 官方文档称：**本地生成的产出要做商业使用，需要 MiniMax 商业许可，且只能通过 Comfy
（其自称唯一官方转售方）获取**；Comfy Cloud 上的生成已含商业权利。

> 这条**只出现在 Comfy 的文档里**——在 MiniMax 的 LICENSE 正文中找不到对应条款，
> 也没有 MiniMax 侧的独立确认。**按"Comfy 单方声明"处理**，别当成合同条款引用。

#### 8. 关于"没有证据"这件事

Reddit 与知乎/Bilibili 在本轮**全部路径被封**（403／验证码／超时），所以本手册里
**没有任何 Reddit 一手来源**——这是"抓不到"，不是"不存在"。
另有九类说法在四条独立检索流里**一致返回空**（道具闪烁、音频嘶嘶声、死寂空档、
音乐串进对白、`ref_image_size` 引起的 OOM、Topaz/FILM、48 kHz 时间轴、LUFS 归一化、
剪辑软件时间线设置）。这类"没有"很可能为真，但本手册统一按**"未证实"**而不是"不存在"处理。
