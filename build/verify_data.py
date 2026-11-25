# -*- coding: utf-8 -*-
"""QuestGear 数据完整性核验（回答「数据到底更没更全、全不全」）。

用法：
  python verify_data.py                 # 核验源码目录里的 QuestGearData.lua
  python verify_data.py --installed     # 同时核验游戏目录里的装机文件是否与源码一致
  python verify_data.py --file X.lua --expect-version V --skip-local-meta --skip-source
                                        # 校验任意候选文件（同步器写盘前调用）

检查项：
  1) 九张表齐全（Meta/Data/ByLevel/Rewards/Chains/Names/Zone/Pos/Starter）
  2) Meta 里声明的 tasks/gear/chains 与表内实数一致
  3) 每个任务等级 1..60；每个装备行 i/il/n/c 合法；无重复 (任务,物品)
  4) 六个等级段都有数据（1-10 ~ 51-60），低段不为空
  5) data_meta.json（本地同步版本标记）与 Meta.v 一致（若文件存在，skip_local_meta 可跳过）
  6) 装机文件 MD5 与源码一致（--installed）

作为模块：verify(path, expect_version=None, skip_meta=False, check_source=True)
返回 (problems, stats, md5)，供 qg_sync.py 在原子替换前校验候选文件。
"""
import os, re, sys, json, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from strict_wow import make_env2

INSTALL = r'C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns\QuestGear\QuestGearData.lua'
DATA = os.path.join(HERE, 'QuestGearData.lua')
LOCAL_META = os.path.join(HERE, 'data_meta.json')

REQUIRED = ['QuestGearMeta', 'QuestGearData', 'QuestGearByLevel', 'QuestGearRewards',
            'QuestGearChains', 'QuestGearNames', 'QuestGearZone', 'QuestGearPos',
            'QuestGearStarter']

# Lua 侧一次性跑完结构检查，避免大表跨语言传输
LUA_CHECK = r'''
local bad = {}
local function count(t) local n=0 for _ in pairs(t) do n=n+1 end return n end
local names = {"QuestGearMeta","QuestGearData","QuestGearByLevel","QuestGearRewards",
               "QuestGearChains","QuestGearNames","QuestGearZone","QuestGearPos","QuestGearStarter"}
for _,n in ipairs(names) do
  if type(_G[n]) ~= "table" then bad[#bad+1] = "缺表:"..n end
end
local gear, seen = 0, {}
for q,d in pairs(QuestGearData or {}) do
  if type(q) ~= "number" then bad[#bad+1] = "任务ID非数字:"..tostring(q) end
  if type(d.l) ~= "number" or d.l < 1 or d.l > 60 then
    bad[#bad+1] = "任务等级越界:"..tostring(q).."="..tostring(d.l)
  end
  if d.f ~= 0 and d.f ~= 1 and d.f ~= 2 and d.f ~= 3 then
    bad[#bad+1] = "阵营字段非法:"..tostring(q).."="..tostring(d.f)
  end
  local gcount = 0
  for _,g in ipairs(d.gear or {}) do
    gcount = gcount + 1; gear = gear + 1
    local key = q..":"..tostring(g.i)
    if seen[key] then bad[#bad+1] = "重复奖励:"..key end
    seen[key] = true
    if type(g.i) ~= "number" or g.i <= 0 then bad[#bad+1] = "物品ID非法:"..key end
    if type(g.n) ~= "string" or g.n == "" then bad[#bad+1] = "物品名缺失:"..key end
    if type(g.il) ~= "number" or g.il < 0 then bad[#bad+1] = "装等非法:"..key end
    if g.c ~= 2 and g.c ~= 4 then bad[#bad+1] = "物品类别非法:"..key end
  end
  if gcount == 0 then bad[#bad+1] = "任务无装备却进了主表:"..tostring(q) end
end
local bands = {}
for _,b in ipairs({1,11,21,31,41,51}) do
  bands[b] = count((QuestGearByLevel or {})[b] or {})
  if bands[b] == 0 then bad[#bad+1] = "等级段空:"..b end
end
local m = QuestGearMeta or {}
return table.concat({
  "v="..tostring(m.v), "built="..tostring(m.built), "source="..tostring(m.source),
  "tasks="..count(QuestGearData or {}), "meta_tasks="..tostring(m.tasks),
  "gear="..gear, "meta_gear="..tostring(m.gear),
  "chains="..count(QuestGearChains or {}), "meta_chains="..tostring(m.chains),
  "factions="..(function() local c={0,0,0,0} for _,d in pairs(QuestGearData or {}) do c[(d.f or 0)+1]=c[(d.f or 0)+1]+1 end return table.concat(c,"/") end)(),
  "rewards="..count(QuestGearRewards or {}), "pos="..count(QuestGearPos or {}),
  "bands="..table.concat((function() local t={} for _,b in ipairs({1,11,21,31,41,51}) do t[#t+1]=b..":"..bands[b] end return t end)(), ","),
  "bad="..#bad, table.concat(bad, "\n"),
}, "\n")
'''


