# l4d2-Deathcraft-Zombies-Enhanced

由 Deepseek 处理

本mod以下面为基础修改，并未询问相关作者，如有作者要求下架，我会尊重原作者请求

Deathcraft Zombies

https://steamcommunity.com/sharedfiles/filedetails/?id=122945959

Deathcraft Zombies\[fix\]

https://steamcommunity.com/sharedfiles/filedetails/?id=3386683229

Minecraft Zombies Fix: Fixed Again

https://steamcommunity.com/sharedfiles/filedetails/?id=3815646772

## 使用

1. 通过 Steam 创意工坊订阅

https://steamcommunity.com/sharedfiles/filedetails/?id=3829142412

2. 下载 `vpk` 文件

不要订阅/下载同类 mod！！

到 [Releases](https://github.com/Little-Data/l4d2-Deathcraft-Zombies-Enhanced/releases) 下载 `vpk` 文件

将文件放到 `Left 4 Dead 2\left4dead2\addons` 中

## 文件夹

`tools` 为自定义工具，其余为 `vpk` 文件的内容

## 修改

基底：Deathcraft Zombies\[fix\]

修改来源：Minecraft Zombies Fix Fixed Again

### 为什么删掉 `.phy`

原版 L4D2 的普通感染者**没有 .phy 文件**（死亡后是客户端布娃娃，按骨骼自动生成）。这个 mod 却给每个模型塞了一个早期 L4D1 时代的简化 .phy（只有 3 个刚体），引擎会改用服务端布娃娃，骨骼匹配不上就会扭曲；模型没替换成功时，这个 .phy 还会被套到原版僵尸身上，于是出现“原版皮肤的僵尸死后布娃娃乱扭”。

## 其它修改

被感染生还者 / 伞兵的书包道具挂点改回原版位置：

pipebomb、molotov -> Spine2；pills -> Spine1；medkit -> Spine4

补齐所有普通感染者缺失的挂点：Head、chest、RArm/LArm/RLeg/LLeg、lfoot/rfoot、severed_*（否则面罩、断肢、背包等道具会掉在脚下）

修复"身上的物品在脚底"：把三个 L4D1 变体换成修好的模型

common_male_riot_l4d1 / common_male_fallen_survivor_l4d1 / common_male_ceda_l4d1

52 个基础模型各配一张独立皮肤，原有 38 张贴图全部启用

（armour iron、armour gold、armorgzom、hazmatzom2 这些之前是闲置的）

新增 6 个 scripts：

population.txt / population_l4d1coop.txt / population_l4d1survival.txt / population_l4d1vs.txt / population_survival.txt / population_versus.txt

原因：游戏用这些文件决定"哪张图刷哪些模型"，原版表只用到 35~49 个模型，很多皮肤永远刷不出来。

现在所有模型都进刷新表，每个区域保留原主题模型，其余按比例随机；每个 section 百分比仍合计 100。

若控制台出现 precache 警告，删掉 scripts/population*.txt 里几行低概率变体即可

若出现材质不一致提示，可用 `sv_consistency 0`

## 知识库文件

`知识库.md` 概括了我使用ai时留下的记录，方便再次询问ai时减少分析时间，相当于“记忆”