# -*- coding: utf-8 -*-
"""QuestGear 全量数据构建器（唯一入口）。

从 QuestieDB(Forever) baked TOC 一次性生成完整 QuestGearData.lua：
  QuestGearMeta     数据版本/构建时间/统计（供插件显示 + 自动更新比对）
  QuestGearData     [任务ID]={n,l,max,series,c,gear={{i,q,n,il,rl,c,s}}}
  QuestGearByLevel  等级段索引（保留兼容）
  QuestGearRewards  [任务ID]={xp,gear,other}
  QuestGearChains   [链首ID]={按顺序的任务ID}
  QuestGearNames    [任务ID]=中文名
  QuestGearZone     [任务ID]=uiMapID

与旧管线的差异：
  - 全量 1-60 级（旧版只有 1-30）
  - 装备含全子类：戒指/饰品/项链(sub=None)、魔杖(sub=19)、鱼竿(sub=20)、圣物(sub=6~9)
  - 品质 q 在生成条目时直接注入（不再事后正则）
  - 幂等：整文件重写，重复运行结果一致
"""
import argparse, base64, zlib, cbor2, json, os, re, datetime
from collections import Counter, defaultdict

# ---------------- 参数 ----------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
p = argparse.ArgumentParser()
# v2（GitHub Actions）：所有下载源统一放 upstream/，产出写本目录，
# 与 build_*.py 的 ROOT=脚本目录 约定一致，保证 9+6 张表在同一目录串起来。
p.add_argument('--toc', default=os.path.join(HERE, 'upstream/QuestieDB/QuestieDB_Forever.toc'))
p.add_argument('--out', default=os.path.join(HERE, 'QuestGearData.lua'))
p.add_argument('--quality', default=os.path.join(HERE, 'upstream/quality-full.json'))
p.add_argument('--quality2', default=os.path.join(HERE, 'upstream/quality.json'))
p.add_argument('--areamap', default=os.path.join(HERE, 'upstream/QuestieDB/support/Forever/Zones/areaIdToUiMapId.lua'))
p.add_argument('--xp', default=os.path.join(HERE, 'upstream/QuestieDB/support/Forever/QuestXP/xpDB-classic.lua'))
p.add_argument('--version', default=None, help='数据版本号，默认=上游commit前8位（上游不变则版本不变）')
p.add_argument('--meta-out', default=None, help='额外输出 JSON 元信息（供工作流判断是否需更新）')
p.add_argument('--max-level', type=int, default=60)
a = p.parse_args()

# ---------------- 读 TOC 元数据 ----------------
meta = {}
for line in open(a.toc, encoding='utf-8'):
    if line.startswith('## X-') and ':' in line:
        k, v = line[5:].split(':', 1); meta[k.strip()] = v.strip()

def get(k):
    v = meta.get(k)
    if v is None: return None
    if v.startswith('~') and v.endswith('~'):
        n = int(v[1:-1]); return ''.join(meta.get(f'{k}-{i}', '') for i in range(1, n+1))
    return v

def dec(k):
    v = get(k)
    if not v: return None
    raw = base64.b64decode(v)
    try: raw = zlib.decompress(raw)
    except Exception: pass
    try: return cbor2.loads(raw)
    except Exception: return None

def idlist(prefix):
    v = get(prefix + 'IDS')
    if not v: return []
    raw = base64.b64decode(v)
    try: raw = zlib.decompress(raw)
    except Exception: pass
    return cbor2.loads(raw)

def l10n_cols(key, ids):
    v = get(key)
    if not v: return {}
    raw = base64.b64decode(v)
    try: raw = zlib.decompress(raw)
    except Exception: return {}
    try: data = cbor2.loads(raw)
    except Exception: return {}
    cols = data if isinstance(data, list) else [data]
    out = {}
    if cols and isinstance(cols[0], list):
        for idx, val in enumerate(cols[0]):
            if idx < len(ids) and val:
                out[ids[idx]] = val.decode('utf-8', 'ignore') if isinstance(val, bytes) else str(val)
    return out

