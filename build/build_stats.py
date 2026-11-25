# -*- coding: utf-8 -*-
"""从 items-quality-full.json 烘焙任务装备属性表 QuestGearStats.lua。

- 只收录 QuestGearData.lua 里出现过的 itemID（插件筛选只用到这些）。
- 值用 |key|key| 的紧凑集合串，Lua 端用 string.find(set, "|key|", 1, true) 判定，
  不依赖 bit 库（怀旧服 Lua 5.1 没有标准位运算）。
- 独立文件，不被每日同步的 QuestGearData.lua 覆盖；toc 里先于 QuestGear.lua 加载。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# key -> tooltip 里 "+N <名字>" 的英文名
STATS = {
    "str": "Strength",
    "agi": "Agility",
    "sta": "Stamina",
    "int": "Intellect",
    "spi": "Spirit",
    "fire": "Fire Resistance",
    "frost": "Frost Resistance",
    "nature": "Nature Resistance",
    "shadow": "Shadow Resistance",
    "arcane": "Arcane Resistance",
}


def main():
    data = open(os.path.join(HERE, 'QuestGearData.lua'), encoding='utf-8').read()
    ids = set(int(x) for x in re.findall(r'\bi=(\d+)', data))
    items = json.load(open(os.path.join(HERE, 'items-quality-full.json'), encoding='utf-8'))
    by_id = {it['itemId']: it for it in items}

    out = {}
    for iid in sorted(ids):
        it = by_id.get(iid)
        if not it:
            continue
        keys = []
        for t in it.get('tooltip') or []:
            label = str(t.get('label') or '').strip()
            m = re.match(r'^\+[\d,]+ (.+?)\.?$', label)
            if not m:
                continue
            name = m.group(1).strip()
            for key, ename in STATS.items():
                if name == ename and key not in keys:
                    keys.append(key)
        if keys:
            out[iid] = keys

    lines = [
        "-- QuestGearStats：任务装备属性烘焙表（由 build_stats.py 生成，勿手改）",
        "-- 值格式 |key|key|：str力量 agi敏捷 sta耐力 int智力 spi精神 fire/frost/nature/shadow/arcane 抗性",
        "QuestGearStats = {",
    ]
    for iid in sorted(out):
        lines.append('  [%d]="|%s|",' % (iid, '|'.join(out[iid])))
    lines.append('}')
    lines.append('')
    path = os.path.join(HERE, 'QuestGearStats.lua')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('生成 %s：%d 件装备有属性，%d 字节' % (path, len(out), os.path.getsize(path)))


if __name__ == '__main__':
    main()
