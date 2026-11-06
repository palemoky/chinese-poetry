#!/usr/bin/env python3
"""小合集 ↔ 全唐诗 / 宋词 互校：同一首作品在两处的一字之差，以识典古籍判定哪一方有误。

花间集、南唐二主词、唐诗三百首、千家诗、水墨唐诗等选本中的作品，大多也收在 全唐诗 或 宋词 里。
两处文字一字之差时，至少一方可能有错；以差异字左右两侧的共同上下文检索识典古籍（检索词不含差异字，
不偏向任何一方），统计古籍片段中各读法出现在几种书里。
（merge_anthologies.py 已删去 poet.tang 中与花间集/南唐重复的词，这两部已无全唐诗对照。）

  W=~/.cache/chinese-poetry/twin       # 放在仓库之外
  python3 scripts/twin_collate.py plan    --work $W
  node   scripts/shidian/search.mjs      $W/queries.json $W/results.jsonl
  A=docs/小合集互校.applied.json        # 已写回或否决的条目，之后的审核表不再出现
  python3 scripts/twin_collate.py analyze --work $W --applied $A   # 写出 $W/review.tsv
  # 审核 review.tsv 的 decision 列：target = 改小合集为对方读法；ref = 改 全唐诗/宋词 为小合集读法；
  #   reject = 不改且以后不再出现；留空 = 暂不决定。char 列可填写要写入的字，覆盖自动选字。
  python3 scripts/twin_collate.py apply   --work $W --applied $A --reviewer <名字> --date YYYY-MM-DD

判定（只是建议，写回前须逐条人工审核）：
  fix_target  对方读法 ≥2 种古籍，本方 0 种          fix_ref  反之
  variant     两读皆有古籍 → 异文，不改               weak     证据不足
  glyph       一字在 GB2312 内、一字不在 → 多为异体，只供人工看

审核经验（2026-10 首次运行，798 处差异）：
  - 用字差异不算错字，即使本方 0 种古籍也不改：帷/幃、消/銷、含/銜、怎奈/争奈、么/摩、拚/判、坼/拆、歧/岐、直/值。
  - fix_ref 要格外谨慎：识典古籍首页结果多为通行选本，《全唐诗》自己的读法常被淹没（如骆宾王「客思侵」、
    白居易「夜来城上一尺雪」「疑绝不通」都是《全唐诗》原貌）。只改能确认的错字：失韵、形近明显错、句意不通。
"""
import argparse
import collections
import csv
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_structure as cs  # noqa: E402
import collate  # noqa: E402
import shidian as sd  # noqa: E402

ROOT = cs.ROOT
TARGETS = ['五代诗词/huajianji', '五代诗词/nantang', '蒙学/tangshisanbaishou.json', '蒙学/qianjiashi.json',
           '水墨唐诗/shuimotangshi.json']
REF_DIRS = ['全唐诗', '宋词']
HANX = r'[㐀-鿿\U00020000-\U0003ffff]'
ORDER = {'fix_target': 0, 'fix_ref': 1, 'glyph': 2, 'weak': 3, 'variant': 4}


def walk(node, path=()):
    """递归找出含 paragraphs 的作品（蒙学 各书是 content[].content[] 的嵌套结构）。"""
    if isinstance(node, dict):
        if isinstance(node.get('paragraphs'), list):
            yield path, node
            return
        for k, v in node.items():
            if isinstance(v, (list, dict)):
                yield from walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + (i,))


def node_at(data, path):
    for p in path:
        data = data[p]
    return data


def title_of(it):
    return it.get('title') or it.get('rhythmic') or it.get('chapter') or ''


def is_target(rel, targets):
    return any(rel == t or rel.startswith(t + os.sep) for t in targets)


# ---------------------------------------------------------------- plan