def sval(b):
    return b.decode('utf-8', 'ignore') if isinstance(b, bytes) else (str(b) if b is not None else None)

qids_all = idlist('Quest-')
iids_all = idlist('Item-')
npcids_all = idlist('Npc-')
objids_all = idlist('Object-')
qzh = l10n_cols('l10n-zhCN-Quest', qids_all)
izh = l10n_cols('l10n-zhCN-Item', iids_all)
npczh = l10n_cols('l10n-zhCN-Npc', npcids_all)     # v1.22：接任务 NPC 中文名
objzh = l10n_cols('l10n-zhCN-Object', objids_all)  # v1.22：接任务物件中文名
qids_set = set(qids_all)
print('QuestieDB: %d 任务 / %d 物品；中文名 任务%d 物品%d NPC%d 物件%d' % (
    len(qids_all), len(iids_all), len(qzh), len(izh), len(npczh), len(objzh)))

def qrow(q):
    r = dec(f'Quest-{q}-S'); return r if isinstance(r, dict) else {}
def irow(i):
    r = dec(f'Item-{i}-S'); return r if isinstance(r, dict) else {}
def qname(q, r=None):
    return qzh.get(q) or sval((r or {}).get(1)) or ('任务%d' % q)
def iname(i, r=None):
    return izh.get(i) or sval((r or {}).get(1)) or ('item%d' % i)

# ---------------- 物品 -> 任务 反查（字段6 questRewards）----------------
pat = re.compile(r'^Item-(\d+)-6$')
quest_items = defaultdict(list)
for k in meta:
    m = pat.match(k)
    if m:
        val = dec(k)
        if val:
            for q in val: quest_items[q].append(int(m.group(1)))

# ---------------- 品质表 ----------------
QUALITY_NUM = {'Poor':0,'Common':1,'Uncommon':2,'Rare':3,'Epic':4,'Legendary':5,'Artifact':6,'Heirloom':7}
# 装备槽位中文短标记：QuestieDB 无 inventoryType，借品质库的 slot 字段精确区分杂项护甲
SLOT_SHORT = {
    'Shirt':'衬衣', 'Tabard':'战袍', 'Finger':'戒指', 'Neck':'项链',
    'Trinket':'饰品', 'Back':'披风', 'Held In Off-hand':'副手', 'Off Hand':'副手',
    'Relic':'圣物', 'Chest':'胸甲', 'Legs':'腿甲', 'Hands':'手套', 'Feet':'靴',
    'Head':'头盔', 'Waist':'腰带', 'Shoulder':'护肩', 'Wrist':'护腕',
    'Two-Hand':'双手', 'Main Hand':'主手', 'One-Hand':'单手', 'Non-equippable':'杂',
}
# 物品级职业限制：tooltip 里的 "Classes: Mage" / "Classes: Priest, Mage, Warlock"
# 映射成内部职业 key，烘焙成装备 r 字段。子类熟练度（如德鲁伊能用法杖类别）
# 不足以判断具体物品——奥法之杖 s=法杖但写死 Classes: Mage，必须靠这个字段挡掉。
CLASS_KEY = {'Warrior':'warrior','Paladin':'paladin','Hunter':'hunter','Rogue':'rogue',
             'Priest':'priest','Shaman':'shaman','Mage':'mage','Warlock':'warlock','Druid':'druid'}
qmap = {}
smap = {}
rmap = {}   # itemID -> {内部职业key}，仅记录有 Classes: 限制的物品
for path in (a.quality, a.quality2):
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for it in json.load(f):
                iid = int(it['itemId'])
                qv = it.get('quality')
                if qv in QUALITY_NUM:
                    qmap.setdefault(iid, QUALITY_NUM[qv])
                sl = it.get('slot')
                if sl and iid not in smap:
                    smap[iid] = SLOT_SHORT.get(sl, sl)
                if iid not in rmap:
                    keys = set()
                    for t in it.get('tooltip', []):
                        lab = t.get('label', '') if isinstance(t, dict) else str(t)
                        if lab.startswith('Classes:'):
                            for part in lab.split(':', 1)[1].split(','):
                                k = CLASS_KEY.get(part.strip())
                                if k: keys.add(k)
                            break
                    if keys: rmap[iid] = sorted(keys)
