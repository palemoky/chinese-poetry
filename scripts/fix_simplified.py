#!/usr/bin/env python3
"""把繁体诗（全唐诗/poet.*）中混入的简化字改回繁体正字。

字表与判定规则和 check_structure.py 的 simplified_in_trad 检查共用（SIMPLIFIED_IN_TRAD），
说明见 docs/繁体混入简化字.md。只改 title 与 paragraphs；tags、prologue 是合并选本时加入的
简体标注，author 关系到作者匹配，都不动。

写回时保持文件原有的 JSON 格式：先确认原文能按同样的格式重新生成（否则跳过该文件），
写回前再核对新旧文本只在被替换的字上不同。

用法：
  python3 scripts/fix_simplified.py              # 预览：各字的替换次数
  python3 scripts/fix_simplified.py --apply      # 写回，并把逐处修改记入 docs/繁体混入简化字.tsv
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_structure import ROOT, SIMPLIFIED_IN_TRAD, written_in_simplified  # noqa: E402

RECORD = os.path.join(ROOT, 'docs', '繁体混入简化字.tsv')
FORMATS = (dict(ensure_ascii=False, indent=4), dict(ensure_ascii=False, indent=2))


def dumps_like(data, raw):
    """返回与 raw 格式一致的序列化函数，找不到时返回 None。"""
    for kw in FORMATS:
        out = json.dumps(data, **kw)
        for tail in ('', '\n'):
            if out + tail == raw:
                return lambda d, kw=kw, tail=tail: json.dumps(d, **kw) + tail
    return None


def convert(text):
    return ''.join(SIMPLIFIED_IN_TRAD.get(c, c) for c in text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='写回文件并记录修改')
    args = ap.parse_args()

    per_char = collections.Counter()
    records, skipped_files = [], []
    for path in sorted(glob.glob(os.path.join(ROOT, '全唐诗', 'poet.*.json'))):
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding='utf-8') as fp:
            raw = fp.read()
        data = json.loads(raw)
        dumps = dumps_like(data, raw)
        if dumps is None:
            skipped_files.append(rel)
            continue

        changed = False
        for idx, it in enumerate(data):
            lines = it.get('paragraphs')
            if not isinstance(lines, list):
                continue
            title = it.get('title') if isinstance(it.get('title'), str) else ''
            if written_in_simplified(title + ''.join(lines)):
                continue
            targets = [('title', None, title)] + [('paragraphs', i, s) for i, s in enumerate(lines)]
            for field, i, before in targets:
                after = convert(before)
                if after == before:
                    continue
                per_char.update(c for c in before if c in SIMPLIFIED_IN_TRAD)
                records.append((rel, idx, field if i is None else f'{field}[{i}]', before, after))
                if field == 'title':
                    it['title'] = after
                else:
                    lines[i] = after
                changed = True

        if changed and args.apply:
            new = dumps(data)
            # 只允许被替换的字不同：长度相同，逐字差异都是表中的一对
            assert len(new) == len(raw), rel
            assert all(a == b or SIMPLIFIED_IN_TRAD.get(a) == b for a, b in zip(raw, new)), rel
            with open(path, 'w', encoding='utf-8') as fp:
                fp.write(new)

    print(f'{sum(per_char.values())} 处，{len(per_char)} 个字，{len({r[0] for r in records})} 个文件，{len(records)} 行')
    print('  ' + ' '.join(f'{c}→{SIMPLIFIED_IN_TRAD[c]}:{n}' for c, n in per_char.most_common()))
    if skipped_files:
        print(f'格式无法原样重现，跳过 {len(skipped_files)} 个文件：' + ', '.join(skipped_files))

    if args.apply:
        with open(RECORD, 'w', encoding='utf-8') as fp:
            fp.write('file\tindex\tfield\tbefore\tafter\n')
            for row in records:
                fp.write('\t'.join(map(str, row)) + '\n')
        print(f'已写回，逐处修改记入 {os.path.relpath(RECORD, ROOT)}')
    else:
        print('预览模式，未写回；加 --apply 写回')


if __name__ == '__main__':
    sys.exit(main())
