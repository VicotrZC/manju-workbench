# skill-for-video

> AIGC 分镜提示词工作流：以导演视角锁定「风格/光线/角色/场景/画质」五段，逐镜输出图片+视频双提示词；支持「直接出」与「导演模式」，可封装为可复用风格 skill。

## 这是什么

`skill-for-video` 是一个面向 AI 视频创作的分镜提示词生成 skill。它扮演「专业电影导演 + AIGC 提示词工程师」，先把**风格、光线、角色、场景、画质**五段底层提示词锁定、全片逐字复用，再逐镜产出 **图片提示词 + 视频提示词**两段，并落实最小颗粒度的镜头语言（景别/景深/机位角度/对焦/前景/遮挡/景深关系/视点/视角语义/视角连续性/反向限制/时长/timecode），保证全片风格与光线一致。

## 特性

- **两种模式**：直接出（一次性自主完成）/ 导演模式（剧情→风格→时长→方案→五段锁定→逐镜细节逐步确认）
- **五段锁定**：风格（六维：名称参考/色彩/笔触/构图/强度/影调）、光线（光影命名 + 动机光源 + 场景绝对方位 + 阴影方向）、角色、场景、画质——锁定后逐字不变
- **一致性三件套**：光线基准帧 + 角色参考图 + 固定 seed
- **可封装**：把成果封装为可复用的「{风格}-{视频风格}」skill

## 安装

把本仓库克隆或复制到你的 skill 目录（保持 `SKILL.md` 与 `references/` 的相对结构不变）：

- DeepSeek Harness：`.agents/skills/skill-for-video/`
- Claude Code：`~/.claude/skills/skill-for-video/`
- Codex：`~/.codex/skills/` 或项目内 `.codex/skills/`

## 使用

在支持 slash 命令的 agent 里输入：

```
/skill-for-video 雨夜霓虹下的赛博朋克少女独行
```

或直接说明主题，并可选加「直出」或「导演模式」指定交互方式。

## 文件结构

- `SKILL.md` — skill 主文件（完整工作流定义）
- `references/style-map.md` — 风格→光线/画质/镜头倾向映射表
- `references/lighting-library.md` — 经典光影风格库
- `references/backend-capability-matrix.md` — 各出图后端能力与降级矩阵
- `references/camera-emotion-map.md` — 机位/运镜→触发条件→情绪效果映射表
- `references/emotion-library.md` — 情绪词库（情绪→技法反向入口）
- `references/examples.md` — 扩展示例（大场面、光影对照等）