print('品质表:', len(qmap), '件 | 槽位表:', len(smap), '件 | 职业限制表:', len(rmap), '件')

# ---------------- 经验表 ----------------
xp = {}
if os.path.exists(a.xp):
    for line in open(a.xp, encoding='utf-8'):
        m = re.match(r'\s*\[(\d+)\]\s*=\s*\{([^,]+),\s*(\d+)\}', line)
        if m: xp[int(m.group(1))] = int(m.group(3))
print('经验表:', len(xp), '条')

# ---------------- areaID -> uiMapID ----------------
area2map = {}
if os.path.exists(a.areamap):
    for line in open(a.areamap, encoding='utf-8'):
        m = re.match(r'\s*\[(\d+)\]\s*=\s*(\d+)\s*,', line)
        if m: area2map[int(m.group(1))] = int(m.group(2))
print('地图映射:', len(area2map), '条')

# ---------------- 任务链（字段22正向 + 字段13反向）----------------
next22, pre13 = {}, defaultdict(list)
for q in qids_all:
    r = qrow(q); f22 = r.get(22)
    if isinstance(f22, int) and f22 > 0 and f22 in qids_set: next22[q] = f22
    pv = dec(f'Quest-{q}-13')
    if isinstance(pv, list):
        for pre in pv:
            if isinstance(pre, int) and pre in qids_set: pre13[pre].append(q)
next_map = dict(next22)
for pre, succs in pre13.items():
    if pre not in next_map and len(succs) == 1: next_map[pre] = succs[0]
prev = defaultdict(list)
for src, dst in next_map.items(): prev[dst].append(src)

def find_head(q, maxsteps=60):
    cur, seen = q, {q}
    for _ in range(maxsteps):
        ps = [p for p in prev.get(cur, []) if p not in seen]
        if not ps: return cur
        cur = ps[0]; seen.add(cur)
    return cur

chains = {}
chain_of = {}
for q in qids_all:
    if q not in next_map and q not in prev: continue
    h = find_head(q)
    seq, cur, seen2 = [], h, set()
    while cur in qids_set and cur not in seen2:
        seen2.add(cur); seq.append(cur)
        if cur not in next_map: break
        cur = next_map[cur]
    if len(seq) >= 2:
        chains[h] = seq
        for i, x in enumerate(seq):
            if x not in chain_of or len(seq) > chain_of[x][1]:
                chain_of[x] = (i+1, len(seq), h)
print('任务链:', len(chains), '条，覆盖任务', len(chain_of))

# ---------------- 地图（startedBy -> NPC/Object zone -> uiMapID）----------------
npc_by_quest = defaultdict(list)
for nid in idlist('Npc-'):
    nr = dec(f'Npc-{nid}-S')
    if isinstance(nr, dict) and nr.get(10):
        for q in (nr[10] if isinstance(nr[10], list) else []): npc_by_quest[q].append(nid)

def to_map(area):
    if not isinstance(area, int) or area <= 0: return None
    return area2map.get(area)
def npc_zone(nid):
    nr = dec(f'Npc-{nid}-S'); return to_map(nr.get(9)) if isinstance(nr, dict) else None
def obj_zone(oid):
    # v1.109：Object 的 -S summary 里 zoneID 是字段 5（见 objectMeta.lua），不是 4。
    # 旧代码取 o.get(4) 对全部 7471 个 Object 都拿到 None（4 是完整记录里的 spawns，
    # 不出现在 -S）；zone_of() 靠 zoneOrSort 兜底才没暴露。
    o = dec(f'Object-{oid}-S'); return to_map(o.get(5)) if isinstance(o, dict) else None

