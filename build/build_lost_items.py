# -*- coding: utf-8 -*-
"""QG 无来源装备分类构建器（v1.80）。

输入：build_special.py 产出的「未分类装备清单.txt」（CMaNGOS 无任何投放关联的物品）
输出：把分类说明并入 QuestGearExtras.lua（保留 build_special.py 已有的机械补漏条目），
      并重写 未分类装备清单.txt（增加「分类」列）。

分类只依据机械可复核的规则：物品英文名/中文名关键字。不采信聊天机器人给出的
「CMaNGOS flags 标记」「整张军衔表缺失」「某站标注私服来源」等说法——这些均已核实不成立
（详见 README / 工作日志）。分类说明里明确区分「原版经典服规则」与「私服可自定义投放」。

用法：python build_special.py && python build_lost_items.py
"""
import os, re, datetime
from collections import Counter
from build_special import parse_sources, parse_item_english, read
from build_quest_info import lua_str

ROOT = os.path.dirname(os.path.abspath(__file__))

# 分类码 -> (短标签, 详情说明)。说明不写死未经证实的投放，只给可核对的方向。
CATS = {
    'GM':    ('GM测试', 'GM测试装备：暴雪内部专用，正式服无正常获取途径；私服一般 GM 命令 .additem 生成'),
    'PH':    ('开发占位', '开发占位道具 [PH]：暴雪版本开发期预留、未实装投放，正式服无获取'),
    'RANK':  ('荣誉军衔', '荣誉军衔/战场奖励：正式服由对应阵营军需官按军衔或战场声望兑换；本地 CMaNGOS 未收录该批映射'),
    'FEST':  ('节日/玩具', '节日或玩具彩蛋：多数为万圣节/节日活动物品；本地 CMaNGOS 未收录节日专属 loot 表'),
    'BLOOD': ('血帆声望', '血帆海盗声望装：正式服需血帆海盗声望达标后向营地商人购买；本地 CMaNGOS 未收录该商人表'),
    'TEST':  ('测试/模型', '暴雪内部测试或模型展示道具：仅客户端保留资源，正式服无投放'),
    'GONE':  ('废弃未实装', '废弃/未实装：早期设计稿或砍掉的掉落，正式服无获取；私服若有则由服主自定义投放，开源库查不到'),
}

# 顺序敏感：先特殊后兜底
def classify(iid, cn, en):
    n = (en or '').lower()
    c = cn or ''
    if 'gamemaster' in n or n.startswith('gm'):
        return 'GM'
    if '[ph]' in n:
        return 'PH'
    if 'bloodsail' in n or '血帆' in c:
        return 'BLOOD'
    rank = ('knight-lieutenant', 'knight-captain', 'lieutenant commander', "lieutenant commander's",
            'blood guard', "champion's", "legionnaire's", "centurion's", "sergeant's mark",
            "warrior's honor", "defiler's")
    if any(k in n for k in rank) or any(k in c for k in ('骑士中尉','骑士队长','少校','护卫骑士','血卫士','勇士','军团士兵','百夫长','污染者','冠军战袍')):
        return 'RANK'
    if 'pvp' in n or 'pvp' in c:
        return 'RANK'
    if 'mask' in n or '面具' in c or 'mood ring' in n or 'fishing hat' in n or '心境之戒' in c or '渔帽' in c:
        return 'FEST'
    test = ('twain', 'aura proc', "engineer's shield", 'chilton wand', 'shadow sword',
            'nature sword', 'frost bracers', 'orb of fire', 'flimsy', 'sturdy')
    if any(k in n for k in test):
        return 'TEST'
    return 'GONE'


def parse_existing_extras():
    """读回 build_special.py 生成的补漏条目，避免覆盖。"""
    p = os.path.join(ROOT, 'QuestGearExtras.lua')
    if not os.path.exists(p):
        return []
    src = read(p)
    out = {}
    for m in re.finditer(r'^  \[(\d+)\]=\{b=(\d+),d="([^"]*)"\},?$', src, re.M):
        out[int(m.group(1))] = (int(m.group(2)), m.group(3))
    return out


def main():
    sources = parse_sources()
    item_en = parse_item_english()
    existing = parse_existing_extras()

    # 读清单里的 ID（ Defense: 只取数字行）
    p = os.path.join(ROOT, '未分类装备清单.txt')
    ids = []
    for line in read(p).splitlines():
        m = re.match(r'^(\d+)\t', line)
        if m:
            ids.append(int(m.group(1)))

    cats = {}
    for iid in ids:
        o = sources.get(iid, {})
        code = classify(iid, o.get('n', ''), item_en.get(iid, ''))
        cats[iid] = code

    # 合并：已有机械补漏 + 新分类（新分类不覆盖已有 b 位补漏，仅当完全空缺时写 b=0）
    merged = dict(existing)
    for iid, code in cats.items():
        if iid in merged:
            continue  # 已有更精确的补漏详情（如任务获取）保留
        label, desc = CATS[code]
        merged[iid] = (0, '[%s] %s' % (label, desc))

    lines = [
        '-- QuestGear 其它来源补充表（build_special.py + build_lost_items.py 自动生成，勿手改）',
        '-- b=要叠加的来源位（1任务/4世界掉落），b=0 表示仍留在「其他」但显示分类详情',
        'QuestGearExtrasMeta = {v="qge-2",count=%d,built="%s"}' % (
            len(merged), datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        '',
        'QuestGearExtras = {',
    ]
    for iid in sorted(merged):
        b, d = merged[iid]
        lines.append('  [%d]={b=%d,d=%s},' % (iid, b, lua_str(d)))
    lines.append('}')
    lines.append('')
    open(os.path.join(ROOT, 'QuestGearExtras.lua'), 'w', encoding='utf-8').write('\n'.join(lines))

    # 重写清单，加分类列；统计
    cnt = Counter(cats.values())
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    out = [
        'QuestGear：CMaNGOS 中查不到投放关联的装备分类清单',
        '生成时间：' + now,
        '分类依据：物品英文名/中文名关键字机械匹配（不采信未证实的证据链）。',
        '说明：原版经典服无正常获取途径；私服若放出，位置由服主自定义，开源库查不到。',
        '      共 %d 件，分类统计见下。可把本清单按分类交给豆包逐批核对。' % len(ids),
        '',
        '分类统计：',
    ]
    for code, (label, _) in CATS.items():
        out.append('  %s  %d 件' % (label, cnt.get(code, 0)))
    out += ['', 'ID\t分类\t中文名\t英文名\t装等\t需求等级']
    for iid in ids:
        o = sources.get(iid, {})
        out.append('%d\t%s\t%s\t%s\t%d\t%d' % (
            iid, CATS[cats[iid]][0], o.get('n', ''), item_en.get(iid, ''),
            o.get('l', 0), o.get('r', 0)))
    open(p, 'w', encoding='utf-8').write('\n'.join(out) + '\n')

    print('分类完成：', ', '.join('%s %d' % (CATS[c][0], cnt.get(c, 0)) for c in CATS))
    print('QuestGearExtras.lua 合计 %d 条（原有补漏 %d + 新分类 %d）' % (
        len(merged), len(existing), len(ids)))
    for iid in (2586, 21125, 16369, 22742, 20391, 6174, 12104):
        print('  %d -> %s' % (iid, CATS.get(cats.get(iid), ('?', ''))[0]))


if __name__ == '__main__':
    main()