def cmd_plan(args):
    os.makedirs(args.work, exist_ok=True)
    norm = collate.norm_factory(args.work)
    targets = []
    for rel in cs.iter_files():
        if not is_target(rel, args.targets):
            continue
        for path, it in walk(sd.load(rel)):
            sents = cs.sentences([s for s in it['paragraphs'] if isinstance(s, str)])
            if sents:
                targets.append(dict(file=rel, path=path, it=it, sents=sents, ns=[norm(s) for s in sents]))
    want = {s for t in targets for s in t['ns'] if len(s) >= 4}

    # 只索引与目标句完全相同的参考句，据此找出对应作品
    hit = collections.defaultdict(set)
    for rel in cs.iter_files():
        if rel.split(os.sep)[0] not in REF_DIRS or is_target(rel, args.targets) or f'{os.sep}error{os.sep}' in rel:
            continue
        for idx, it, lines in cs.iter_poems(rel):
            for s in cs.sentences(lines):
                n = norm(s)
                if n in want:
                    hit[n].add((rel, idx))

    ref_cache = {}
    diffs, matched = [], 0
    for t in targets:
        c = collections.Counter(r for s in t['ns'] if len(s) >= 4 for r in hit.get(s, ()))
        best = [r for r, n in c.most_common(1) if n >= 2 and n >= len(t['ns']) * 0.25]
        if not best:
            continue
        matched += 1
        rel, idx = best[0]
        if rel not in ref_cache:
            ref_cache[rel] = sd.load(rel)
        rit = ref_cache[rel][idx]
        rs = cs.sentences(rit.get('paragraphs') or [])
        rn = [norm(s) for s in rs]
        sm = difflib.SequenceMatcher(None, t['ns'], rn, autojunk=False)
        for op, a1, a2, b1, b2 in sm.get_opcodes():
            if op != 'replace' or a2 - a1 != b2 - b1:
                continue
            for i, j in zip(range(a1, a2), range(b1, b2)):
                x, y, a, b = t['ns'][i], rn[j], t['sents'][i], rs[j]
                if not (len(x) == len(y) == len(a) == len(b)):
                    continue
                d = [k for k in range(len(x)) if x[k] != y[k]]
                if len(d) != 1 or collate.interchangeable(a[d[0]], b[d[0]]):
                    continue
                diffs.append(dict(file=t['file'], path=list(t['path']), poem=f"{t['it'].get('author', '')}《{title_of(t['it'])}》",
                                  sent=a, ref_file=rel, ref_idx=idx, ref_poem=f"{rit.get('author', '')}《{title_of(rit)}》",
                                  ref_sent=b, pos=d[0], mine=a[d[0]], theirs=b[d[0]],
                                  prev=t['sents'][i - 1] if i else '', next=t['sents'][i + 1] if i + 1 < len(t['sents']) else ''))

    queries = []
    for it in diffs:
        tr = lambda s: sd.to_trad(it['file'], s)  # noqa: E731
        prev, sent, nxt, k = tr(it['prev']), tr(it['sent']), tr(it['next']), it['pos']
        it['queries'] = [q for q in ((prev + sent[:k])[-5:], (sent[k + 1:] + nxt)[:5]) if len(q) >= 4]
        queries += it['queries']
    json.dump(diffs, open(os.path.join(args.work, 'diffs.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(list(dict.fromkeys(queries)), open(os.path.join(args.work, 'queries.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    print(f'{matched}/{len(targets)} poems matched, {len(diffs)} one-char diffs, '
          f'{len(set(queries))} queries → {args.work}')


# ---------------------------------------------------------------- analyze

def key_of(file, path, sent, pos):
    return f'{file}#{path}#{sent}#{pos}'


def load_applied(path):
    return set(json.load(open(path, encoding='utf-8'))) if path and os.path.exists(path) else set()


def cmd_analyze(args):
    norm = collate.norm_factory(args.work)
    res = sd.load_results(args.work)
    applied = load_applied(args.applied)
    rows = []
    for it in json.load(open(os.path.join(args.work, 'diffs.json'), encoding='utf-8')):
        if key_of(it['file'], json.dumps(it['path']), it['sent'], it['pos']) in applied:
            continue                                   # 已审核
        if not all(q in res for q in it['queries']):
            continue                                   # 检索未完成
        tr = lambda s: norm(sd.to_trad(it['file'], s))  # noqa: E731
        prev, sent, nxt, k = tr(it['prev']), tr(it['sent']), tr(it['next']), it['pos']
        L, R = (prev + sent[:k])[-2:], (sent[k + 1:] + nxt)[:2]
        if len(L) < 2:
            R = (sent[k + 1:] + nxt)[:4 - len(L)]
        if len(R) < 2:
            L = (prev + sent[:k])[-(4 - len(R)):]
        mine, theirs = norm(it['mine']), norm(it['theirs'])
        books, seen = collections.defaultdict(set), set()
        for q in it['queries']:
            for raw, _, book, _ in sd.snippets(res[q]):
                n = norm(raw)
                if (n, book) in seen:
                    continue
                seen.add((n, book))
                for m in re.finditer(re.escape(L) + f'({HANX})' + re.escape(R), n):
                    books[m.group(1)].add(book)
        a, b = len(books.get(mine, ())), len(books.get(theirs, ()))
        if collate.gb(it['mine']) != collate.gb(it['theirs']):
            verdict = 'glyph'
        elif b >= 2 and a == 0:
            verdict = 'fix_target'
        elif a >= 2 and b == 0:
            verdict = 'fix_ref'
        elif a and b:
            verdict = 'variant'
        else:
            verdict = 'weak'
        others = sorted(((c, len(v)) for c, v in books.items() if c not in (mine, theirs)), key=lambda x: -x[1])
        rows.append(dict(verdict=verdict, file=it['file'], path=json.dumps(it['path']), poem=it['poem'], sent=it['sent'],
                         mine=it['mine'], mine_books=a, ref_file=it['ref_file'], ref_idx=it['ref_idx'],
                         ref_sent=it['ref_sent'], theirs=it['theirs'], theirs_books=b, pos=k,
                         other=' '.join(f'{c}:{n}' for c, n in others[:3]),
                         mine_src='；'.join(sorted(books.get(mine, ()))[:3]),
                         theirs_src='；'.join(sorted(books.get(theirs, ()))[:3]), decision='', char=''))
    rows.sort(key=lambda r: (ORDER[r['verdict']], r['file']))
    with open(os.path.join(args.work, 'review.tsv'), 'w', encoding='utf-8', newline='') as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0]), delimiter='\t')
        w.writeheader()
        w.writerows(rows)
    print(dict(collections.Counter(r['verdict'] for r in rows)), f'— {len(rows)} analyzed → {args.work}/review.tsv')