def zone_of(q):
    sb = dec(f'Quest-{q}-2')
    npcs, objs = [], []
    if isinstance(sb, list) and sb:
        if isinstance(sb[0], list): npcs = sb[0]
        if len(sb) > 1 and isinstance(sb[1], list): objs = sb[1]
    for nid in npcs:
        m = npc_zone(nid)
        if m: return m
    for oid in objs:
        m = obj_zone(oid)
        if m: return m
    for nid in npc_by_quest.get(q, []):
        m = npc_zone(nid)
        if m: return m
    z = qrow(q).get(17)
    return to_map(z) if isinstance(z, int) and z > 0 else None

# ---------------- 起始坐标（NPC/Object spawn -> uiMapID + 0-1 归一化坐标）----------------
# 供插件「距离」排序用：QuestieDB 的 spawn 坐标是 0-100 百分比，转成 0-1。
# 优先取与任务 zone 一致的 area；取不到则取第一个可映射 area 的首个坐标点。
def spawn_pos(ref_id, kind):
    # v1.109：spawns 字段号随类型不同——Npc 是 7（npcMeta.lua），Object 是 4
    # （objectMeta.lua；-7 是 waypoints，对全部 7471 个 Object 均为空）。
    # 旧代码对两种类型都读 -7，导致 5680 个 Object spawn 从未进入坐标链。
    fld = 7 if kind == 'Npc' else 4
    sp = dec(f'{kind}-{ref_id}-{fld}')
    if not isinstance(sp, dict): return None
    for area, pts in sp.items():
        m = to_map(area)
        if m and isinstance(pts, list) and pts and isinstance(pts[0], list) and len(pts[0]) >= 2:
            x, y = pts[0][0], pts[0][1]
            # -1/-1 是 QuestieDB 的「无坐标」哨兵，跳过（否则烘焙出负坐标）
            if isinstance(x, (int, float)) and isinstance(y, (int, float)) and x >= 0 and y >= 0:
                return (m, x / 100.0, y / 100.0)
    return None

def item_spawn_pos(item_id):
    """物品启动任务（startedBy 的 itemIds）没有自己的 spawn：回退到掉落该物品的
    NPC/Object 的 spawn。QuestieDB 字段：Item-<id>-2=npcDrops, -3=objectDrops。
    v1.108：修「被污染的水元素」(1918, 物品16408) 等物品触发任务坐标缺失。"""
    for field, kind in ((2, 'Npc'), (3, 'Object')):
        refs = dec(f'Item-{item_id}-{field}') or []
        for ref in (refs if isinstance(refs, list) else [refs]):
            if not isinstance(ref, int): continue
            p = spawn_pos(ref, kind)
            if p: return p
    return None

def pos_of(q):
    sb = dec(f'Quest-{q}-2')
    npcs, objs, items = [], [], []
    if isinstance(sb, dict) and sb:
        # 标准结构 {0?:npcIds, 1?:objectIds, 3?:itemIds}（见 questMeta.lua startedBy）
        npcs  = sb.get(0) or []
        objs  = sb.get(1) or []
        items = sb.get(3) or []
    elif isinstance(sb, list) and sb:
        if isinstance(sb[0], list): npcs = sb[0]
        if len(sb) > 1 and isinstance(sb[1], list): objs = sb[1]
    for nid in list(npcs) + npc_by_quest.get(q, []):
        p = spawn_pos(nid, 'Npc')
        if p: return p
    for oid in objs:
        p = spawn_pos(oid, 'Object')
        if p: return p
    # v1.108：NPC/Object 都取不到时，物品启动任务走掉落源回退（不污染已有 NPC 任务）
    for iid in items:
        if not isinstance(iid, int): continue
        p = item_spawn_pos(iid)
        if p: return p
    return None

# ---------------- 接任务 NPC/物件中文名（v1.22）----------------
# 优先 Quest-q-2.startedBy 的第一个 NPC，再 Object，再 npc_by_quest 反查。
# 中文名从 l10n-zhCN-Npc/Object 取，回退英文名 -S[1]。
def starter_of(q):
    sb = dec(f'Quest-{q}-2')
    npcs, objs = [], []
    if isinstance(sb, list) and sb:
        if isinstance(sb[0], list): npcs = sb[0]
        if len(sb) > 1 and isinstance(sb[1], list): objs = sb[1]
    for nid in list(npcs) + npc_by_quest.get(q, []):
        nm = npczh.get(nid)
        if nm: return nm
        nr = dec(f'Npc-{nid}-S')
        if isinstance(nr, dict) and nr.get(1): return sval(nr[1])
    for oid in objs:
        nm = objzh.get(oid)
        if nm: return nm
        o = dec(f'Object-{oid}-S')
        if isinstance(o, dict) and o.get(1): return sval(o[1])
    return None

