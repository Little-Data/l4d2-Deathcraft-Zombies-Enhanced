# skin_tool.py 使用说明

一个单文件、独立的皮肤工具：图片 ↔ VTF、换模型皮肤、做变体、渲染预览、
自检、打包/解包 VPK，全部由这一个脚本自己完成，**不调用、也不依赖任何其它工具**。

---

## 0. 准备

- 需要 **Python 3**（安装时勾选 “Add python to PATH”）
- 安装两个库（只需一次）：

```powershell
pip install pillow numpy
```

- 在脚本所在目录打开 PowerShell 执行下面的命令（脚本也可以用绝对路径调用）。
- 工具默认操作**同级目录**下的 `Deathcraft Zombies Enhanced` 文件夹；放在别处时用
  `--mod "路径"` 指定。

> 屏幕输出是英文：中文 Windows 控制台默认 GBK，输出中文容易变乱码。

---

## 1. 三条最常用的命令

### ① 把某只僵尸换成另一张**已有**皮肤

```powershell
python skin_tool.py assign common_male01 shirt10zom
```

### ② 把一张**自己的图**做成新皮肤

```powershell
python skin_tool.py newskin 我的僵尸.png my_zombie
```

- 图片建议 **64×32**（经典 Minecraft 皮肤尺寸）或它的整数倍；
- 工具会：最近邻放大到 ≥512 宽（保持像素锐利）→ 生成完整 mipmap →
  编码成 **DXT5**（无透明时自动用 DXT1）→ 顺便生成同名 `.vmt`。

然后挂到模型上：

```powershell
python skin_tool.py assign common_male01 my_zombie
```

### ③ 改完打包 + 安装

```powershell
python skin_tool.py check     # 先自检
python skin_tool.py pack      # 生成 VPK
python skin_tool.py install "E:\Software\Steam\steamapps\common\Left 4 Dead 2\left4dead2\addons"
```

### ④ 批量转换一整个文件夹

```powershell
python skin_tool.py batch D:\我的皮肤
```

- 递归读取文件夹里所有图片（png/tga/bmp/jpg/webp/gif），逐张转成 VTF；
- 不给输出目录 → 直接写进 mod 的 `materials\models\infected\zombie\`；
- 给输出目录 → 在它下面生成**标准 materials 结构**，可以直接打包：

```
<输出根目录>\
└─ materials\
   └─ models\
      └─ infected\
         └─ zombie\
            ├─ 皮肤A.vtf
            ├─ 皮肤A.vmt
            ├─ 皮肤B.vtf
            └─ 皮肤B.vmt