def verify(path, expect_version=None, skip_meta=False, check_source=True, strict_errors=True,
           local_meta_path=None):
    """校验单个数据文件。返回 (problems, stats, md5)。
    expect_version: 期望的 Meta.v（同步器用远端 meta.version 传入）。
    skip_meta: 跳过本地 data_meta.json 版本比对（校验远端候选文件时必须为 True）。
    check_source: 是否要求 source commit 以 933ec77a 开头（CLI 默认 True）。
    strict_errors: 是否把 Lua 桩记录的错误计入失败。
    local_meta_path: 本地版本标记文件，默认模块级 LOCAL_META（测试可注入沙箱路径）。
    """
    problems = []
    def check(cond, msg):
        if not cond:
            problems.append(msg)

    raw = open(path, 'rb').read()
    md5 = hashlib.md5(raw).hexdigest()
    try:
        txt = raw.decode('utf-8')          # 严格解码：乱码/非 UTF-8 直接判失败
    except UnicodeDecodeError as e:
        return ['文件非 UTF-8（乱码）: %s' % e], {}, md5

    check('QuestGearMeta = {' in txt, '数据文件没有 Meta 头')
    lua, env = make_env2()
    try:
        lua.execute(txt)                   # 语法错 / 运行时错直接判失败
    except Exception as e:
        problems.append('Lua 加载失败: %s' % str(e)[:200])
    try:
        checks = lua.execute(LUA_CHECK) or ''
    except Exception as e:
        checks = ''
        problems.append('Lua 结构校验失败: %s' % str(e)[:200])

    stats = {}
    for line in checks.split('\n'):
        if '=' in line and not line.startswith(' '):
            k, v = line.split('=', 1)
            stats[k] = v
    for line in checks.split('\n'):
        if line.startswith(('任务', '缺表', '物品', '重复', '装等', '等级段')):
            problems.append(line)

    for k in ('tasks', 'gear', 'chains'):
        check(stats.get(k) == stats.get('meta_' + k),
              'Meta 声明的 %s=%s 与实际 %s 不一致' % (k, stats.get('meta_' + k), stats.get(k)))
    if check_source:
        check(stats.get('source', '').startswith('933ec77a'), '数据源 commit 与预期不符')
    if expect_version:
        check(stats.get('v') == expect_version,
              '数据版本 %s 与期望 %s 不一致' % (stats.get('v', '?'), expect_version))

    if strict_errors:
        for e in getattr(env, 'errs', []):
            problems.append('严格桩: ' + str(e))

    meta_file = local_meta_path or LOCAL_META
    if not skip_meta and os.path.exists(meta_file):
        try:
            lv = json.load(open(meta_file, encoding='utf-8')).get('version', '')
            check(lv == stats.get('v'),
                  'data_meta.json 版本 %s 与数据版本 %s 不一致' % (lv, stats.get('v')))
        except Exception as e:
            problems.append('data_meta.json 解析失败: %s' % e)
    return problems, stats, md5


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--installed', action='store_true')
    ap.add_argument('--file', help='校验任意候选数据文件')
    ap.add_argument('--expect-version')
    ap.add_argument('--skip-local-meta', action='store_true')
    ap.add_argument('--skip-source', action='store_true')
    a = ap.parse_args()

    target = a.file or DATA
    problems, stats, md5 = verify(
        target, expect_version=a.expect_version,
        skip_meta=a.skip_local_meta or bool(a.file),
        check_source=not a.skip_source)

    print('=' * 72)
    print('QuestGear 数据完整性核验：%s' % target)
    print('=' * 72)
    for k in ('v', 'built', 'source', 'tasks', 'gear', 'chains', 'factions', 'rewards', 'pos', 'bands'):
        print('  %-12s %s' % (k, stats.get(k, '?')))
    print('  md5          %s' % md5)

    if a.installed and not a.file:
        if os.path.exists(INSTALL):
            imd5 = hashlib.md5(open(INSTALL, 'rb').read()).hexdigest()
            if imd5 != md5:
                problems.append('装机文件与源码 MD5 不一致：%s vs %s' % (imd5, md5))
            print('  installed    %s (%s)' % (imd5, '一致' if imd5 == md5 else '不一致'))
        else:
            problems.append('装机文件不存在: ' + INSTALL)

    if problems:
        print('\n失败 %d 项：' % len(problems))
        for p in problems[:30]:
            print('  -', p)
        return 1
    print('\n结论：数据完整（%s 任务 / %s 条装备奖励 / %s 条任务链），各等级段齐全 ✓'
          % (stats.get('tasks'), stats.get('gear'), stats.get('chains')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