# ---------------- 构建主数据 ----------------
# 阵营：QuestieDB 任务第 6 字段 requiredRaces 是种族位掩码，无独立 faction 字段。
# Forever 的位定义见 extracted/QuestieDB/src/corrections/enum/expansions.lua：
#   联盟 = 人1/矮4/暗夜8/侏64/德莱尼1024/狼人2097152/熊猫人联盟16777216/天空联盟2^32
#   部落 = 兽2/亡灵16/牛32/巨魔128/地精256/血精灵512/熊猫人部落2^25/天空部落2^33
# 烘焙成 f=1(联盟)/2(部落)/3(双方)/0(nil，中立)，运行时只需 UnitFactionGroup 过滤。
ALLY_BITS  = 1 | 4 | 8 | 64 | 1024 | 2097152 | (1 << 24) | (1 << 32)
HORDE_BITS = 2 | 16 | 32 | 128 | 256 | 512 | (1 << 25) | (1 << 33)
def faction_of(mask):
    if not isinstance(mask, int) or mask <= 0:
        return 0
    a, h = bool(mask & ALLY_BITS), bool(mask & HORDE_BITS)
    if a and h: return 3
    if a: return 1
    if h: return 2
    return 0

GEAR_CLASSES = {2, 4}
DATA = {}
skipped = 0
for q, items in quest_items.items():
    r = qrow(q)
    lvl = r.get(4)
    if not isinstance(lvl, int) or not (1 <= lvl <= a.max_level): continue
    gear = []
    for i in items:
        ir = irow(i); c = ir.get(12)
        if c not in GEAR_CLASSES: continue
        gear.append({'i': i, 'q': qmap.get(i), 'n': iname(i, ir),
                     'il': ir.get(9), 'rl': ir.get(10), 'c': c, 's': ir.get(13),
                     't': smap.get(i), 'r': rmap.get(i)})
    if not gear:
        skipped += 1; continue
    gear.sort(key=lambda g: (g['il'] or 0), reverse=True)
    cls_flags = sorted({g['c'] for g in gear})
    DATA[q] = {'n': qname(q, r), 'l': lvl, 'max': r.get(5), 'series': r.get(17),
               'c': cls_flags, 'f': faction_of(r.get(6)), 'gear': gear}

