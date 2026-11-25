# -*- coding: utf-8 -*-
"""QG 任务详情补充表构建器（v1.76）。

目的：把豆包能查到的 CMaNGOS 任务字段（中文目标/前置/需求物品/三选一奖励）
补进插件，不替换 QuestieDB 的 1219 个任务链与坐标数据。

数据源（均为已下载到 _research/ 的事实数据，重新表达为自有格式，不分发源文件）：
  - ClassicDB_base.sql        quest_template（入口/前置/需求物品/奖励物品）
  - locales_quest_zh.sql      locales/Chinese/locales_quest.sql（中文标题/描述/目标）
  - locales_item_zh.sql       locales/Chinese/locales_item.sql（物品中文名）
  - QuestGearData.lua         任务 ID 清单 + 阵营字段 f

用法：python build_quest_info.py
输出：QuestGearQuestInfo.lua
"""
import os, re, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, '_research')


# ---------- SQL 通用解析（正确处理引号内逗号/反斜杠） ----------
def split_tuples(body):
    out, buf, quote, esc, depth = [], [], False, False, 0
    for ch in body:
        if esc:
            buf.append(ch); esc = False; continue
        if ch == '\\':
            buf.append(ch); esc = True; continue
        if ch == "'":
            quote = not quote; buf.append(ch); continue
        if not quote:
            if ch == '(':
                depth += 1
                if depth == 1:
                    buf = []; continue
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    out.append(''.join(buf)); buf = []; continue
        buf.append(ch)
    return out


def split_values(s):
    out, buf, quote, esc = [], [], False, False
    for ch in s:
        if esc:
            buf.append(ch); esc = False; continue
        if ch == '\\':
            buf.append(ch); esc = True; continue
        if ch == "'":
            quote = not quote; buf.append(ch); continue
        if ch == ',' and not quote:
            out.append(''.join(buf).strip()); buf = []; continue
        buf.append(ch)
    if buf:
        out.append(''.join(buf).strip())
    return out


def unquote(v):
    v = v.strip()
    if v.upper() == 'NULL':
        return ''
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        v = v[1:-1]
        # SQL 转义：'' -> '，\' -> '
        v = v.replace("\\'", "'").replace('""', '"')
        return v
    return v


def table_columns(sql, table):
    """从 CREATE TABLE 读取列顺序（INSERT 无列头时必须靠它对齐）。"""
    m = re.search(r'CREATE\s+TABLE\s+`?' + re.escape(table) + r'`?\s*\((.*?)\)\s*ENGINE',
                  sql, re.S | re.I)
    if not m:
        return []
    return [c.strip().strip('`') for c in re.findall(r'^\s*`(\w+)`\s+\w', m.group(1), re.M)]


def insert_rows(sql, table):
    """返回 [(列名list, 原始值list)]。"""
    rows = []
    create_cols = table_columns(sql, table)
    pat = re.compile(r'INSERT\s+INTO\s+`?' + re.escape(table) + r'`?\s*(\([^)]*\))?\s*VALUES\s*(.*?);\s*(?:\n|$)',
                     re.S | re.I)
    for m in pat.finditer(sql):
        cols = []
        if m.group(1):
            cols = [c.strip().strip('`') for c in m.group(1)[1:-1].split(',')]
        else:
            cols = create_cols
        for t in split_tuples(m.group(2)):
            vals = split_values(t)
            rows.append((cols, vals))
    return rows


