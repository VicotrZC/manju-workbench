# source/ —— 原著（**只读**）

## 这是什么

**《美食：全市巡摆，馋哭食客》**，共 50 章，在 `originals/`。`index.json` 是章节索引。

**这一层只读。** 改编、删改、合并都发生在 `story/` 和 `script/`，不要动原文
（`规矩.md` §1 的单向依赖：`source → story → script → storyboard → prompts`）。

## 参考片（**不在仓库里**）

复刻用的参考片是 `mmexport1789479809107.mp4`，**没有入库**（视频文件，`.gitignore` 排除）。
它当时放在**旧仓库**的位置：

```
<旧仓库根>/references/videos/mmexport1789479809107.mp4
```

旧仓库：`https://github.com/VicotrZC/MiniMax-H3-Short-Drama`

**为什么留它**：身份基准（`assets/CHR/FILM/`）是从这部片子逐帧裁出来的、**未经任何生成**，
所以身份不可能漂移。而参考图**不可确定性重出**，规矩要求必须单独搬。

**要用时**：从旧仓库或在本地找那份 mp4，放到本项目的 `assets/reference/`（不进 git）。

## 买肉那一场（我们测过的镜头）

`买肉.txt`（在旧仓库 `projects/买肉/source/`）是**第 2 章「新鲜的二师兄」那一场戏的改写节选**，
当时用来测试四镜。它不是独立作品 —— **它属于本项目的一个镜头**。
