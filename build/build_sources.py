# -*- coding: utf-8 -*-
"""QG 全量装备来源数据表构建器（方案一：源头 CMaNGOS）。

数据源（全部为事实数据，重新表达为自有格式，不分发源文件）：
  - CMaNGOS classic-db  Full_DB/ClassicDB_1_12_1_z2815.sql.gz   (GPL-3.0)
  - CMaNGOS locales/Chinese/locales_creature.sql / locales_item.sql
  - 本项目 items-quality-full.json（装备清单/属性）
  - 本项目 QuestGearData.lua（任务类权威源）
  - 本项目 _research/wclbox_gear_20261124.json（永久服图鉴装备清单，仅用于补任务奖励的
    中文名/品质/槽位；来源位仍记为任务）

v1.85 修正（体检发现）：
  1. SQL 元组解析改为逐字符扫描，正确处理名称里的逗号/括号/引号；旧版按逗号切分会错列。
  2. 修正 reference_loot_template 语义：父表里 mincountOrRef < 0 的行才是“引用组”，
     旧版把引用组一律记为世界掉落，导致副本 boss 的套装件被标成世界。
  3. 修正 gameobject_loot_template.entry（lootId）与 gameobject_template.data1 的关联，
     旧版把 lootId 当 GO entry 查刷新点，几乎全部落空。
  4. 任务装备 ID 改用 lupa 读 QuestGearData（旧版正则 \\bi= 会扫到无关字段）。
  5. 下载改为临时文件 + 校验后原子替换；gzip 损坏自动重下。
  6. 用 wclbox 清单补齐“任务奖励里有、1.12 库里没有”的永久服新装备（只补任务位）。

用法：python build_sources.py [--offline] [--no-wclbox]
  --offline   使用 _research/ 下已下载的文件，不重新联网。
"""
import os, re, sys, json, gzip, argparse, datetime, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, '_research')
CDN = 'https://cdn.jsdelivr.net/gh/cmangos/classic-db@master/'

BIT_TASK, BIT_DUNGEON, BIT_WORLD, BIT_NPC, BIT_OTHER = 1, 2, 4, 8, 16
CONTINENT_MAPS_INT = {0, 1}

LOG = []
def log(s):
    LOG.append(s)
    print(s)