# ---------- 中文文本清洗 ----------
def clean_text(s):
    if not s:
        return ''
    s = s.replace('$B$B', '；').replace('$b$b', '；').replace('$B', '；').replace('$b', '；')
    s = s.replace('$N', '你').replace('$C', '玩家').replace('$R', '你')
    s = s.replace('\r', ' ').replace('\n', ' ').replace('\\', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def lua_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


# ---------- 主流程 ----------
def main():
    sql_path = os.path.join(RES, 'ClassicDB_base.sql')
    qzh_path = os.path.join(RES, 'locales_quest_zh.sql')
    izh_path = os.path.join(RES, 'locales_item_zh.sql')
    data_path = os.path.join(ROOT, 'QuestGearData.lua')
    for p in (sql_path, qzh_path, izh_path, data_path):
        if not os.path.exists(p):
            raise SystemExit('缺少输入文件: ' + p)

    print('读取 SQL / Lua 数据 ...')
    sql = open(sql_path, encoding='utf-8', errors='replace').read()
    qzh = open(qzh_path, encoding='utf-8', errors='replace').read()
    izh = open(izh_path, encoding='utf-8', errors='replace').read()
    lua = open(data_path, encoding='utf-8').read()

    # 任务模板：quest_template 列很多，按列名取
    qt = {}
    want = ['entry', 'Title', 'Objectives', 'PrevQuestId',
            'ReqItemId1', 'ReqItemId2', 'ReqItemId3', 'ReqItemId4',
            'ReqItemCount1', 'ReqItemCount2', 'ReqItemCount3', 'ReqItemCount4',
            'RewChoiceItemId1', 'RewChoiceItemId2', 'RewChoiceItemId3', 'RewChoiceItemId4',
            'RewChoiceItemId5', 'RewChoiceItemId6',
            'RewChoiceItemCount1', 'RewChoiceItemCount2', 'RewChoiceItemCount3',
            'RewChoiceItemCount4', 'RewChoiceItemCount5', 'RewChoiceItemCount6']
    for cols, vals in insert_rows(sql, 'quest_template'):
        if not cols:
            # 无列头时按经典表顺序，entry 必在第 1 列
            d = {}
            try:
                for i, name in enumerate(want):
                    d[name] = unquote(vals[i])
            except IndexError:
                continue
        else:
            d = {c: unquote(vals[i]) for i, c in enumerate(cols) if i < len(vals) and c in want}
        try:
            eid = int(d.get('entry', '0'))
        except ValueError:
            continue
        qt[eid] = d
    print('  quest_template: %d 条' % len(qt))

    # 中文任务文本
    qcn = {}
    for cols, vals in insert_rows(qzh, 'locales_quest'):
        try:
            eid = int(unquote(vals[0]))
        except (ValueError, IndexError):
            continue
        d = {c: unquote(vals[i]) for i, c in enumerate(cols) if i < len(vals)} if cols else {}
        qcn[eid] = {
            't': d.get('Title_loc4', ''),
            'd': clean_text(d.get('Details_loc4', '')),
            'o': clean_text(d.get('Objectives_loc4', '')),
        }
    print('  中文任务文本: %d 条' % len(qcn))

    # 中文物品名
    icn = {}
    for cols, vals in insert_rows(izh, 'locales_item'):
        try:
            iid = int(unquote(vals[0]))
        except (ValueError, IndexError):
            continue
        if len(vals) > 1:
            icn[iid] = unquote(vals[1])
    print('  中文物品名: %d 条' % len(icn))

    # QuestGearData 里的任务 ID + 阵营
    ids = {}
    for m in re.finditer(r'^  \[(\d+)\]=\{n="[^"]*",l=.*?f=(\d+)', lua, re.M):
        ids[int(m.group(1))] = int(m.group(2))
    # 前置任务可能不在 QuestGearData，仍需中文名才能显示
    extra = set()
    for q, d in qt.items():
        try:
            p = int(d.get('PrevQuestId', '0') or 0)
        except ValueError:
            p = 0
        if p and p in qcn:
            extra.add(p)
    print('  QuestGearData 任务: %d 条，补充前置名 %d 条' % (len(ids), len(extra)))

    def to_int(s):
        try:
            return int(s or 0)
        except ValueError:
            return 0

    def item_list(d, ipre, cpre):
        out = []
        for i in range(1, 7):
            iid = to_int(d.get('%s%d' % (ipre, i), '0'))
            if not iid:
                continue
            cnt = to_int(d.get('%s%d' % (cpre, i), '0')) or 1
            out.append((iid, icn.get(iid, ''), cnt))
        return out

    def lua_items(items):
        parts = []
        for iid, name, cnt in items:
            parts.append('{i=%d,n=%s,c=%d}' % (iid, lua_str(name), cnt))
        return '{' + ','.join(parts) + '}'

    lines = [
        '-- QuestGear 任务详情补充表（build_quest_info.py 自动生成，勿手改）',
        '-- 源: CMaNGOS classic-db quest_template + locales/Chinese/locales_quest.sql',
        '-- 构建: %s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '-- 字段: t=中文名 d=描述 o=目标 p=前置任务ID r=需求物品 w=奖励选项(三选一) f=阵营(0中立/1联盟/2部落/3双方)',
        'QuestGearQuestInfo = {',
    ]
    count = 0
    for q in sorted(set(ids) | extra):
        d = qt.get(q)
        cn = qcn.get(q, {})
        if not d and not cn:
            continue
        t = cn.get('t') or d.get('Title', '')
        o = cn.get('o') or clean_text(d.get('Objectives', ''))
        desc = cn.get('d', '')
        p = to_int(d.get('PrevQuestId', '0')) if d else 0
        req = item_list(d, 'ReqItemId', 'ReqItemCount') if d else []
        rew = item_list(d, 'RewChoiceItemId', 'RewChoiceItemCount') if d else []
        f = ids.get(q, 0)
        parts = ['t=%s' % lua_str(t)]
        if desc:
            parts.append('d=%s' % lua_str(desc[:220]))
        if o:
            parts.append('o=%s' % lua_str(o[:220]))
        if p:
            parts.append('p=%d' % p)
        if req:
            parts.append('r=%s' % lua_items(req))
        if rew:
            parts.append('w=%s' % lua_items(rew))
        if f:
            parts.append('f=%d' % f)
        lines.append('  [%d]={%s},' % (q, ','.join(parts)))
        count += 1
    lines.append('}')
    lines.append('QuestGearQuestInfoMeta = {v="qgi-cmangos-1",count=%d,built="%s"}' %
                 (count, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    out = os.path.join(ROOT, 'QuestGearQuestInfo.lua')
    with open(out, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('\n'.join(lines) + '\n')
    print('已生成 %s：%d 条，%d 字节' % (out, count, os.path.getsize(out)))

    # 样例自检
    s89 = [l for l in lines if l.startswith('  [89]=')]
    if s89:
        print('样例 [89] 止水湖上的桥:')
        print(s89[0][:600])


if __name__ == '__main__':
    main()
