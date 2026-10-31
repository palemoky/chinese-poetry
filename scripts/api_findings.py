#!/usr/bin/env python3
"""生成 docs/API导入问题清单.tsv：chinese-poetry-api 导入时发现的数据问题，只报告，不修改任何数据。

id 列是 `文件#下标`，增删记录后同一文件中靠后的下标全部失效，改动数据后要重新生成。

检查项：
  唐宋重复收录        poet.song 与 poet.tang 中作者、正文完全相同
  正文为空或只有标点  全唐诗、元曲
  正文在标题中        元曲 paragraphs 为空而 title 含句读，正文写在了 title 里，不是空正文
  正文含空段          全唐诗、元曲
  空标题              全唐诗
  作者名含缺字/括注   全唐诗、宋词、元曲；{...} 是生僻字占位，不算
  首段疑为注文        全唐诗首段以 （ 开头；元曲中以括号开头的多为科介，属于正文
  作者表重名条目      authors.tang.json、authors.song.json
  作者小传为空        同上
  唐宋同名作者        信息性，不一定是错误

用法：
  python3 scripts/api_findings.py                    # 写入 docs/API导入问题清单.tsv
  python3 scripts/api_findings.py --out /tmp/r.tsv
  python3 scripts/api_findings.py --root /path/to/checkout  # 统计另一份数据
"""
import argparse
import collections
import csv
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = ['id', '作者', '题目', '问题', '详情', '建议']
ADVICE = {
    '唐宋重复收录': '确认归属朝代后删除其中一条',
    '正文为空或只有标点': '补全正文或删除该条（如为存目可移入 notes）',
    '正文在标题中': '把 title 中的正文拆回 paragraphs，title 只留曲牌；勿删除',
    '正文含空段': '删除空段',
    '空标题': '补题（可用「句」「失题」或首句），或确认是否为上一首的残段',
    '作者名含缺字/括注': '核实作者名；无法补全的统一写法，括注移入 notes',
    '首段疑为注文': '若为整段注释，移入 notes 字段',
    '作者表重名条目': '同一人则合并小传；不同人则在名字或 id 上区分',
    '作者小传为空': '补写小传，或确认无传可考',
    '唐宋同名作者': '确认是同一人（五代入宋等）还是同名异人；两部分作者表各自的小传应与之对应',
}
PUNCT_ONLY = re.compile(r'^[\s。，、；：？！…．.,]*$')
BAD_AUTHOR = re.compile(r'[\[\]□？]')
YUANQU = '元曲/yuanqu.json'


def rel_glob(root, pattern):
    files = glob.glob(os.path.join(root, pattern))
    files.sort(key=lambda f: int(re.search(r'\.(\d+)', os.path.basename(f))[1]))
    return [os.path.relpath(f, root) for f in files]


def title_of(poem):
    return poem.get('title', poem.get('rhythmic', '')) or ''


def poem_key(poem):
    return poem.get('author'), tuple(poem.get('paragraphs') or [])


def collect(root):
    def load(rel):
        with open(os.path.join(root, rel), encoding='utf-8') as f:
            return json.load(f)

    tang = rel_glob(root, '全唐诗/poet.tang.*.json')
    song = rel_glob(root, '全唐诗/poet.song.*.json')
    quan = tang + song + ['全唐诗/唐诗补录.json']
    ci = rel_glob(root, '宋词/ci.song.[0-9]*.json')
    data = {f: load(f) for f in quan + ci + [YUANQU]}
    rows = []

    def add(rid, author, title, kind, detail):
        rows.append([rid, author, title, kind, detail, ADVICE[kind]])

    def add_poem(f, i, poem, kind, detail):
        add(f'{f}#{i}', poem.get('author', ''), title_of(poem), kind, detail)

    tang_index = {}
    for f in tang:
        for i, p in enumerate(data[f]):
            if ''.join(p.get('paragraphs') or []).strip('。 '):
                tang_index[poem_key(p)] = f'{f}#{i}'
    for f in song:
        for i, p in enumerate(data[f]):
            if poem_key(p) in tang_index:
                add_poem(f, i, p, '唐宋重复收录', f'与 {tang_index[poem_key(p)]} 作者、正文完全相同')

    for f in quan + [YUANQU]:
        for i, p in enumerate(data[f]):
            paragraphs = p.get('paragraphs') or []
            dumped = json.dumps(paragraphs, ensure_ascii=False)
            if PUNCT_ONLY.match(''.join(paragraphs)):
                if f == YUANQU and re.search('[，。？！；]', title_of(p)):
                    add_poem(f, i, p, '正文在标题中', 'paragraphs 为空，正文写在 title 里')
                else:
                    add_poem(f, i, p, '正文为空或只有标点', dumped)
            elif any(not s.strip() for s in paragraphs):
                add_poem(f, i, p, '正文含空段', dumped[:60])

    for f in quan:
        for i, p in enumerate(data[f]):
            if not title_of(p).strip():
                add_poem(f, i, p, '空标题', ''.join(p.get('paragraphs') or [])[:30])

    first_seen, counts = {}, collections.Counter()
    for f in quan + ci + [YUANQU]:
        for i, p in enumerate(data[f]):
            author = p.get('author', '')
            if BAD_AUTHOR.search(author):
                counts[author] += 1
                first_seen.setdefault(author, (f'{f}#{i}', title_of(p)))
    for author, (rid, title) in first_seen.items():
        add(rid, author, title, '作者名含缺字/括注', f'「{author}」共 {counts[author]} 首（此处为首次出现）')

    for f in quan:
        for i, p in enumerate(data[f]):
            paragraphs = p.get('paragraphs') or []
            if paragraphs and paragraphs[0].startswith('（'):
                add_poem(f, i, p, '首段疑为注文', paragraphs[0][:40])

    author_files = ['全唐诗/authors.tang.json', '全唐诗/authors.song.json']
    authors = {f: load(f) for f in author_files}
    for f in author_files:
        by_name = collections.defaultdict(list)
        for i, a in enumerate(authors[f]):
            by_name[a.get('name')].append(i)
        for name, indexes in by_name.items():
            if len(indexes) > 1:
                add(f'{f}#{indexes[0]}', name, '', '作者表重名条目', '同名条目下标 ' + ', '.join(map(str, indexes)))
    for f in author_files:
        for i, a in enumerate(authors[f]):
            if not (a.get('desc') or '').strip():
                add(f'{f}#{i}', a.get('name', ''), '', '作者小传为空', 'desc 为空')

    tang_count = collections.Counter(p.get('author') for f in tang for p in data[f])
    song_count = collections.Counter(p.get('author') for f in song for p in data[f])
    for a in sorted(set(tang_count) & set(song_count), key=lambda a: (-(tang_count[a] + song_count[a]), a)):
        add('全唐诗/poet.*.json', a, '', '唐宋同名作者', f'唐 {tang_count[a]} 首 / 宋 {song_count[a]} 首')
    return rows


def main():
    parser = argparse.ArgumentParser(description='生成 API 导入问题清单')
    parser.add_argument('--root', default=ROOT, help='数据根目录，默认当前仓库')
    parser.add_argument('--out', default=os.path.join(ROOT, 'docs', 'API导入问题清单.tsv'))
    args = parser.parse_args()

    rows = collect(args.root)
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter='\t', lineterminator='\r\n')
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f'{len(rows)} 条 → {args.out}')
    for kind, n in collections.Counter(r[3] for r in rows).most_common():
        print(f'  {kind}: {n}')


if __name__ == '__main__':
    main()
