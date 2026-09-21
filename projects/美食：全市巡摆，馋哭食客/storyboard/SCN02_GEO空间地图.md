# SCN-02 · GEO 空间地图（凌晨空街）

> 依据 `pipeline/docs/01_资产规范.md` §2.3。
> **这不是描述，是锁定件**：本文件的中英两块**逐字复制进该场每一个镜头的提示词**，
> 一个字都不许改写。
>
> **为什么本场要单独一份**（用户 2026-09-21 拍板拆场次）：
> 本场是**室外街道**，SCN-01 是**室内猪肉摊**。GEO 是「一个场次一份、一个坐标系」
> （`audit_rules.json` 的 `geo_file`）。摊内那套米数（案台 x −1.5…+1.5 等）
> 与街道的米数**塞不进同一份地图**，硬塞会把已经锁好的摊内几何弄坏。
> → 拆成两个场次，各锁各的。
>
> ⚠️ **本文件是 2026-09-21 新写的，摊内那份（`SCN01_GEO空间地图.md`）一字未动。**

---

## 一、中文版（给人看的，也是分镜表的引用源）

```
GEO SPATIAL LAYOUT（全镜头锁定，纯空间地图）：
— 场地 = 中国某小区外的一条**东西向城市街道**，凌晨四点，全场无行人（远处一名环卫工人）
— 坐标系 = x 向东为正、y 向北为正，**原点 = 街道中心线与小区大门中线的交点**（y = 0 即街心）
— 街道 = 沥青路面，东西向，x −40…+40；**路宽 7.00m**，即 y −3.5…+3.5
— 人行道 = 南北各一条，各宽 2.50m：北侧 y +3.5…+6.0，南侧 y −3.5…−6.0
— 路缘石 = 南北各一道，高 0.15m，在 y = ±3.5
— 小区大门 = 南侧，铁艺门，在 x −1.2…+1.2，y −6.0…−6.6；门内是小区院内（本场不出现在画面里）
— 停车棚 = 南侧人行道上，轻钢棚，x −2.0…+1.0，y −4.0…−5.5，棚内停一排小电驴
— 路灯 = **北侧一道**，臂式，间距 12.00m，杆位 x = −24 / −12 / 0 / +12 / +24，y = +3.6，灯头离地 6.00m
   **南侧没有路灯。** 全场光源只有北侧这一列
— 行道树 = 北侧人行道，间距 12.00m，与路灯交错（x = −18 / −6 / +6 / +18），树干直径 0.25m
— 环卫工人 = 北侧人行道，x +6.0，y +4.6，**面朝西**，推一辆手推垃圾车
— 闫清（C01）：**骑小电驴**，起于小区大门内侧 x −0.6，y −5.6，**向东（+x）行进**；
   行进路线沿南侧人行道外缘，y ≈ −4.2，**全镜只向东走，不回头**
— 小电驴 = 踏板式两轮电动车，车身长约 1.70m；车头小灯是唯一随人移动的光
— 手机 = 闫清右手握持，屏幕亮，屏幕光向上打到他的脸与胸前
— 环境亮度 = 极暗。天空无月无星，天光几乎为零
— 名义光 = **北侧那一列路灯**（色温约 4000K，冷白，光轴垂直向下略偏向北）；
   补光 = 手机屏幕（冷白偏高色温，只照到闫清一个人）
— 全场阴影统一落向正下方并略偏向南（路灯在北），软阴影、无硬边投影；
   只有手机屏照亮的那一块是硬一点的近场光
— **东边天光**：本镜收尾时东侧天际线开始极弱地泛白（承接 SCN-01 的收在天亮）
```

**§2.3 的四条规则，逐条执行**：

| 规则 | 本文件的做法 |
|---|---|
| 方位**只从摄像机出发**（"画面左/画面右"），不写"站在角色左边" | 中文版用**绝对方位**（东/西/南/北）给几何；**相对方位只在英文块里、且以 `frame left/right` 表述** |
| 位置用**地标 ＋ 米数** | 全部写成 `地标 + 米数`（如 `路灯杆位 x = 0，y = +3.6`） |
| **每剪一刀之后，重新写一遍谁站在哪、看向哪** | 见 §三：每镜各给一份（本场目前一镜，仍写） |
| **静态对话戏只给房间的一个角落，不给整个房间** | 本场**不是**对话戏，是一镜到底的过街全景 → 英文块给**街心那一段**（x −4…+8），两侧不给 |

---

## 二、英文版（**直接粘进 H3 六段式的 `detailed_description`**，一字不改）