# ---------- 数据获取 ----------
def fetch(url, dest, offline):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        log('  使用本地: %s (%d KB)' % (os.path.basename(dest), os.path.getsize(dest)//1024))
        return dest
    if offline:
        raise RuntimeError('离线模式缺少文件: ' + dest)
    log('  下载: %s' % url)
    last = None
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'QuestGearBuild/1.1'})
            data = urllib.request.urlopen(req, timeout=180).read()
            tmp = dest + '.part'
            with open(tmp, 'wb') as f:
                f.write(data)
            if dest.endswith('.gz'):
                with gzip.open(tmp, 'rb') as g:
                    g.read(1024)
            os.replace(tmp, dest)
            log('  完成 (%d KB)' % (len(data)//1024))
            return dest
        except Exception as e:
            last = e
            log('  下载失败(第%d次): %s' % (i + 1, e))
    raise RuntimeError('下载失败: %s (%s)' % (url, last))


def get_sql(offline):
    gz = os.path.join(RES, 'ClassicDB_base.sql.gz')
    fetch(CDN + 'Full_DB/ClassicDB_1_12_1_z2815.sql.gz', gz, offline)
    plain = os.path.join(RES, 'ClassicDB_base.sql')
    if os.path.exists(plain) and os.path.getsize(plain) > 1000000:
        sql = open(plain, encoding='utf-8', errors='replace').read()
    else:
        try:
            with gzip.open(gz, 'rt', encoding='utf-8', errors='replace') as f:
                sql = f.read()
        except Exception:
            # 本地包损坏：删掉重下
            os.remove(gz)
            fetch(CDN + 'Full_DB/ClassicDB_1_12_1_z2815.sql.gz', gz, offline)
            with gzip.open(gz, 'rt', encoding='utf-8', errors='replace') as f:
                sql = f.read()
        with open(plain, 'w', encoding='utf-8', errors='replace') as f:
            f.write(sql)
    log('  SQL 载入: %d 字符' % len(sql))
    return sql


def get_locale_tables(offline):
    out = {}
    for name, url in [
        ('creature', 'locales/Chinese/locales_creature.sql'),
        ('item', 'locales/Chinese/locales_item.sql'),
        ('gameobject', 'locales/Chinese/locales_gameobject.sql'),
    ]:
        dest = os.path.join(RES, 'locales_%s_zh.sql' % name)
        fetch(CDN + url, dest, offline)
        out[name] = open(dest, encoding='utf-8', errors='replace').read()
    return out


# ---------- SQL 解析（逐字符，正确处理引号/括号/逗号） ----------
def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("\\'", "'").replace("''", "'").replace('\\"', '"')
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace('""', '"')
    if s.upper() == 'NULL':
        return None
    return s


def iter_tuples(text):
    """从 VALUES 之后的文本里逐个抽元组；引号内的逗号/括号不再当分隔符。"""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == ';':
            return
        if ch != '(':
            i += 1
            continue
        i += 1
        fields, cur, quote = [], [], None
        while i < n:
            ch = text[i]
            if quote:
                if ch == '\\':
                    cur.append(ch)
                    i += 1
                    if i < n:
                        cur.append(text[i])
                        i += 1
                    continue
                cur.append(ch)
                i += 1
                if ch == quote:
                    quote = None
                continue
            if ch in "'\"":
                quote = ch
                cur.append(ch)
                i += 1
                continue
            if ch == ',':
                fields.append(''.join(cur))
                cur = []
                i += 1
                continue
            if ch == ')':
                fields.append(''.join(cur))
                i += 1
                yield fields
                break
            cur.append(ch)
            i += 1


def table_segments(sql, tname):
    results = []
    for m in re.finditer(r'CREATE TABLE `?' + re.escape(tname) + r'`?\s*\((.*?)\)\s*ENGINE',
                         sql, re.S | re.I):
        cols = re.findall(r'^\s*`(\w+)`\s+\w', m.group(1), re.M)
        nxt = sql.find('CREATE TABLE', m.end())
        seg = sql[m.end(): nxt if nxt > 0 else len(sql)]
        results.append((cols, seg))
    return results


def parse_rows(sql, tname, want_cols, converters=None):
    """返回 want_cols 对应的行（缺列的表段跳过）。"""
    out = []
    for cols, seg in table_segments(sql, tname):
        if not all(c in cols for c in want_cols):
            continue
        idx = [cols.index(c) for c in want_cols]
        for im in re.finditer(r'INSERT\s+INTO\s+`?' + re.escape(tname) + r'`?[^V]*?VALUES',
                              seg, re.I):
            tail = seg[im.end():]
            for fields in iter_tuples(tail):
                if len(fields) < len(cols):
                    continue
                row = tuple(_unquote(fields[i]) for i in idx)
                if converters:
                    row = converters(row)
                out.append(row)
                if len(out) % 20000 == 0:
                    log('    %s %d 行' % (tname, len(out)))
    return out


def to_int(row):
    return tuple(int(x) if isinstance(x, str) and x.lstrip('-').isdigit() else x for x in row)


# ---------- 名称 ----------
def parse_locale(sql_text, table):
    """locales_*.sql 没有 CREATE TABLE，列清单写在每条 INSERT 里，单独解析。"""
    out = {}
    pat = re.compile(r'INSERT\s+INTO\s+`?' + re.escape(table) + r'`?\s*\(([^)]*)\)\s*VALUES',
                     re.I)
    for m in pat.finditer(sql_text):
        cols = [c.strip().strip('`') for c in m.group(1).split(',')]
        if 'entry' not in cols or 'name_loc4' not in cols:
            continue
        ei, ni = cols.index('entry'), cols.index('name_loc4')
        tail = sql_text[m.end():]
        for fields in iter_tuples(tail):
            if len(fields) <= max(ei, ni):
                continue
            ent = _unquote(fields[ei])
            nm = _unquote(fields[ni])
            if ent and ent.lstrip('-').isdigit() and nm:
                out[int(ent)] = nm
    return out


# ---------- 副本名 ----------
def build_map_names(sql):
    rows = parse_rows(sql, 'areatrigger_teleport', ['name', 'target_map'])
    names = {}
    for nm, tmap in rows:
        try:
            mid = int(tmap)
        except (TypeError, ValueError):
            continue
        if mid in CONTINENT_MAPS_INT or not nm:
            continue
        clean = re.sub(r'\s*-\s*(Entering|Entrance).*$', '', nm, flags=re.I).strip()
        if clean and mid not in names:
            names[mid] = clean
    return names


def si(x):
    try:
        return int(x)
    except (ValueError, TypeError):
        return -1


def as_int(x):
    try:
        return int(x)
    except (ValueError, TypeError):
        return 0


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--no-wclbox', action='store_true')
    args = ap.parse_args()

    log('=== QG 来源数据表构建 v1.85 ===')
    sql = get_sql(args.offline)
    loc = get_locale_tables(args.offline)

    log('解析中文名表...')
    zh_creature = parse_locale(loc['creature'], 'locales_creature')
    zh_item = parse_locale(loc['item'], 'locales_item')
    zh_gobj = parse_locale(loc['gameobject'], 'locales_gameobject')
    log('  中文名: 生物%d 物品%d 物件%d' % (len(zh_creature), len(zh_item), len(zh_gobj)))

    log('解析 map→副本名...')
    map_names = build_map_names(sql)
    log('  副本 map 数: %d' % len(map_names))

    log('解析生物刷新点...')
    creature_map = {}
    for tid, mp in parse_rows(sql, 'creature', ['id', 'map']):
        tid, mp = si(tid), si(mp)
        if tid >= 0:
            creature_map.setdefault(tid, set()).add(mp)
    log('  有刷新点的生物模板: %d' % len(creature_map))

    log('解析物件刷新点 + data1(lootId) 关联...')
    gobj_map, gobj_loot = {}, {}
    for row in parse_rows(sql, 'gameobject_template', ['entry', 'data1']):
        gid, loot = si(row[0]), si(row[1])
        if gid >= 0 and loot > 0:
            gobj_loot.setdefault(loot, set()).add(gid)
    for gid, mp in parse_rows(sql, 'gameobject', ['id', 'map']):
        gid, mp = si(gid), si(mp)
        if gid >= 0:
            gobj_map.setdefault(gid, set()).add(mp)
    log('  物件模板: %d，有 lootId: %d，有刷新点: %d' % (len(gobj_loot), len(gobj_loot), len(gobj_map)))

    log('解析生物/物件名称...')
    cname = {}
    for ent, nm in parse_rows(sql, 'creature_template', ['Entry', 'Name']):
        eid = si(ent)
        if eid >= 0:
            cname[eid] = zh_creature.get(eid) or nm
    gname = {}
    for ent, nm in parse_rows(sql, 'gameobject_template', ['entry', 'name']):
        eid = si(ent)
        if eid >= 0:
            gname[eid] = zh_gobj.get(eid) or nm

    log('解析掉落与商人表...')
    sources = {}      # item -> [(kind, id, chance)]
    ref_parents = {}  # refGroup -> set((kind, parentEntry))
    ref_items = {}    # refGroup -> [item]

    def add(item, kind, sid, chance=0):
        item, sid = as_int(item), as_int(sid)
        if item > 0:
            sources.setdefault(item, []).append((kind, sid, chance))

    for entry, item, minref in parse_rows(sql, 'creature_loot_template', ['entry', 'item', 'mincountOrRef']):
        entry, item, minref = si(entry), si(item), si(minref)
        if item <= 0:
            continue
        if minref < 0:
            ref_parents.setdefault(item, set()).add(('C', entry))
        else:
            add(item, 'C', entry)
    for entry, item, minref in parse_rows(sql, 'gameobject_loot_template', ['entry', 'item', 'mincountOrRef']):
        entry, item, minref = si(entry), si(item), si(minref)
        if item <= 0:
            continue
        if minref < 0:
            ref_parents.setdefault(item, set()).add(('G', entry))
        else:
            add(item, 'G', entry)
    for entry, item, minref in parse_rows(sql, 'reference_loot_template', ['entry', 'item', 'mincountOrRef']):
        entry, item, minref = si(entry), si(item), si(minref)
        if item > 0 and minref >= 0:
            ref_items.setdefault(entry, []).append(item)
    for entry, item in parse_rows(sql, 'npc_vendor', ['entry', 'item']):
        add(item, 'V', entry)
    log('  直接掉落/商人物品: %d；引用组: %d（父引用 %d 组）' % (
        len(sources), len(ref_items), len(ref_parents)))

    # 把引用组展开到父怪/父物件
    for group, items in ref_items.items():
        for kind, parent in ref_parents.get(group, ()):
            for item in items:
                sources.setdefault(item, []).append(('R', (kind, parent), 0))

    # 任务装备 ID（lupa 读真实 gear.i）
    qdata = open(os.path.join(ROOT, 'QuestGearData.lua'), encoding='utf-8').read()
    quest_ids = set()
    try:
        from lupa import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(qdata)
        D = lua.globals().QuestGearData
        for _, d in D.items():
            gear = d['gear']
            if not gear:
                continue
            for g in gear.values():
                quest_ids.add(int(g['i']))
        log('  任务奖励装备（lupa）: %d' % len(quest_ids))
    except Exception as e:
        log('  lupa 不可用(%s)，回退正则' % e)
        quest_ids = set(int(x) for x in re.findall(r'\{i=(\d+)', qdata))

    # 装备清单
    items = json.load(open(os.path.join(ROOT, 'items-quality-full.json'), encoding='utf-8'))
    valid_db = set()
    for (eid,) in parse_rows(sql, 'item_template', ['entry']):
        try:
            valid_db.add(int(eid))
        except (ValueError, TypeError):
            pass
    gear = [it for it in items if it.get('class') in ('Armor', 'Weapon')
            and it['itemId'] in valid_db and (it.get('requiredLevel') or 0) <= 60]
    log('有效装备（req<=60 且在来源库）: %d' % len(gear))

    QUAL = {'Poor': 0, 'Common': 1, 'Uncommon': 2, 'Rare': 3, 'Epic': 4, 'Legendary': 5}
    SUB = {'Cloth': 1, 'Leather': 2, 'Mail': 3, 'Plate': 4, 'Shield': 6,
           'Libram': 7, 'Idol': 8, 'Totem': 9, 'Staff': 10,
           'Axe': 11, 'Sword': 11, 'Mace': 11, 'Dagger': 15, 'Gun': 3,
           'Bow': 2, 'Crossbow': 18, 'Wand': 19, 'Polearm': 6,
           'Fist Weapon': 13, 'Fishing Pole': 20, 'Thrown': 2, 'Miscellaneous': 5}
    SLOT = {'Back': '披风', 'Chest': '胸甲', 'Feet': '靴', 'Finger': '戒指',
            'Hands': '手套', 'Head': '头盔', 'Held In Off-hand': '副手',
            'Legs': '腿甲', 'Main Hand': '主手', 'Neck': '项链',
            'Off Hand': '副手', 'One-Hand': '单手', 'Shirt': '衬衣',
            'Shoulder': '护肩', 'Tabard': '战袍', 'Trinket': '饰品',
            'Two-Hand': '双手', 'Waist': '腰带', 'Wrist': '护腕',
            'Ranged': '远程', 'Relic': '圣物', 'Thrown': '投掷', 'Non-equippable': '杂'}

    def item_attrs(it):
        q = QUAL.get(it.get('quality'), 1)
        c = 4 if it.get('class') == 'Armor' else 2
        s = SUB.get(it.get('subclass'), 5)
        t = SLOT.get(it.get('slot'), '杂')
        il = it.get('itemLevel') or 0
        rl = it.get('requiredLevel') or 0
        return q, c, s, t, il, rl

    out = {}
    stats = {'task': 0, 'dungeon': 0, 'world': 0, 'npc': 0, 'other': 0}
    for it in gear:
        iid = it['itemId']
        bits = 0
        details = []
        if iid in quest_ids:
            bits |= BIT_TASK
            stats['task'] += 1
            details.append('T')
        has_dungeon = has_world = has_npc = False
        dungeon_detail = world_detail = npc_detail = None
        for kind, sid, chance in sources.get(iid, []):
            if kind == 'R':
                pkind, parent = sid
                maps = (creature_map if pkind == 'C' else gobj_map).get(parent, set())
                nm = (cname if pkind == 'C' else gname).get(parent, '%s%d' % (pkind, parent))
            elif kind == 'V':
                maps = creature_map.get(sid, set())
                nm = cname.get(sid, '商人%d' % sid)
                in_inst = any(m not in CONTINENT_MAPS_INT for m in maps)
                if in_inst:
                    if not has_dungeon:
                        has_dungeon = True
                        dungeon_detail = '商店:' + nm
                else:
                    has_npc = True
                    if not npc_detail:
                        npc_detail = '商人:' + nm
                continue
            else:
                if kind == 'C':
                    maps = creature_map.get(sid, set())
                else:
                    # lootId -> GO entry（data1），再查刷新点
                    maps = set()
                    for gent in gobj_loot.get(sid, ()):
                        maps |= gobj_map.get(gent, set())
                nm = (cname if kind == 'C' else gname).get(sid, '%s%d' % (kind, sid))
            if any(m not in CONTINENT_MAPS_INT for m in maps):
                has_dungeon = True
                if not dungeon_detail:
                    mid = next((m for m in maps if m not in CONTINENT_MAPS_INT), None)
                    dn = map_names.get(mid, '')
                    dungeon_detail = '掉落:' + nm + (('@' + dn) if dn else '')
            elif maps:
                has_world = True
                if not world_detail:
                    world_detail = '掉落:' + nm
            else:
                # 引用组仍无位置：保留“掉落”但归世界（宁可标世界也不丢来源）
                has_world = True
                if not world_detail:
                    world_detail = '掉落:' + nm
        if has_dungeon:
            bits |= BIT_DUNGEON; stats['dungeon'] += 1; details.append('D:' + (dungeon_detail or ''))
        if has_world:
            bits |= BIT_WORLD; stats['world'] += 1; details.append('W:' + (world_detail or ''))
        if has_npc:
            bits |= BIT_NPC; stats['npc'] += 1; details.append('N:' + (npc_detail or ''))
        if bits == 0:
            bits = BIT_OTHER; stats['other'] += 1; details.append('O')
        zh = zh_item.get(iid) or it.get('name') or ''
        q, c, sv, t, il, rl = item_attrs(it)
        out[iid] = {'s': bits, 'n': zh, 'd': '|'.join(details),
                    'q': q, 'c': c, 'v': sv, 't': t, 'l': il, 'r': rl}

    log('来源统计(可多来源): %s' % stats)

    # v1.85：补永久服新装备（仅任务奖励里出现、1.12 库没有的）
    if not args.no_wclbox:
        wp = os.path.join(RES, 'wclbox_gear_20261124.json')
        if os.path.exists(wp):
            G = json.load(open(wp, encoding='utf-8'))
            TYPE_SUB = {
                'Cloth': 1, 'Leather': 2, 'Mail': 3, 'Plate': 4, 'Miscellaneous': 5,
                'Shield': 6, 'Libram': 7, 'Idol': 8, 'Totem': 9, 'Staff': 10,
                'One-Handed Axes': 11, 'Two-Handed Axes': 11, 'One-Handed Swords': 11,
                'Two-Handed Swords': 11, 'One-Handed Maces': 11, 'Two-Handed Maces': 11,
                'Dagger': 15, 'Gun': 3, 'Bow': 2, 'Crossbow': 18, 'Wand': 19,
                'Polearm': 6, 'Fist Weapon': 13, 'Fishing Pole': 20, 'Thrown': 2,
                'Cosmetic': 5,
            }
            added = 0
            for iid in sorted(quest_ids):
                if iid in out:
                    continue
                v = G.get(str(iid))
                if not v or (v.get('requiredLevel') or 0) > 60:
                    continue
                if v.get('classId') not in (2, 4):
                    continue
                out[iid] = {
                    's': BIT_TASK, 'n': v.get('name') or '', 'd': 'T',
                    'q': v.get('quality') if v.get('quality') is not None else 1,
                    'c': v.get('classId'), 'v': TYPE_SUB.get(v.get('type'), 5),
                    't': SLOT.get(v.get('slot'), '杂'),
                    'l': v.get('itemLevel') or 0, 'r': v.get('requiredLevel') or 0,
                }
                stats['task'] += 1
                added += 1
            log('  wclbox 补齐任务奖励新装备: %d' % added)
        else:
            log('  未找到 wclbox 清单，跳过新装备补齐')

    version = 'qg-src-' + datetime.datetime.now().strftime('%Y%m%d-%H%M')
    lines = [
        '-- QuestGear 装备来源数据表（build_sources.py 自动生成，勿手改）',
        '-- 数据源: CMaNGOS classic-db (GPL-3.0, 事实数据重表达, 不分发源文件)',
        '--          + 本项目 QuestGearData.lua (任务类权威源)',
        '--          + wclbox 图鉴清单（仅补任务奖励新装备的中文名/品质/槽位）',
        '-- 字段: [itemId]={s=来源位掩码(1任务/2副本/4世界/8NPC/16其他),n=中文名,d=详情,',
        '--        q=品质,c=类别(2武器/4护甲),v=子类,t=槽位,l=装等,r=需求等级}',
        'QuestGearSourcesMeta = {v="%s",built="%s",count=%d,task=%d,dungeon=%d,world=%d,npc=%d,other=%d}' % (
            version, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), len(out),
            stats['task'], stats['dungeon'], stats['world'], stats['npc'], stats['other']),
        '',
        'QuestGearSources = {',
    ]
    for iid in sorted(out):
        o = out[iid]
        d = o['d'].replace('\\', '').replace('"', '').replace('|', '/')
        n = (o['n'] or '').replace('\\', '').replace('"', '')
        lines.append('  [%d]={s=%d,n="%s",d="%s",q=%d,c=%d,v=%d,t="%s",l=%d,r=%d},' % (
            iid, o['s'], n, d, o['q'], o['c'], o['v'], o['t'], o['l'], o['r']))
    lines.append('}')
    dest = os.path.join(ROOT, 'QuestGearSources.lua')
    tmp = dest + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, dest)
    log('已生成 %s (%d 条, %.1f KB)' % (dest, len(out), os.path.getsize(dest)/1024))


if __name__ == '__main__':
    main()