```

- 文件名即皮肤名：中文/特殊字符会被替换，替换结果记在同目录的 `_renamed.txt`；
  重名的自动加 `_2`、`_3`。
- 常用选项：`--overwrite` 覆盖已有文件、`--dry-run` 只预览不写盘、
  `--no-vmt` 不生成材质、`--flat` 不建 materials 目录、`--size 512`、`--format dxt5|dxt1|auto`。

批量反向导出（看了再改）：

```powershell
python skin_tool.py export D:\皮肤备份 --used-only
```

> **“不会自动挂到模型上”是什么意思？**
> 模型里存的是一个“材质名”（例如 `blockdude`），它只认名字。
> `batch` 只是把图片变成 `<名字>.vtf` + `<名字>.vmt` 放进材质目录，
> **但没有改任何模型**，所以此时这些皮肤是“躺在文件夹里没人用”的状态，
> `check` 会提示 `skin xxx is not used by any model`。
> 要真正用上，用 `attach` 一次挂完，或者逐个 `assign` / `copy-model`：
> ```powershell
> python skin_tool.py attach                       # 所有未使用的皮肤 → 各建一个变体
> python skin_tool.py attach --weight 6            # 同上，刷出概率 6%
> python skin_tool.py attach --replace             # 不建变体，直接替换基础模型的皮肤
> python skin_tool.py attach skin_a skin_b         # 只挂指定的几张
> python skin_tool.py attach --dry-run             # 先看它会怎么挂
> ```
> **`attach` 怎么选模型**：皮肤如果画了头盔层（右上角那块），就复制一个
> 288 顶点（带头盔箱）的模型；否则复制 264 顶点的模型。基础模型按“刷新表里
> 出现次数最多”的顺序轮着用，所以变体在大多数地图都能刷到；同时会自动写进
> `population*.txt`，概率默认 4%。
> 如果导入的皮肤名和某个已有材质**同名**，那它会被直接覆盖使用（这种情况等于
> 自动生效），所以批量导入时更推荐用新名字。

---

## 2. 命令一览

`--mod` 既可以写在命令前，也可以写在命令后。

| 命令 | 作用 |
|---|---|
| `list` | 列出所有模型，以及每个模型当前用的皮肤（`normal` / `special`） |
| `skins` | 列出所有皮肤文件、尺寸、格式、是否缺 VMT |
| `png2vtf <图片> <名字>` | 图片 → VTF（+ 自动补 VMT） |
| `newskin <图片> <名字>` | 同上（别名） |
| **`batch <图片目录> [输出根目录]`** | **批量转换整个文件夹，输出标准 materials 目录结构** |
| `vtf2png <名字> [输出.png]` | 把皮肤导出成 PNG 查看/修改 |
| **`export [输出目录]`** | **批量把 mod 里所有皮肤导出成 PNG** |
| **`attach [皮肤...] [--weight 4] [--replace]`** | **把所有没挂上模型的皮肤一次性挂上（批量 assign / 批量变体）** |
| `assign <模型> <皮肤> [--force]` | 改模型用的皮肤 |
| `copy-model <源模型> <新模型> <皮肤> [--weight 4]` | 复制模型做**新变体**，并自动写进刷新表 |
| `preview <模型> [输出.png] [--width 400 --height 500 --yaw 55]` | 软件渲染预览图 |
| `check` | 自检（贴图/材质/刷新表/`.phy`/特殊皮肤是否串到普通） |
| `pack [输出.vpk]` | 打包 |
| `install <addons目录> [vpk]` | 把 VPK 复制进游戏 addons |
| `extract <vpk> [目录]` | 解包 VPK |

常用参数：

| 参数 | 说明 |
|---|---|
| `--size 512` | `png2vtf/newskin` 的最小宽度，默认 512（小于就整数倍放大） |
| `--force` | `assign` 时即使皮肤文件不存在也写入 |
| `--weight 4` | `copy-model` 时新变体在刷新表里的百分比 |
| `--mod <目录>` | 操作其它 mod 目录 |

---

## 3. 皮肤规格

| 项目 | 要求 |
|---|---|
| 尺寸 | **64×32**（推荐），或 128×64 / 256×128 / 512×256；工具会整数倍放大到 ≥512 宽 |
| 布局 | 标准 Minecraft 皮肤布局（头部左上、身体中上、右臂、右腿），**不要自己重排 UV** |
| 格式 | 有透明 → DXT5（8 位 alpha）；完全不透明 → DXT1；都带完整 mipmap |
| 透明 | PNG 的 alpha 会完整保留（见下） |
| 文件名 | 只用英文/数字/下划线/空格，不要中文和括号 |
| 放置位置 | 工具自动写到 mod 的 `materials\models\infected\zombie\` |

**关于透明通道**

- 导入：只要图片里有一个像素的 alpha < 255，`auto` 就会选 **DXT5**，
  写入 8 位 alpha（VTF flags `0x2000`）。实测 0 / 40 / 128 / 255 四档
  alpha 往返误差为 **0**。
- 只有手动指定 `--format dxt1` 才会丢 alpha（DXT1 没有 alpha），
  工具现在会在这种情况下打印警告。
- 导出：`vtf2png` / `export` 写出的都是 **RGBA PNG**（实测 512×256、
  alpha 0–255、透明像素数量与原图一致）。
- 游戏表现：材质默认是 `$alphatest 1`，所以 alpha 是**硬边镂空**
  （>0.5 显示、<0.5 完全透明），半透明渐变不会被渲染成半透明。
  想要真正的半透明，把该皮肤 `.vmt` 里的 `$alphatest 1` 改成 `$translucent 1`
  （注意透明物体排序问题，一般不推荐用在人物身上）。

**为什么建议 64×32？**
模型每个面只用到皮肤的一小块，64×32 就是原生尺寸；放大到 512 宽是为了让 DXT
的 4×4 压缩块和像素格对齐，近看边缘才锐利（不放大直接压会糊）。

---

## 4. 模型 / 皮肤 / 刷新的关系

```
population*.txt   决定某张地图刷哪些模型、各占多少 %
      ↓
common_xxx.mdl    模型（形状 + 内部记着一个"材质名"）
      ↓
common_xxx.vmt    材质（指向一张贴图）
      ↓
xxx.vtf           皮肤图片
```

- **换皮肤**只改 `.mdl` 里的材质名（`assign` 做的就是这个），模型形状不变。
- **换刷新概率**改 `scripts\population*.txt` 里的数字（每段合计 100）。
- **加新外观**用 `copy-model`：复制模型 → 改内部名 → 换皮肤 → 自动加进刷新表。

---

## 5. `check` 会检查什么

1. 每个模型都有材质，且 `.vmt` / `.vtf` 都存在；
2. `.mdl` 的 `length` 字段和文件大小一致（手改坏了会报）；
3. 有没有"特殊感染者的皮肤被普通感染者用了"；
4. 有没有皮肤文件完全没被使用；
5. 有没有多余的 `.phy`（会害死布娃娃）；
6. `population*.txt` 每段是否合计 100、有没有引用不存在的模型。

全部通过会打印 `all checks passed`。

---

## 6. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `python` 不是内部或外部命令 | 安装 Python 时没勾 PATH，重装并勾选 |
| `No module named PIL` | `pip install pillow numpy` |
| 控制台中文乱码 | 正常，工具故意输出英文 |
| `skin not found` | 皮肤名要和材料目录里的文件名完全一致（不含 `.vtf`） |
| 游戏里没变化 | 没重新 `pack`，或 VPK 没放进 addons，或同时开了别的普通感染者 mod |
| 模型发紫/黑 | 材质名写错，或 `.vmt` 里 `$basetexture` 指向了不存在的图 |
| 头顶多出一个方块 / 头盔不显示 | 皮肤和模型的顶点数不匹配（264 无头盔层 / 288 有头盔层） |
| 布娃娃扭曲 | mod 里混进了 `.phy`，删掉（`check` 会提醒） |

---

## 7. 撤销改动

- 改动前建议整个复制一份 mod 文件夹留底。
- 还原单个模型：`assign` 回原来的皮肤（`list` 能查到原名）。
- 还原单张皮肤：从原始素材目录把同名 `.vtf` 拷回来。