```
GEOSPATIAL LOCK (identical in every shot of this scene):
— Location: one east-west city street outside a Chinese residential compound, at four in the morning. The street is completely empty of people except for one street sweeper far away.
— Coordinates: x increases to the EAST, y increases to the NORTH. The origin is the point where the midline of the street meets the midline of the compound gate, so y = 0 is the centre of the roadway.
— Roadway: asphalt, running east-west, x −40 to +40. The road is 7.00 m wide, that is y −3.5 to +3.5.
— Pavements: one on each side, 2.50 m wide. North pavement y +3.5 to +6.0, south pavement y −3.5 to −6.0.
— Kerbs: one on each side, 0.15 m high, at y = ±3.5.
— Compound gate: on the SOUTH side, wrought iron, x −1.2 to +1.2, y −6.0 to −6.6. Inside the gate is the compound yard, which never appears in frame.
— Bicycle shelter: on the SOUTH pavement, light steel canopy, x −2.0 to +1.0, y −4.0 to −5.5, with one row of small electric scooters parked under it.
— Street lamps: ONE row only, on the NORTH side, with cantilever arms, 12.00 m apart, poles at x = −24, −12, 0, +12, +24, y = +3.6, lamp heads 6.00 m above the ground. THERE ARE NO LAMPS ON THE SOUTH SIDE. This one row is the only light source on the street.
— Street trees: on the NORTH pavement, 12.00 m apart, alternating with the lamps (x = −18, −6, +6, +18), trunks 0.25 m in diameter.
— The street sweeper: on the NORTH pavement, x +6.0, y +4.6, FACING WEST, pushing one hand cart.
— Yan Qing (C01): RIDING a small electric scooter. He starts just inside the compound gate at x −0.6, y −5.6, and TRAVELS EASTWARD (+x) along the outer edge of the SOUTH pavement at about y −4.2. He only ever moves east and never turns back.
— The scooter: a step-through two-wheel electric scooter about 1.70 m long; its small headlight is the only light that moves with him.
— The phone: held in Yan Qing's right hand, screen lit, throwing its light upward onto his face and chest.
— Ambient level: very dark. No moon, no stars, essentially no skylight.
— Motivated light: the single row of street lamps on the NORTH side (about 4000 K, cool white, axis straight down and very slightly north) is the ONLY light source, plus the phone screen (cool, slightly higher colour temperature, reaching Yan Qing alone).
— Shadows: every shadow falls almost straight down and slightly SOUTH, because the lamps are north of the road. Soft-edged and low in contrast. Only the patch lit by the phone screen has a harder near-field falloff.
— Sky: the eastern skyline is very faintly paling at the end of this shot, carrying the dawn that SCN-01 finishes on.
— Screen direction rule: the compound gate and the bicycle shelter stay on the SOUTH (frame left, away from the camera) side and the street lamps and the street sweeper stay on the NORTH (frame right, toward the camera) side, IN EVERY SHOT. Yan Qing travels only toward the EAST, which is frame right. No second rider, no pedestrian, and no vehicle ever enters the frame, and no figure is ever duplicated.
```

---

## 三、每镜各写一遍（§2.3：**每剪一刀之后重新写一遍谁站在哪、看向哪**）

| 镜 | 戏在哪里（节拍） | 闫清 站在哪／看向哪 | 环卫工人 | 机位 | 帧数 |
|---|---|---|---|---|---|
| **S00** | B1｜四点，空街 | 骑小电驴，自小区大门 x −0.6, y −5.6 向东行进至 y ≈ −4.2，看前方（+x） | x +6.0, y +4.6，面朝西，背对行进方向 | CAM0：x −0.15, y −3.2，朝北（与 SCN-01 的 CAM1 同位同向），24mm，距 4.0m，可见宽 6.00m | 175 |

**帧数**落在 H3 的 `17k+5` 网格上（175 = 17×10+5）。

> ⚠️ **CAM0 与 SCN-01 的 CAM1 是同一个位置与朝向**（`x −0.15, y −3.2`，朝北）。
> 这是有意的：**两场要能接得上**。区别只在焦段（24mm 全景 vs 35mm 中景）
> 与场地（街心 vs 摊前）。
>
> ⚠️ **7.29 秒要装两个画面**（手机闹钟 04:00 ＋ 骑小电驴出门）。
> 用户 2026-09-21 定「就一个镜头，出首帧我看」—— **看过首帧再判断装不装得下**，
> 装不下就拆镜或加长（加长到 192 帧仍在网格上）。

---

## 四、这套东西怎么用（三步，缺一不可）

1. **文字**：本文件 §二 的英文块 → **逐字**贴进本场每条 H3 提示词的 `detailed_description` 开头
2. **取景**：本镜先用 t2i/edit 出首帧，**景别与机位在首帧里就定死**
3. **核对**：首帧出来之后，回来核 §三 那张表里的 x/y 米数是否真的落在画面里

> ⚠️ **本场还没有 `plan/cams` 图纸。** SCN-01 有
> `assets/SCN/SCN-01_plan.png` 与 `SCN-01_cams.png`（由 `tools/draw_plan.py` ＋
> `SCN01_猪肉摊_plan_spec.json` 生成）。本场的米数**只在上面这段文字里**，
> 没有第二份可核对的图纸。**这是本场目前的一处已知缺口。**

---

## 五、还没做的

| # | 事项 | 说明 |
|---|---|---|
| 1 | **S00 的首帧** | 用户已定「出一个给我看」 |
| 2 | **S00 的 H3 六段式提示词** | `detailed_description` 里必须含本文件 §二 的英文块 |
| 3 | **plan/cams 图纸** | 见 §四末。文字锁了，图纸没做 |
| 4 | **音频核验** | 连着几轮欠着：只验过流参数，**没有人听过** |