# ---------------------------------------------------------------- apply

def edit(progress, rel, path, sent, k, ch, note, reviewer, date):
    """改正文中的一字；若标题（词牌·首句）含同一句，一并改。"""
    raw = open(os.path.join(ROOT, rel), encoding='utf-8').read()
    node = node_at(json.loads(raw), path)
    hits = [p for p in node['paragraphs'] if p.count(sent) == 1]
    if len(hits) != 1:
        return f'skip {rel}{path}: 「{sent}」 not unique'
    new_sent = sent[:k] + ch + sent[k + 1:]
    pairs = [(hits[0], hits[0].replace(sent, new_sent, 1))]
    for key in ('title', 'rhythmic'):
        if isinstance(node.get(key), str) and sent in node[key]:
            pairs.append((node[key], node[key].replace(sent, new_sent)))
    for o, n in pairs:
        o, n = json.dumps(o, ensure_ascii=False), json.dumps(n, ensure_ascii=False)
        if raw.count(o) != 1:
            return f'skip {rel}{path}: {o} not unique in file'
        raw = raw.replace(o, n, 1)
    open(os.path.join(ROOT, rel), 'w', encoding='utf-8').write(raw)
    e = sd.add_fix(progress, rel, dict(original=sent, corrected=new_sent, note=note), date, reviewer)
    if e.get('status') == 'clean':
        e['status'] = 'fixed'
    return None


def cmd_apply(args):
    rows = list(csv.DictReader(open(os.path.join(args.work, 'review.tsv'), encoding='utf-8'), delimiter='\t'))
    progress_path = os.path.join(ROOT, 'fix_progress.json')
    progress = json.load(open(progress_path, encoding='utf-8'))
    applied = load_applied(args.applied)
    n = 0
    for r in rows:
        d, k = r['decision'].strip(), int(r['pos'])
        key = key_of(r['file'], r['path'], r['sent'], r['pos'])
        if d == 'reject':
            applied.add(key)
            continue
        if d == 'target':
            ch = r['char'] or sd.to_dataset_script(r['file'], sd.to_trad(r['ref_file'], r['theirs']))
            note = (f"Twin collation with {r['ref_file']}#{r['ref_idx']} ({r['ref_sent']}); 识典古籍: 「{r['theirs']}」 in "
                    f"{r['theirs_books']} books ({r['theirs_src']}), dataset reading 「{r['mine']}」 in {r['mine_books']}")
            err = edit(progress, r['file'], json.loads(r['path']), r['sent'], k, ch, note, args.reviewer, args.date)
        elif d == 'ref':
            ch = r['char'] or sd.to_dataset_script(r['ref_file'], sd.to_trad(r['file'], r['mine']))
            note = (f"Twin collation with {r['file']} ({r['sent']}); 识典古籍: 「{r['mine']}」 in "
                    f"{r['mine_books']} books ({r['mine_src']}), dataset reading 「{r['theirs']}」 in {r['theirs_books']}")
            err = edit(progress, r['ref_file'], [int(r['ref_idx'])], r['ref_sent'], k, ch, note, args.reviewer, args.date)
        else:
            continue
        if err:
            print(err)
        else:
            applied.add(key)
            n += 1
    sd.write_progress(progress, progress_path)
    if args.applied:
        with open(args.applied, 'w', encoding='utf-8') as fp:
            json.dump(sorted(applied), fp, ensure_ascii=False, indent=0)
            fp.write('\n')
    print(f'applied {n} corrections; {len(applied)} items closed in total')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--work', required=True)
    p.add_argument('--targets', nargs='+', default=TARGETS, help='要互校的小合集（目录或文件，相对仓库根目录）')
    p = sub.add_parser('analyze')
    p.add_argument('--work', required=True)
    p.add_argument('--applied', help='已写回或否决条目的记录文件')
    p = sub.add_parser('apply')
    p.add_argument('--work', required=True)
    p.add_argument('--applied', help='已写回或否决条目的记录文件')
    p.add_argument('--reviewer', required=True, help='AI model name or GitHub handle')
    p.add_argument('--date', required=True, help='YYYY-MM-DD')
    args = ap.parse_args()
    {'plan': cmd_plan, 'analyze': cmd_analyze, 'apply': cmd_apply}[args.cmd](args)


if __name__ == '__main__':
    main()
