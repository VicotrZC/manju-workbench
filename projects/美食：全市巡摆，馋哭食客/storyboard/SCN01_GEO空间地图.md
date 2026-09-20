# SCN-01 · GEO 空间地图（凌晨猪肉摊）

> 依据 `pipeline/docs/01_资产规范.md` §2.3。
> **这不是描述，是锁定件**：本文件的中英两块**逐字复制进该场每一个镜头的提示词**，
> 一个字都不许改写。`plan/cams` 图纸与它对的是同一套米数。
>
> **为什么需要它**（用户 2026-09-21 问「场景部分角度不一致，你后期调整吗」）：
> **后期调不了**。跨镜几何一致靠三样：**这张文字块** ＋ `SCN-01_plan/cams.png`（米数与角度）
> ＋ **每个镜头的首帧**（取景写死在首帧里）。九宫格只管陈设，不管取景。

---

## 一、中文版（给人看的，也是分镜表的引用源）

```
GEO SPATIAL LAYOUT（全镜头锁定，纯空间地图）：
— 场地 = 中国室内菜市场的一个猪肉摊位，摊位在市场通道北侧、面向南（南＝观众/通道方向）
— 坐标系 = x 向东为正、y 向北为正，原点在案台西端与南沿的交点附近
— 案台 = 白瓷砖长条案台，横置，x −1.5…+1.5，y 0…0.8（长 3.00m、进深 0.80m、高 0.90m）
— 案台后墙 = 浅色瓷砖墙，x −1.8…+1.8，y 1.5…1.7
— 木门 = 深色，在瓷砖墙正中，x −0.5…+0.5
— 东西两侧隔墙 = 各 0.20m 厚，x ±1.6…±1.8，y 0…1.5
— 红肠串 = 挂在东侧隔墙上，锚点 A4（x +1.7, y +1.0）
— 五盏红伞吊灯 = 案台正上方 y +0.4 一列，x −1.4/−0.7/0/+0.7/+1.4，离地 2.40m
— 案台下 = 白色泡沫箱（A5，x −1.9）、蓝塑料筐（A6，x +0.75）、白塑料桶（A7，x +1.9）
— 地面 = 湿水磨石，全场漫反射
— 市场通道 = y < 0，宽约 3.5m；通道对面另有一排摊位，y −4.5…−3.6
— 锚点 A1 = 案台西端，A2 = 案台东端，A3 = 木门中线，A8 = 吊灯排中线
— 闫清（C01）：案台南侧，x −0.6，y −0.9，面朝北（+y）
— 摊主（C04）：案台北侧，x +0.35，y +1.15，面朝南（−y）
— 180° 轴线 = 两人视线连线，A 侧在东南、B 侧在西北；**摄像机永远停在 A 侧，绝不越线**
— 名义光 = 五盏红伞吊灯（色温约 3000K，光轴垂直向下略偏南）；
  补光 = 通道方向的公共照明与入口天光（约 5000K，冷调，强度低于主光）；
  全场阴影统一落向正下方并略偏向摊位内侧，软阴影、无硬边投影
```

**§2.3 的四条规则，逐条执行**：

| 规则 | 本文件的做法 |
|---|---|
| 方位**只从摄像机出发**（"画面左/画面右"），不写"站在角色左边" | 中文版用**绝对方位**（东/西/南/北）给几何；**相对方位只在英文块里、且以 `frame left/right` 表述** |
| 位置用**地标 ＋ 米数** | 全部写成 `锚点 + 米数`（如 `A2 案台东端，x +1.5`） |
| **每剪一刀之后，重新写一遍谁站在哪、看向哪** | 见 §三：每镜各给一份 |
| **静态对话戏只给房间的一个角落，不给整个房间** | 本场就是静态对话戏 → 英文块**只锁案台这一段**，通道对面那排摊位只在远景镜里出现 |

---

## 二、英文版（**直接粘进 H3 六段式的 `detailed_description`**，一字不改）

