# -*- coding: utf-8 -*-
"""QG 专业制造来源表构建器（v1.77）。

豆包查「雕花皮外衣 ID2300」时给出的信息是「制皮专业制造，不是掉落/任务，
所以插件显示未知来源」。CMaNGOS 基础库其实有完整配方链，只是 QG 之前的
build_sources.py 只统计 loot/vendor/quest，没读配方表。本脚本沿以下机械链补齐：

  制造 spell (Effect=24, EffectItemType=itemId)
    → 教学 spell (Effect=36, EffectTriggerSpell=制造spellId)
      → npc_trainer (spell=教学spellId) → reqskill/reqskillvalue/NPC entry
        → creature_template / locales_creature 取 NPC 中文名
        → QuestDB Forever NPCSpawns 取百分比坐标

材料来自制造 spell 的 Reagent1..8 / ReagentCount1..8 + locales_item 中文名。

用法：python build_crafts.py
输出：QuestGearCrafts.lua
"""
import os, re, zipfile, datetime
from build_quest_info import insert_rows, table_columns, unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, '_research')

# SkillLine ID → 中文专业名（1.12 经典旧世）
SKILL_NAMES = {
    40: '毒药', 129: '附魔', 164: '锻造', 165: '制皮', 171: '炼金',
    185: '烹饪', 197: '裁缝', 202: '工程', 333: '附魔',
}
# uiMapID → 中文地名（只覆盖训练师常见出生地；其余留空不显示）
MAP_NAMES = {
    1411: '泰达希尔', 1412: '莫高雷', 1413: '丹莫罗', 1414: '提瑞斯法林地',
    1415: '西瘟疫之地', 1416: '希尔斯布莱德丘陵', 1417: '赤脊山', 1418: '千针石林',
    1419: '奥特兰克山脉', 1420: '阿拉希高地', 1421: '荆棘谷', 1422: '尘泥沼泽',
    1423: '荒芜之地', 1424: '凄凉之地', 1425: '悲伤沼泽', 1426: '菲拉斯',
    1427: '塔纳利斯', 1428: '暮色森林', 1429: '湿地', 1430: '艾萨拉',
    1431: '费拉斯', 1432: '诅咒之地', 1433: '赤脊山', 1434: '石爪山脉',
    1435: '冬泉谷', 1436: '希利苏斯', 1437: '黑石山', 1438: '杜隆塔尔',
    1439: '贫瘠之地', 1440: '洛克莫丹', 1441: '暮色森林', 1442: '赤脊山',
    1443: '提瑞斯法林地', 1444: '银松森林', 1445: '奥特兰克山脉', 1446: '灼热峡谷',
    1447: '燃烧平原', 1448: '通灵学院', 1449: '斯坦索姆', 1450: '厄运之槌',
    1451: '黑石塔', 1452: '铁炉堡', 1453: '暴风城', 1454: '奥格瑞玛',
    1455: '雷霆崖', 1456: '幽暗城', 1457: '达纳苏斯', 1458: '闪金镇',
    1459: '湖畔镇',
}


