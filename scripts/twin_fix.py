#!/usr/bin/env python3
"""全唐诗 -> 御定全唐詩 对勘：还原御定中的 ASCII 残渣编码，补回丢失的生僻字。

御定全唐詩爬取时丢失了扩展 A 区及非 BMP 的生僻字，原位留下 1~3 位 ASCII 编码（如 z5、eR）。
全唐诗/poet.tang.* 是同一部《全唐詩》的独立来源，保留了这些字。本脚本：
  1. 对齐两边相邻句完全相同、仅差一字的句子，从缺口处的编码反推「编码 -> 汉字」；
  2. 与已有编码表 scripts/yuding_codes.tsv 合并（只采用无冲突或压倒性多数的映射）；
  3. 用编码表替换御定中的残渣；缺口无编码且所缺为生僻字的，按全唐诗补回。

用法：
  python3 scripts/twin_fix.py                  # dry run，只打印
  python3 scripts/twin_fix.py --apply          # 写回 御定全唐詩/json/*.json 并更新编码表
  python3 scripts/twin_fix.py --out r.json     # 输出编码证据与逐行修改明细
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_structure as cs  # noqa: E402

ROOT = cs.ROOT
CODE_TABLE = os.path.join(ROOT, 'scripts', 'yuding_codes.tsv')
CODE = r'[A-Za-z0-9]{1,3}'
EXCLUDE = {'du', 'ek'}   # 单条证据且映射到常用字（林、隧），存疑，不采用


def rare(ch):
    return ord(ch) > 0xFFFF or 0x3400 <= ord(ch) <= 0x4DBF


def load(pattern):
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, pattern))):
        rel = os.path.relpath(p, ROOT)
        for idx, it, lines in cs.iter_poems(rel):
            out.append((rel, idx, it, lines, cs.sentences(lines)))
    return out


def read_table():
    table = {}
    if os.path.exists(CODE_TABLE):
        with open(CODE_TABLE, encoding='utf-8') as fp:
            for line in fp:
                if line.strip() and not line.startswith('#'):
                    code, ch = line.rstrip('\n').split('\t')[:2]
                    table[code] = ch
    return table


def write_table(table):
    with open(CODE_TABLE, 'w', encoding='utf-8') as fp:
        fp.write('# 御定全唐詩 爬取残渣编码 -> 汉字，由 scripts/twin_fix.py 与 全唐诗/poet.tang.* 对勘得出\n')
        for code in sorted(table):
            fp.write(f'{code}\t{table[code]}\n')


def collect_evidence(qts, yd):
    """在御定中找「少一字」且全唐诗有对应完整句的位置，记录缺口处的编码。"""
    after, before = collections.defaultdict(list), collections.defaultdict(list)
    for *_, s in qts:
        for a, b in zip(s, s[1:]):
            after[a].append(b)
            before[b].append(a)
    all_qts = {x for *_, s in qts for x in s}

    evidence = collections.defaultdict(collections.Counter)   # code -> Counter(char)
    examples = collections.defaultdict(list)
    bare_gaps = []                                             # 缺口处无编码
    for rel, idx, it, lines, s in yd:
        for i, y in enumerate(s):
            if y in all_qts:
                continue
            cands = (after.get(s[i - 1], []) if i else []) + \
                    (before.get(s[i + 1], []) if i + 1 < len(s) else [])
            full = next((c for c in cands if cs.one_edit(y, c)), None)
            if not full:
                continue
            j = next(k for k in range(len(full)) if full[:k] + full[k + 1:] == y)
            ch = full[j]
            if ch in '□〇':
                continue
            pat = re.compile(re.escape(y[:j]) + f'({CODE})?' + re.escape(y[j:]))
            locs = [(li, m) for li, line in enumerate(lines)
                    for m in pat.finditer(cs.FOOTNOTE.sub('', line))]
            if len(locs) != 1:
                continue
            li, m = locs[0]
            if m.group(1):
                evidence[m.group(1)][ch] += 1
                examples[m.group(1)].append(f'{y[:j]}[{m.group(1)}]{y[j:]} -> {full}')
            elif rare(ch):
                bare_gaps.append(dict(file=rel, idx=idx, line=li, short=y, full=full))
    return evidence, examples, bare_gaps


def build_table(evidence, known):
    """已有编码表优先；新编码只采用无冲突或压倒性多数（异体字）的映射。"""
    table, conflicts = dict(known), {}
    for code, cnt in evidence.items():
        ch, n = cnt.most_common(1)[0]
        total = sum(cnt.values())
        if code in known:
            if known[code] not in cnt or cnt[known[code]] < total / 2:
                conflicts[code] = {'table': known[code], **cnt}
        elif code in EXCLUDE:
            conflicts[code] = dict(cnt)
        elif total == n or (total >= 5 and n / total >= 0.8):
            table[code] = ch
        else:
            conflicts[code] = dict(cnt)
    return table, conflicts


def apply_fixes(table, bare_gaps, write):
    token = re.compile(r'(?<![A-Za-z0-9\[])('
                       + '|'.join(map(re.escape, sorted(table, key=len, reverse=True)))
                       + r')(?![A-Za-z0-9\]])') if table else None
    gaps_by_file = collections.defaultdict(list)
    for g in bare_gaps:
        gaps_by_file[g['file']].append(g)

    changes = []
    for path in sorted(glob.glob(os.path.join(ROOT, '御定全唐詩', 'json', '*.json'))):
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding='utf-8') as fp:
            raw = fp.read()
        data = json.loads(raw)
        file_changes = []
        for idx, it in enumerate(data):
            paras = it.get('paragraphs') or []
            for li, line in enumerate(paras):
                new = token.sub(lambda m: table[m.group(1)], line) if token else line
                if new != line:
                    file_changes.append(dict(file=rel, idx=idx, author=it.get('author'),
                                             title=it.get('title'), original=line,
                                             corrected=new, how='code'))
                    paras[li] = new
        for g in gaps_by_file.get(rel, []):
            it = data[g['idx']]
            line = it['paragraphs'][g['line']]
            if line.count(g['short']) == 1 and g['full'] not in line:
                new = line.replace(g['short'], g['full'])
                file_changes.append(dict(file=rel, idx=g['idx'], author=it.get('author'),
                                         title=it.get('title'), original=line,
                                         corrected=new, how='bare'))
                it['paragraphs'][g['line']] = new
        if file_changes and write:
            # 按原文逐行替换，不重新序列化，避免改变文件格式
            for c in file_changes:
                a = json.dumps(c['original'], ensure_ascii=False)
                b = json.dumps(c['corrected'], ensure_ascii=False)
                assert a in raw, (rel, c['original'])
                raw = raw.replace(a, b)
            with open(path, 'w', encoding='utf-8') as fp:
                fp.write(raw)
        changes += file_changes
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='写回数据文件并更新编码表')
    ap.add_argument('--out', help='输出编码证据与修改明细（JSON）')
    args = ap.parse_args()

    qts = load(os.path.join('全唐诗', 'poet.tang.*.json'))
    yd = load(os.path.join('御定全唐詩', 'json', '*.json'))
    known = read_table()
    evidence, examples, bare_gaps = collect_evidence(qts, yd)
    table, conflicts = build_table(evidence, known)
    changes = apply_fixes(table, bare_gaps, write=args.apply)
    if args.apply and table != known:
        write_table(table)

    new_codes = sorted(set(table) - set(known))
    print(f'编码表 {len(table)} 个（已有 {len(known)}，新增 {len(new_codes)}），'
          f'冲突 {len(conflicts)} 个，缺口无编码的生僻字 {len(bare_gaps)} 处')
    if conflicts:
        print('冲突:', conflicts)
    if new_codes:
        print('新增:', ' '.join(f'{k}={table[k]}' for k in new_codes))
    print(f'{"已修改" if args.apply else "待修改"} {len(changes)} 行'
          f'（code {sum(c["how"] == "code" for c in changes)}，'
          f'bare {sum(c["how"] == "bare" for c in changes)}）')
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fp:
            json.dump(dict(mapping=table, conflicts=conflicts, examples=examples, changes=changes),
                      fp, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
