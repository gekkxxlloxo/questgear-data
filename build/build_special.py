# -*- coding: utf-8 -*-
"""QG 特殊来源构建器（v1.79）。

产出两个数据表 + 一份待人工核对清单：
  QuestGearStartItems.lua  角色创建自带装备（CharStartOutfit.dbc，1.12 客户端结构）
  QuestGearExtras.lua      其余「未知」但有 CMaNGOS 关联记录的物品（任务/法术/邮件）
  未分类装备清单.txt         CMaNGOS 中查不到任何关联的物品，供人工/豆包补来源

数据源（已下载到 _research/，只重表达事实数据，不分发源文件）：
  CharStartOutfit.dbc       L4G_Dbc 仓库的 1.12 DBC
  ClassicDB_base.sql        quest_template / spell_template / *_loot_template
  locales_quest_zh.sql      任务中文名
  locales_item_zh.sql       物品中文名
  QuestGearSources.lua      当前已知来源表
  QuestGearCrafts.lua       已归类为专业制造的物品

用法：python build_special.py
"""
import os, re, struct, datetime
from collections import defaultdict
from build_quest_info import insert_rows, unquote, clean_text, lua_str

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, '_research')

# 客户端 DBC 用连续 race ID（不是服务器种族掩码）
RACE = {1: '人类', 2: '兽人', 3: '矮人', 4: '暗夜精灵', 5: '亡灵', 6: '牛头人',
        7: '侏儒', 8: '巨魔', 9: '地精', 10: '血精灵', 11: '德莱尼', 12: '熊猫人'}
CLASS = {1: '战士', 2: '圣骑士', 3: '猎人', 4: '潜行者', 5: '牧师', 6: '死亡骑士',
         7: '萨满', 8: '法师', 9: '术士', 10: '武僧', 11: '德鲁伊'}


def read(p):
    with open(p, encoding='utf-8', errors='replace') as f:
        return f.read()


def parse_sources():
    src = read(os.path.join(ROOT, 'QuestGearSources.lua'))
    out = {}
    for m in re.finditer(r'^  \[(\d+)\]=\{s=(\d+),n="([^"]*)"(.*?)\},?$', src, re.M):
        iid = int(m.group(1))
        tail = m.group(4)
        l = re.search(r'\bl=(\d+)', tail)
        r = re.search(r'\br=(\d+)', tail)
        out[iid] = {'s': int(m.group(2)), 'n': m.group(3),
                    'l': int(l.group(1)) if l else 0,
                    'r': int(r.group(1)) if r else 0}
    return out


def parse_crafts():
    src = read(os.path.join(ROOT, 'QuestGearCrafts.lua'))
    return set(int(x) for x in re.findall(r'^  \[(\d+)\]=\{', src, re.M))


def parse_locale_items():
    sql = read(os.path.join(RES, 'locales_item_zh.sql'))
    out = {}
    for m in re.finditer(r"\((\d+),\s*'([^']*)'", sql):
        out[int(m.group(1))] = clean_text(m.group(2))
    return out


def parse_locale_quests():
    sql = read(os.path.join(RES, 'locales_quest_zh.sql'))
    out = {}
    for m in re.finditer(r"\((\d+),\s*'([^']*)'", sql):
        out[int(m.group(1))] = clean_text(m.group(2))
    return out


def parse_item_english():
    sql = read(os.path.join(RES, 'ClassicDB_base.sql'))
    out = {}
    for cs, vs in insert_rows(sql, 'item_template'):
        if len(vs) != len(cs):
            continue
        d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
        try:
            out[int(d.get('entry', 0))] = clean_text(d.get('name', ''))
        except ValueError:
            pass
    return out


