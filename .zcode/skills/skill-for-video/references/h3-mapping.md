# 把本 skill 的镜头清单落到 MiniMax H3 上

> **本文件由本项目自写，不属于上游 skill 内容。**
> 上游 skill 的默认出图后端是 Midjourney / 即梦 / SD 那一路（静态图 + 首尾帧），
> 而我们的后端是 **MiniMax H3（Ref2VA）**：一次前向同时出画面和声音，提示词有固定六段。
> 所以**不要照搬它的输出格式**，按下面的对照表翻译。

## 1. 五段锁定 → H3 六段提示词

| skill 的段 | 落到 H3 哪里 | 注意 |
| --- | --- | --- |
| **风格段**（风格六维） | `[Shot 1]` **之前**的一两句英文风格句 | 【官方】完整参考模式的风格句必须在 `[Shot 1]` 之前；T2VA 才写在之后 |
| **光线段**（光影命名 ＋ 动机光源 ＋ 光源方位 ＋ 阴影方向 ＋ 色温/影调） | `detailed_description` 里**每个镜头**的环境与光线描写 | 【官方】官方明确要求逐镜交代 environment and lighting。光源方位要写**场景绝对方位**，不要写"画面左侧" |
| **角色段** | `subject_definitions` 里的 `<Subject N>` 定义 | 每个角色一条；身份靠 `<Subject N>` 承载，不要在别处另开 `<Picture N>` |
| **场景段** | 同上，作为独立的 `<Subject N>` | 空镜来源图里**不能有人物**，否则人物参考被污染 |
| **画质段**（渲染质感词库） | 并入 `[Shot 1]` 之前那句风格句 | 与风格段合并成一句，不要拆成第二条 |
| **光线基准帧** | **就是我们的 H3 首帧** | 一图两用：既是像素锚点，也是身份锚点。见 §3 |

## 2. 逐镜镜头语言 → `detailed_description` 的镜头句

skill 要求每镜写全的一串字段，翻译成英文镜头句写进 `detailed_description`：

| skill 字段 | H3 提示词里怎么写 |
| --- | --- |
| 景别 | `a medium two-shot` / `a close-up of …`（词表见 `docs/镜头编码表_H3用.md`） |
| 景深 | `shallow depth of field, background softly blurred` |
| 机位四维（俯仰/方位/高度/横滚） | `a low-angle, three-quarter-front view from chest height, level horizon` |
| 对焦 | `focus on <Subject 2>` |
| 前景类型 / 遮挡 | `the hanging pork sits in the foreground, out of focus` —— **但主角的脸不许被挡**（我们踩过：S02 那块肉挡了 8 秒，最后靠改调度解决） |
| 景深关系 | `the foreground soft, the subject sharp, the background falling off` |
| 视点 / 视角语义 | `objective third-person view` / `the shot becomes <Subject 3>'s POV` |
| **视角连续性（不跳轴）** | 写成显式的空间关系：`<Subject 3> stays on the left, <Subject 2> on the right, across the counter` —— H3 没有轴线概念，**只能靠这句话把左右关系钉住** |
| 时长 / timecode | 落到 H3 的**帧数网格**（`17k+5`：124/141/158/175/192/209…），24fps |
| 反向限制 | ⚠️ **不能直接抄**，见 §4 |

## 3. 一致性三件套 → 我们的三件套

| skill 的三件套 | 我们的做法 |
| --- | --- |
| 光线基准帧 | H3 **首帧**（自己生成，Qwen-Image-Edit 或 T2I） |
| 角色参考图 | `ref_images` 里的角色卡（但记住：**参考图压不过首帧里已有的脸**） |
| 固定 seed | H3 的 `RandomNoise` seed；**逐镜独立 seed**，不要全片同一个（复用同 seed 会让脸和声音一起漂） |

## 4. ⚠️ 三处不要照搬

1. **反向限制（负面词）不能照抄。**
   H3 是 **CFG-distilled**，采样走 `BasicGuider`，**没有 negative 输入、没有 CFG**。
   把"避免文字/避免塑料皮肤"写进去，等于**在提示词里点名这些概念**，可能反而把它们招来
   （和我们踩过的坑一致：正向里写"没有雀斑"会招来雀斑）。
   → 要排除的东西写成**肯定式**：不写 `no plastic skin`，而写 `matte skin with visible pores`；
   字幕就走官方那句 `No subtitles, captions or on-screen text appear at any point.`（这句实测有效）。
2. **"工具档位对齐"换成"帧网格对齐"。**
   它假设目标工具是 3s/5s/10s 整数档；我们是 **24fps、帧数必须落在 `17k+5`**，
   否则会被**向上吸附**（我们请求 198 帧实得 209 帧 = 8.71s，就是这么来的）。
3. **它的分镜图提示词（MJ/SD 语法）我们用不上。**
   我们不需要给每个镜头写出图提示词——首帧由 Qwen-Image-Edit 生成，之后 H3 直接吃首帧。

## 5. 建议的使用姿势

1. 用本 skill 跑到**第 5 步（五段锁定）**为止，拿到：风格段 / 光线段 / 角色段 / 场景段 / 画质段；
2. 按 §1 把它们翻译进 H3 的六段式；
3. 用 `docs/镜头编码表_H3用.md` 给每一镜打上 `Z?-Y?-X?-F?` 编码，再翻成英文镜头句；
4. 帧数按 `17k+5` 选，台词＋环境声按**真实秒数**排（台词 ＋ 约 4 秒安静要能装进这一镜）；
5. 出片后按我们的四查验收：**一致性 → 镜头（脸有没有被挡）→ 缺陷 → 声音**。