def lua_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def main():
    sql_path = os.path.join(RES, 'ClassicDB_base.sql')
    izh = open(os.path.join(RES, 'locales_item_zh.sql'), encoding='utf-8', errors='replace').read()
    czh = open(os.path.join(RES, 'locales_creature_zh.sql'), encoding='utf-8', errors='replace').read()
    sql = open(sql_path, encoding='utf-8', errors='replace').read()
    src_path = os.path.join(ROOT, 'QuestGearSources.lua')
    sources_lua = open(src_path, encoding='utf-8').read()

    # 只处理来源表里已有的有效 60 级装备
    valid_ids = set(int(x) for x in re.findall(r'^  \[(\d+)\]=\{', sources_lua, re.M))
    print('有效装备 %d 件' % len(valid_ids))

    # 中文名
    item_cn, npc_cn = {}, {}
    m = re.search(r'INSERT INTO `locales_item`.*?VALUES', izh, re.S)
    for mm in re.finditer(r"\((\d+),\s*'([^']*)'", izh):
        item_cn[int(mm.group(1))] = mm.group(2)
    for mm in re.finditer(r"\((\d+),\s*'([^']*)'", czh):
        npc_cn[int(mm.group(1))] = mm.group(2)

    # QuestDB Forever NPCSpawns / Zones：NPC → 百分比坐标 + 区域
    npc_pos, zone_map = {}, {}
    zp = os.path.join(RES, 'QuestDB-v0.1.0.zip')
    if os.path.exists(zp):
        z = zipfile.ZipFile(zp)
        sp = [n for n in z.namelist() if 'Forever/_core/NPCSpawns.lua' in n]
        zn = [n for n in z.namelist() if 'Forever/_core/Zones.lua' in n]
        if zn:
            for mm in re.finditer(r'\[(\d+)\]="([^"]*)"', z.read(zn[0]).decode('utf-8', 'replace')):
                parts = re.split(r'\\031|\x19', mm.group(2))
                if len(parts) >= 2 and parts[1].isdigit():
                    zone_map[int(mm.group(1))] = int(parts[1])
        if sp:
            for mm in re.finditer(r'\[(\d+)\]="([^"]*)"', z.read(sp[0]).decode('utf-8', 'replace')):
                vals = mm.group(2).split(',')
                if len(vals) == 2 and ':' in vals[0]:
                    zid, xy = vals[0].split(':', 1)
                    try:
                        npc_pos[int(mm.group(1))] = (int(zid), int(xy) / 100.0, int(vals[1]) / 100.0)
                    except ValueError:
                        pass
        print('QuestDB NPC 坐标 %d 条 / 区域 %d 条' % (len(npc_pos), len(zone_map)))

    # 制造 spell：Effect{n}=24（CREATE_ITEM）
    craft_by_item = {}
    for cs, vs in insert_rows(sql, 'spell_template'):
        if len(vs) != len(cs):
            continue
        d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
        for n in (1, 2, 3):
            if d.get('Effect%d' % n) != '24':
                continue
            try:
                iid = int(d.get('EffectItemType%d' % n) or 0)
            except ValueError:
                continue
            if iid not in valid_ids or iid in craft_by_item:
                continue
            mats = []
            for k in range(1, 9):
                rid = int(d.get('Reagent%d' % k) or 0)
                cnt = int(d.get('ReagentCount%d' % k) or 0)
                if rid and cnt:
                    mats.append((rid, item_cn.get(rid, ''), cnt))
            if mats:
                craft_by_item[iid] = {'spell': int(d['Id']), 'm': mats}
            break
    print('制造配方 %d 条（有材料）' % len(craft_by_item))

    # 教学 spell：Effect{n}=36（LEARN_SPELL），EffectTriggerSpell{n}=制造 spellId
    teach = {}
    for cs, vs in insert_rows(sql, 'spell_template'):
        if len(vs) != len(cs):
            continue
        d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
        for n in (1, 2, 3):
            try:
                target = int(d.get('EffectTriggerSpell%d' % n) or 0)
            except ValueError:
                continue
            if d.get('Effect%d' % n) == '36' and target in set(x['spell'] for x in craft_by_item.values()):
                teach[target] = int(d['Id'])
                break

    # npc_trainer：教学 spell → [(NPC, 专业, 技能点)]（同一 NPC 会教多个 spell，必须按 spell 分组）
    trainer = {}
    teach_ids = set(teach.values())
    for cs, vs in insert_rows(sql, 'npc_trainer'):
        if len(vs) != len(cs):
            continue
        d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
        try:
            sid, entry = int(d.get('spell') or 0), int(d.get('entry') or 0)
        except ValueError:
            continue
        if sid not in teach_ids:
            continue
        skill = int(d.get('reqskill') or 0)
        rank = int(d.get('reqskillvalue') or 0)
        trainer.setdefault(sid, []).append((entry, skill, rank))
    print('教学 spell %d 条 / 教学记录 %d 条' % (len(teach), sum(len(v) for v in trainer.values())))

    # creature_template Faction → 阵营（用于 UI 按玩家阵营选训练师）
    npc_faction = {}
    for cs, vs in insert_rows(sql, 'creature_template'):
        if len(vs) != len(cs):
            continue
        d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
        try:
            npc_faction[int(d.get('Entry') or 0)] = int(d.get('Faction') or 0)
        except ValueError:
            pass
    ALLY_FACTIONS = {1, 10, 12, 29, 32, 35, 55, 56, 67, 68, 72, 80}
    HORDE_FACTIONS = {5, 6, 8, 14, 22, 26, 27, 28, 30, 76, 81, 104, 105, 106, 107, 108, 109, 110}

    # 组装：一件装备收集有坐标的训练师（最多 3 位，副本按阵营去重）
    out = {}
    for iid, info in craft_by_item.items():
        tid = teach.get(info['spell'])
        cand = trainer.get(tid, []) if tid else []
        prof = SKILL_NAMES.get(cand[0][1], '') if cand else ''
        rank = min(x[2] for x in cand) if cand else 0
        mats = [(n, c) for _, n, c in info['m']]
        rec = {'p': prof, 'r': rank, 'm': mats, 't': []}
        seen_g, seen_n = set(), set()
        for e, _, _ in sorted(cand, key=lambda x: x[2]):
            pos = npc_pos.get(e)
            if not pos or pos[0] not in zone_map:
                continue
            nm = npc_cn.get(e, '')
            if not nm or nm in seen_n:
                continue
            fac = npc_faction.get(e, 0)
            g = 1 if fac in ALLY_FACTIONS else (2 if fac in HORDE_FACTIONS else 0)
            if g and g in seen_g:
                continue
            if len(rec['t']) >= 3:
                break
            seen_n.add(nm)
            if g: seen_g.add(g)
            _, x, y = pos
            rec['t'].append({'n': nm, 'x': round(x, 1), 'y': round(y, 1),
                             'z': MAP_NAMES.get(zone_map[pos[0]], ''), 'g': g})
        out[iid] = rec

    lines = [
        '-- QuestGear 专业制造表（build_crafts.py 自动生成，勿手改）',
        '-- 源: CMaNGOS classic-db spell_template + npc_trainer + locales/Chinese + QuestDB Forever NPCSpawns',
        '-- 链: 制造spell(Effect24/EffectItemType) → 教学spell(Effect36/TriggerSpell) → npc_trainer → NPC坐标',
        '-- 字段: p=专业 r=技能点 m=材料(名/数量) n=训练师 x/y=百分比坐标 z=地名',
        'QuestGearCrafts = {',
    ]
    for iid in sorted(out):
        r = out[iid]
        parts = ['p=%s' % lua_str(r['p']), 'r=%d' % r['r']]
        parts.append('m={' + ','.join('{n=%s,c=%d}' % (lua_str(n), c) for n, c in r['m']) + '}')
        if r['t']:
            ts = []
            for t in r['t']:
                ts.append('{n=%s,x=%s,y=%s,z=%s,g=%d}' % (
                    lua_str(t['n']), t['x'], t['y'], lua_str(t['z']), t['g']))
            parts.append('t={' + ','.join(ts) + '}')
        lines.append('  [%d]={%s},' % (iid, ','.join(parts)))
    lines.append('}')
    lines.append('QuestGearCraftsMeta = {v="qgc-cmangos-1",count=%d,built="%s"}' %
                 (len(out), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    dst = os.path.join(ROOT, 'QuestGearCrafts.lua')
    with open(dst, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('\n'.join(lines) + '\n')
    print('已生成 %s：%d 条，%d 字节' % (dst, len(out), os.path.getsize(dst)))
    s2300 = [l for l in lines if l.startswith('  [2300]=')]
    print('样例 [2300]:', s2300[0] if s2300 else '缺失')


if __name__ == '__main__':
    main()