def parse_start_items():
    """1.12 CharStartOutfit.dbc：第 1 字段 id，第 2 字段 race/class/sex/outfit 各 1 字节，
    字段 2..13 为 12 个物品槽，字段 14..25 为对应 displayId，26..37 为 inventoryType。"""
    data = open(os.path.join(RES, 'CharStartOutfit.dbc'), 'rb').read()
    magic, rc, fc, rs, sbs = struct.unpack('<4sIIII', data[:20])
    if magic != b'WDBC':
        raise RuntimeError('CharStartOutfit.dbc 格式错误')
    by_item = defaultdict(set)
    for i in range(rc):
        vals = struct.unpack('<%dI' % (rs // 4), data[20 + i * rs:20 + (i + 1) * rs])
        ident = vals[1]
        race, cls = ident & 0xFF, (ident >> 8) & 0xFF
        for v in vals[2:14]:
            if 0 < v < 0xFFFFFFFE:
                by_item[v].add((race, cls))
    return by_item


def combos_text(pairs):
    by_race = defaultdict(list)
    for race, cls in sorted(pairs):
        cn = CLASS.get(cls)
        if cn and cn not in by_race[race]:
            by_race[race].append(cn)
    parts = []
    for race in sorted(by_race, key=lambda x: (x not in RACE, x)):
        rc = RACE.get(race, '种族' + str(race))
        parts.append(rc + '：' + '/'.join(by_race[race]))
    s = '；'.join(parts[:5])
    if len(parts) > 5:
        s += ' 等'
    return s


def parse_refs():
    sql = read(os.path.join(RES, 'ClassicDB_base.sql'))
    quest_of = defaultdict(set)
    for cs, vs in insert_rows(sql, 'quest_template'):
        if len(vs) != len(cs):
            continue
        d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
        qid = d.get('Id') or d.get('entry')
        for k in ('RewItemId1', 'RewItemId2', 'RewItemId3', 'RewItemId4',
                  'RewChoiceItemId1', 'RewChoiceItemId2', 'RewChoiceItemId3',
                  'RewChoiceItemId4', 'RewChoiceItemId5', 'RewChoiceItemId6',
                  'SrcItemId'):
            v = d.get(k, '0')
            if v not in ('0', '', None):
                try:
                    quest_of[int(v)].add(int(qid))
                except ValueError:
                    pass
    spell_of = defaultdict(set)
    for cs, vs in insert_rows(sql, 'spell_template'):
        if len(vs) != len(cs):
            continue
        d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
        for n in (1, 2, 3):
            v = d.get('EffectItemType%d' % n, '0')
            if v not in ('0', '', None):
                try:
                    spell_of[int(v)].add(clean_text(d.get('SpellName', '')))
                except ValueError:
                    pass
    loot = set()
    mail = set()
    for table, target in (('creature_loot_template', loot),
                          ('gameobject_loot_template', loot),
                          ('npc_vendor', loot),
                          ('mail_loot_template', mail)):
        for cs, vs in insert_rows(sql, table):
            if len(vs) != len(cs):
                continue
            d = {c: unquote(vs[i]) for i, c in enumerate(cs)}
            if d.get('item', '0') not in ('0', '', None):
                try:
                    target.add(int(d['item']))
                except ValueError:
                    pass
    return quest_of, spell_of, loot, mail


def main():
    sources = parse_sources()
    crafts = parse_crafts()
    item_cn = parse_locale_items()
    item_en = parse_item_english()
    quest_cn = parse_locale_quests()
    starts = parse_start_items()
    quest_of, spell_of, loot, mail = parse_refs()

    # 只保留 QG 装备集里的起始物品；即便已有其它来源也保留，作为叠加位
    start_ids = sorted(i for i in starts if i in sources)
    lines = [
        '-- QuestGear 角色创建自带装备表（build_special.py 自动生成，勿手改）',
        '-- 来源：CharStartOutfit.dbc（经典 1.12 客户端起始装束），字段 2..13 的物品槽',
        '-- 说明：这是客户端 DBC 的客观事实数据，不是 item_template.flags 猜测。',
        'QuestGearStartItemsMeta = {v="qgsi-1",count=%d,built="%s"}' % (
            len(start_ids), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        '',
        'QuestGearStartItems = {',
    ]
    for iid in start_ids:
        who = combos_text(starts[iid])
        lines.append('  [%d]={n=%s,who=%s},' % (
            iid, lua_str(sources[iid]['n']), lua_str(who)))
    lines.append('}')
    lines.append('')
    open(os.path.join(ROOT, 'QuestGearStartItems.lua'), 'w', encoding='utf-8').write('\n'.join(lines))

    # 其余未知：有 CMaNGOS 关联记录的补详情；完全无关联的输出清单
    unknown = {i for i, o in sources.items() if o['s'] == 16 and i not in crafts and i not in starts}
    extras = []
    for iid in sorted(unknown):
        bit, det = 0, ''
        qs = sorted(quest_of.get(iid, ()))
        if qs:
            names = [quest_cn.get(q, ('任务' + str(q))) for q in qs[:3]]
            det = '任务获取：' + '、'.join(names)
            if len(qs) > 3:
                det += ' 等%d个任务' % len(qs)
            bit = 1
        elif iid in loot:
            det = '掉落/商人：creature_loot_template 或 npc_vendor 有引用'
            bit = 4
        elif iid in mail:
            det = '活动/邮件奖励：mail_loot_template 有引用'
        elif spell_of.get(iid):
            names = sorted(spell_of[iid])
            det = '法术生成：' + '、'.join(names[:2])
        if det:
            extras.append((iid, bit, det))

    lines = [
        '-- QuestGear 其它特殊来源补充表（build_special.py 自动生成，勿手改）',
        '-- b=要叠加的来源位（1任务/4世界掉落），d=详情文字；无 b 表示仍留在「其他」但不再显示未知',
        'QuestGearExtrasMeta = {v="qge-1",count=%d,built="%s"}' % (
            len(extras), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        '',
        'QuestGearExtras = {',
    ]
    for iid, bit, det in extras:
        lines.append('  [%d]={b=%d,d=%s},' % (iid, bit, lua_str(det)))
    lines.append('}')
    lines.append('')
    open(os.path.join(ROOT, 'QuestGearExtras.lua'), 'w', encoding='utf-8').write('\n'.join(lines))

    pure = sorted(i for i in unknown if i not in {e[0] for e in extras})
    out = [
        'QuestGear：CMaNGOS 中查不到来源关联的装备清单',
        '生成时间：' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '说明：这些物品在 ClassicDB_base.sql 的掉落/任务奖励/商人/配方/邮件表中均无引用，',
        '      也不在 CharStartOutfit.dbc 起始装束里。可能是 GM/测试/未实装/旧版本遗留物品。',
        '      共 %d 件。可把本清单交给豆包逐批补来源。' % len(pure),
        '',
        'ID\t中文名\t英文名\t装等\t需求等级',
    ]
    for iid in pure:
        o = sources[iid]
        out.append('%d\t%s\t%s\t%d\t%d' % (
            iid, o['n'], item_en.get(iid, ''), o['l'], o['r']))
    open(os.path.join(ROOT, '未分类装备清单.txt'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')

    print('起始装备 %d 件 / 特殊补充 %d 条 / 完全未知 %d 件' % (
        len(start_ids), len(extras), len(pure)))
    print('样例 56:', [x for x in lines if x.startswith('  [56]=')] or '不在新表中')


if __name__ == '__main__':
    main()
