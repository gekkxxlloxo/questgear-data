# QuestGear 数据仓库（QuestGearData.lua 的权威源）

本仓库是 QuestGear 插件「任务/装备数据表」的权威数据源，配合 `.github/workflows/daily.yml` **每天从上游重新爬取并重建全部数据表**。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `QuestGearData.lua`（根目录） | **同步入口**：本地 `qg_sync.py` 每天 06:00 从这里拉取。CI 每次重建后会把 `build/QuestGearData.lua` 复制到这里。 |
| `meta.json`（根目录） | **同步元数据**：版本/计数，本地 `qg_sync.py` 据此做 L2 交叉校验后决定是否更新。 |
| `build/` | 完整构建链：主构建 `full_build.py` + 6 张表脚本 + `_research/` 基线资产 + 校验脚本。 |
| `build/_research/` | **无公开 URL 的静态基线资产**（CharStartOutfit.dbc / QuestDB.zip / 4 份 locale / wclbox 图鉴），随仓库保存，不每日重爬。 |
| `.github/workflows/daily.yml` | 每日重建工作流。 |

## 每天爬哪些数据（工作流实际下载源）

| 数据 | 来源 | 频率 |
| --- | --- | --- |
| QuestieDB Forever 任务/物品/NPC/Object 库 | `Questie/QuestieDB` releases 的最新 `-Forever.zip` | 每天（跟随新 release） |
| 物品品质/槽位/职业限制 | `sml86/wow-classic-items` + `JollyGrin/wow-bis` | 每天 |
| CMaNGOS classic-db SQL + 3 份中文 locale | jsDelivr CDN（`build_sources.py` 自带下载器） | 每天 |
| `locales_quest_zh.sql` / `CharStartOutfit.dbc` / `QuestDB.zip` / wclbox 图鉴清单 | 基线资产 `build/_research/`（静态事实数据，无稳定 URL） | 随仓库保存 |

## 坐标的三源交叉链（v1.108/v1.109 固化在 `full_build.py`）

接任务坐标按以下顺序回退，字段号按实体类型分别取（实测已到可靠范围内极限）：

1. `startedBy` 的 NPC → `Npc-<id>-7`（spawns，字段 7）；
2. `startedBy` 的 Object → `Object-<id>-4`（spawns，字段 **4**；`-7` 是 waypoints，全空）；
3. 物品触发任务 → 掉落源：`Item-<id>-2`（npcDrops）/ `-3`（objectDrops）→ 再取 NPC/Object spawn。

> 坐标系：QuestieDB spawn 是 0–100 百分比，烘焙时转 0–1。过滤 `-1/-1` 哨兵。
> 已实测其它候选源不可靠或不合语义：`triggerEnd` 是目标地点且多为哨兵、NPC waypoints 无覆盖、QuestDB 旧版是绝对坐标系。

## 同步机制

- 本地 `qg_sync.py`（Windows 计划任务每天 06:00）从**根目录**拉 `QuestGearData.lua` + `meta.json`，做 L1 下载 / L2 交叉校验（版本+计数+source）/ L3 原子替换。
- 因此 CI 每次重建后必须把产物同时写到根目录与 `build/`，二者版本与计数一致。
- 版本号用 TOC 里的 `X-BUILD-COMMIT` 前 8 位（形如 `qg-933ec77a`）——本地 `qg_sync.py` 的版本正则是 `qg-<hex>`，不接受 `qg-v1.1.6` 这种 tag 名。上游无新 commit 且构建逻辑无变化时内容不变，CI 跳过提交。

## 恢复/手动重建

```bash
cd build
pip install cbor2
python3 full_build.py --meta-out ../meta.json --version qg-<commit8>
python3 build_stats.py
python3 build_sources.py          # 联网补 CMaNGOS SQL；locale 用基线（必须先于 quest_info）
python3 build_quest_info.py       # 依赖 build_sources 产出的 ClassicDB_base.sql
python3 build_crafts.py
python3 build_special.py
python3 build_lost_items.py
python3 verify_data.py --file QuestGearData.lua --skip-source
cp QuestGearData.lua ../QuestGearData.lua && cp ../meta.json ../meta.json
```