print('全量数据集: %d 任务（跳过无装备 %d）' % (len(DATA), skipped))
byband = Counter()
for d in DATA.values():
    byband[min((d['l']-1)//10*10, 60)] += 1
print('等级分布:', dict(sorted(byband.items())))

# ---------------- 奖励（对链上全部任务 + 装备任务）----------------
reward_qs = set(chain_of) | set(DATA)
rewards = {}
for q in reward_qs:
    gear, other = [], []
    for i in quest_items.get(q, []):
        ir = irow(i); c = ir.get(12)
        item = {'i': i, 'n': iname(i, ir)}
        if c in GEAR_CLASSES:
            item.update({'q': qmap.get(i), 'il': ir.get(9), 'c': c, 's': ir.get(13),
                         't': smap.get(i), 'r': rmap.get(i)})
            gear.append(item)
        else:
            item['c'] = c; other.append(item)
    xpv = xp.get(q)
    if gear or other or xpv:
        gear.sort(key=lambda g: (g.get('il') or 0), reverse=True)
        rewards[q] = {'xp': xpv, 'gear': gear, 'other': other}
print('奖励表:', len(rewards), '条')

# ---------------- 地图表（只覆盖数据集 + 链上任务）----------------
zone_qs = set(DATA) | set(chain_of)
zones = {}
for q in zone_qs:
    m = zone_of(q)
    if m: zones[q] = m
print('地图表:', len(zones), '/', len(zone_qs), '(%.1f%%)' % (100.0*len(zones)/max(1,len(zone_qs))))

# ---------------- 起始坐标表（只覆盖数据集 + 链上任务）----------------
positions = {}
for q in zone_qs:
    pos = pos_of(q)
    if pos: positions[q] = pos
print('坐标表:', len(positions), '/', len(zone_qs), '(%.1f%%)' % (100.0*len(positions)/max(1,len(zone_qs))))

# ---------------- 接任务 NPC/物件表（v1.22）----------------
starters = {}
for q in zone_qs:
    nm = starter_of(q)
    if nm: starters[q] = nm
print('接任务NPC表:', len(starters), '/', len(zone_qs), '(%.1f%%)' % (100.0*len(starters)/max(1,len(zone_qs))))

# ---------------- 链名（链上全部任务）----------------
chain_qs = set()
for seq in chains.values(): chain_qs.update(seq)
names = {}
for q in chain_qs:
    nm = qzh.get(q) or sval(qrow(q).get(1))
    if nm: names[q] = nm
print('链任务名:', len(names), '/', len(chain_qs))

# ---------------- 写 Lua ----------------
def esc(s):
    return str(s).replace('\\','\\\\').replace('"','\\"').replace('\n',' ').replace('\r',' ')
def num(v): return str(v) if isinstance(v, (int, float)) else 'nil'
def tstr(v): return ('"'+esc(v)+'"') if v else 'nil'
def rlist(v): return ('{'+','.join('"'+x+'"' for x in v)+'}') if v else 'nil'

built = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
upstream = meta.get('BUILD-COMMIT', 'unknown')
upstream_time = meta.get('BUILD-TIME', 'unknown')
# 版本绑定上游 commit：上游数据没变则版本号不变，工作流可据此跳过无意义提交
version = a.version or ('qg-' + upstream[:8] if upstream and upstream != 'unknown'
                        else datetime.date.today().strftime('%Y%m%d'))

L = []
L.append('-- QuestGear 全量数据（full_build.py 自动生成，勿手改）')
L.append('-- 源: QuestieDB(Forever) commit=%s build=%s' % (upstream, upstream_time))
L.append('-- 构建: %s 版本: %s' % (built, version))
L.append('-- 字段: f=阵营(0中立/1联盟/2部落/3双方) q=品质(0差1白2绿3蓝4紫5橙) i=物品ID n=名 il=装等 rl=需求等级 c=类别(2武器/4护甲) s=子类 t=槽位 r=职业限制(内部key列表,nil=不限)')
L.append('QuestGearMeta = {v="%s",built="%s",source="%s",tasks=%d,gear=%d,chains=%d}' % (
    esc(version), esc(built), esc(upstream), len(DATA),
    sum(len(d['gear']) for d in DATA.values()), len(chains)))
L.append('')
L.append('QuestGearData = {')
for q in sorted(DATA, key=lambda x: (DATA[x]['l'], x)):
    d = DATA[q]
    gp = ','.join('{i=%d,q=%s,n=%s,il=%s,rl=%s,c=%s,s=%s,t=%s,r=%s}' % (
        g['i'], num(g['q']), '"'+esc(g['n'])+'"', num(g['il']), num(g['rl']), num(g['c']), num(g['s']),
        tstr(g.get('t')), rlist(g.get('r')))
        for g in d['gear'])
    L.append('  [%d]={n=%s,l=%d,max=%s,series=%s,c={%s},f=%d,gear={%s}},' % (
        q, '"'+esc(d['n'])+'"', d['l'], num(d['max']), num(d['series']),
        ','.join(str(x) for x in d['c']), d.get('f', 0), gp))
L.append('}')
L.append('')
# 等级段索引（兼容保留，6 档）
L.append('QuestGearByLevel = { [1]={}, [11]={}, [21]={}, [31]={}, [41]={}, [51]={} }')
for q in sorted(DATA, key=lambda x: (DATA[x]['l'], x)):
    band = min((DATA[q]['l']-1)//10*10+1, 51)
    L.append('  table.insert(QuestGearByLevel[%d], %d)' % (band, q))
L.append('')
L.append('-- ===== 奖励 =====')
L.append('QuestGearRewards = {')
for q in sorted(rewards):
    v = rewards[q]; parts = []
    if v['gear']:
        gp = ','.join('{i=%d,q=%s,n=%s,il=%s,c=%s,s=%s,t=%s,r=%s}' % (
            g['i'], num(g.get('q')), '"'+esc(g['n'])+'"', num(g.get('il')), num(g['c']), num(g['s']),
            tstr(g.get('t')), rlist(g.get('r')))
            for g in v['gear'])
        parts.append('gear={%s}' % gp)
    if v['other']:
        op = ','.join('{i=%d,n=%s,c=%s}' % (o['i'], '"'+esc(o['n'])+'"', num(o.get('c'))) for o in v['other'])
        parts.append('other={%s}' % op)
    if v['xp']: parts.append('xp=%d' % v['xp'])
    L.append('  [%d]={%s},' % (q, ','.join(parts)))
L.append('}')
L.append('')
L.append('-- ===== 任务链 =====')
L.append('QuestGearChains = {')
for h in sorted(chains):
    L.append('  [%d]={%s},' % (h, ','.join(str(x) for x in chains[h])))
L.append('}')
L.append('')
L.append('QuestGearNames = {')
for q in sorted(names):
    L.append('  [%d]="%s",' % (q, esc(names[q])))
L.append('}')
L.append('')
L.append('-- ===== 起始地图（uiMapID，界面用 C_Map.GetMapInfo(id).name 本地化）=====')
L.append('QuestGearZone = {')
for q in sorted(zones):
    L.append('  [%d]=%d,' % (q, zones[q]))
L.append('}  -- END QUESTGEARZONE')
L.append('')
L.append('-- ===== 起始坐标（uiMapID + 0-1 归一化坐标，供「距离」排序）=====')
L.append('QuestGearPos = {')
for q in sorted(positions):
    m, x, y = positions[q]
    L.append('  [%d]={m=%d,x=%.4f,y=%.4f},' % (q, m, x, y))
L.append('}  -- END QUESTGEARPOS')
L.append('')
L.append('-- ===== 接任务 NPC/物件中文名（v1.22，对应 QuestGearPos 坐标）=====')
L.append('QuestGearStarter = {')
for q in sorted(starters):
    L.append('  [%d]="%s",' % (q, esc(starters[q])))
L.append('}  -- END QUESTGEARSTARTER')
L.append('')

out = '\n'.join(L)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
with open(a.out, 'w', encoding='utf-8') as f: f.write(out)
print('已写 %s (%d 字节)' % (a.out, len(out.encode('utf-8'))))

if a.meta_out:
    meta_obj = {
        'version': version, 'built': built, 'source': upstream, 'source_time': upstream_time,
        'tasks': len(DATA), 'gear': sum(len(d['gear']) for d in DATA.values()),
        'chains': len(chains), 'rewards': len(rewards), 'zones': len(zones), 'positions': len(positions),
        'by_band': {('%d-%d' % (b, min(b+9, a.max_level))): n for b, n in sorted(byband.items())},
    }
    with open(a.meta_out, 'w', encoding='utf-8') as f:
        json.dump(meta_obj, f, ensure_ascii=False, indent=2)
    print('已写 meta:', a.meta_out, '版本', version)

# ---------------- 自校验 ----------------
try:
    from lupa import LuaRuntime
    lr = LuaRuntime()
    lr.execute(out)
    g = lr.globals()
    print('Lua 加载 OK | Meta:', g.QuestGearMeta.v, '| Data:', len(list(g.QuestGearData)),
          '| Chains:', len(list(g.QuestGearChains)), '| Zones:', len(list(g.QuestGearZone)))
except ImportError:
    print('（lupa 未安装，跳过 Lua 加载校验）')