```
GEOSPATIAL LOCK (identical in every shot of this scene):
— Location: a pork stall inside an indoor Chinese wet market. The stall sits on the NORTH side of the market aisle and FACES SOUTH, toward the aisle and the camera.
— Coordinates: x increases to the EAST, y increases to the NORTH.
— Counter: one long white-tiled counter lying east-west, x −1.5 to +1.5, y 0 to +0.8 (3.00 m long, 0.80 m deep, 0.90 m high).
— Back wall: pale tiled, x −1.8 to +1.8, y +1.5 to +1.7, with one dark wooden door centred at x 0.
— Side piers: 0.20 m thick each, at x ±1.6 to ±1.8, y 0 to +1.5.
— Sausages: one long string of red sausages hangs on the EAST pier (anchor A4, x +1.7, y +1.0).
— Lamps: five red umbrella-shaped pendant lamps in one row above the counter at y +0.4, at x −1.4, −0.7, 0, +0.7, +1.4, all 2.40 m above the floor.
— Under the counter: a white foam box (A5, x −1.9), a blue plastic crate (A6, x +0.75), a white plastic bucket (A7, x +1.9).
— Floor: wet terrazzo with a soft sheen.
— Aisle: y < 0, about 3.5 m wide. A row of other stalls stands opposite, y −4.5 to −3.6.
— Anchors: A1 = west end of the counter, A2 = east end of the counter, A3 = centre of the wooden door, A8 = centre line of the lamp row.
— Yan Qing (C01): SOUTH of the counter, x −0.6, y −0.9, FACING NORTH (+y).
— The butcher (C04): NORTH of the counter, x +0.35, y +1.15, FACING SOUTH (−y).
— 180-degree axis: the line joining the two men's eyes. Side A lies to the SOUTH-EAST of it, side B to the NORTH-WEST. THE CAMERA STAYS ON SIDE A AT ALL TIMES AND NEVER CROSSES THE AXIS.
— Motivated light: the five red pendant lamps (about 3000 K, axis straight down and very slightly south) are the stall's ONLY light source; the aisle behind Yan Qing adds a faint cool spill (about 5000 K) at much lower intensity. Every shadow falls almost straight down and slightly toward the back of the stall, soft-edged and low in contrast. No unmotivated light, no rim light, no lens flare.
— Screen direction rule: the butcher stays on the EAST (frame right) side behind the counter and Yan Qing stays on the WEST (frame left) side in front of it, IN EVERY SHOT. The two men never swap sides, never cross the counter, and neither man is ever duplicated or appears twice anywhere in the frame.
```

---

## 三、每镜各写一遍（§2.3：**每剪一刀之后重新写一遍谁站在哪、看向哪**）

四镜都还没做，下面是**按 `EP02_SC01_菜市场买肉_戏.md` 的戏剧节拍预先分配**，
真正写 H3 提示词时**以那一镜的首帧为准再核一遍**。

| 镜 | 戏在哪里（节拍） | C01 站在哪／看向哪 | C04 站在哪／看向哪 | 机位 | 帧数 |
|---|---|---|---|---|---|
| **S01** | B1–B2｜开价 | 案台南侧 x −0.6, y −0.9，面前倾，看案台上的肉 | 案台北侧 x +0.35, y +1.15，双臂撑台面，看 C01 | CAM1：x −0.15, y −3.2，朝北（yaw 90），35mm，距 3.5m，可见宽 3.60m | 175 |
| **S02** | B3｜黑猪肉 | 同上，前倾更多，视线沿案台自西向东扫 | 同上，抬下巴、比手势说"你闻闻" | CAM2：x 0.0, y −2.2，朝北，50mm，距 2.6m，可见宽 1.87m | 158 |
| **S03** | **B4｜屠宰场视频（★ 承重笑点）** | 直起身，凑近手机屏幕 | 右手从裤兜掏出手机、把屏幕转向 C01 | CAM3：x 0.0, y −1.0，朝北，85mm，距 1.4m，可见宽 0.59m（大特写） | 192 |
| **S04** | B5｜五十斤 | 点头，手插裤兜 | 抄起砍刀，侧身去卸挂着的肉 | CAM1（回到 35mm 中景）x −0.15, y −3.2，朝北，35mm，距 3.5m | 175 |

**帧数**全部落在 H3 的 `17k+5` 网格上（175 = 17×10+5、158 = 17×9+5、192 = 17×11+5）。
**合计 700 帧 ＝ 29.17 秒**。

> ⚠️ **S03 的"大特写"必须在首帧里做出来。** 旧线的实测：`H3 把 <Picture 1> 当"起点附近的状态"，
> 但首帧的景别与机位基本被沿用`，而且**提示词构图与首帧不一致时 H3 会真的移动机位、
> 并在背景留下一个"重复的人"**。所以 S03 的首帧就要是手机屏幕的大特写（85mm/1.4m 的构图），
> 不能指望在 H3 提示词里改景别。

---

## 四、这套东西怎么用（三步，缺一不可）

1. **代码/图纸**：`tools/draw_plan.py` ＋ `storyboard/SCN01_猪肉摊_plan_spec.json`
   → `assets/SCN/SCN-01_plan.png`、`SCN-01_cams.png`（米数与角度）
2. **文字**：本文件 §二 的英文块 → **逐字**贴进每条 H3 提示词的 `detailed_description` 开头
3. **取景**：每个镜头先用 t2i/edit 出首帧，**景别与机位在首帧里就定死**

> **九宫格（`SCN-01_9grid.png`）是第四件，且只排第四**：它管"陈设与布局"，
> 旧线对它的定义原文是 `does not dictate the framing of [Shot 1]`。
> 本项目实测两版九宫格**九个角度没真正拉开**（6 格近乎正面），
> 所以**不能拿它当跨镜几何的主要依据**。

---

## 五、还没做的

| # | 事项 | 说明 |
|---|---|---|
| 1 | 四镜的**首帧** | 每镜一张，景别写死在首帧里 |
| 2 | 四镜的 **H3 六段式提示词** | `detailed_description` 里必须含本文件 §二 的英文块 |
| 3 | **音频核验** | 连着几轮欠着：只验过流参数，**没有人听过** |
