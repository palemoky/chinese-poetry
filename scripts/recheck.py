#!/usr/bin/env python3
"""复核宋词对勘的既往判定：以差异字左右两侧的上下文检索识典古籍，统计各书在该位置的用字。

宋词对勘的审核表只有机器比对，人工判定时没有逐条查书；留空的 168 处查证后 76% 要改，说明判定不够可靠。
本工具对其余 2,968 处（快照 docs/宋词对勘.recheck.tsv）重新取证。检索词不含差异字，不偏向任何一方。

  W=~/.cache/chinese-poetry/songci-recheck      # 放在仓库之外
  python3 scripts/recheck.py plan --work $W
  node   scripts/shidian/search.mjs $W/queries.json $W/results.jsonl --limit 2000
  python3 scripts/recheck.py analyze --work $W  # 写出 $W/recheck.tsv，只列出与既往判定不一致的条目

判定（只是建议，写回前须逐条人工审核）：
  overturn_reject  当时否决：本库读法 0 种书，建议读法 ≥2 种书 → 可能是漏改的错字
  overturn_accept  当时采纳：原读法有书支持 → 可能把异文改掉了；或建议读法 0 种书 → 可能改错了
  weak             双方都不足 2 种书，证据不足
"""
import argparse
import collections
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shidian as sd  # noqa: E402

ROOT = sd.ROOT
SNAPSHOT = os.path.join(ROOT, 'docs', '宋词对勘.recheck.tsv')
FIELDS = ['key', 'past', 'file', 'idx', 'author', 'title', 'original', 'proposed', 'k']
NOISE = set('頁')                                    # 页码混入片段
SKIP_PUNCT = re.compile(r'[^㐀-鿿\U00020000-\U0003ffff□{}]')


def book_name(b):
    """同一部书在结果页有不同写法：[御選]歷代詩餘 / 御選歷代詩餘"""
    return re.sub(r'^(\[[^]]*\]|御選|御定)', '', b).strip()


def locate(text, row, k):
    """在去标点的正文里找到句子，返回其起点。写回后差异字已变；通配放在最后，以免命中只差一字的另一句。"""
    o = row['original']
    for s in (o, row['proposed']):
        if s in text:
            return text.index(s)
    m = re.search(re.escape(o[:k]) + '.' + re.escape(o[k + 1:]), text)
    return m.start() if m else None


def context(text, at, step, n=5):
    out, i = [], at + step
    while 0 <= i < len(text) and len(out) < n and text[i] not in '□{}':
        out.append(text[i])
        i += step
    return ''.join(reversed(out) if step < 0 else out)


def poem_text(rel, idx, cache):
    if rel not in cache:
        cache[rel] = json.load(open(os.path.join(ROOT, rel), encoding='utf-8'))
    return SKIP_PUNCT.sub('', ''.join(cache[rel][idx]['paragraphs']))


def cmd_snapshot(args):
    """由完整审核表生成快照；只需运行一次，结果随仓库提交。"""
    rows = list(csv.DictReader(open(args.review, encoding='utf-8'), delimiter='\t'))
    done = {r['key'] for r in csv.DictReader(open(args.skip, encoding='utf-8'), delimiter='\t')}
    out, missing, cache = [], [], {}
    for r in rows:
        if r['key'] in done:
            continue
        o, p = r['original'], r['proposed']
        k = next(j for j in range(len(o)) if o[j] != p[j])
        text = poem_text(r['file'], int(r['idx']), cache)
        at = locate(text, r, k)
        if at is None:
            missing.append(r['key'])
            continue
        out.append(dict({f: r[f] for f in FIELDS if f in r}, k=k, past='reject' if text[at + k] == o[k] else 'accept'))
    with open(args.out, 'w', encoding='utf-8', newline='') as fp:
        w = csv.DictWriter(fp, delimiter='\t', fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f'{len(out)} rows ({collections.Counter(r["past"] for r in out)}), missing {missing}')


def cmd_plan(args):
    os.makedirs(args.work, exist_ok=True)
    items, queries, cache = [], [], {}
    for r in csv.DictReader(open(SNAPSHOT, encoding='utf-8'), delimiter='\t'):
        k = int(r['k'])
        text = poem_text(r['file'], int(r['idx']), cache)
        at = locate(text, r, k)
        if at is None:
            print('skip (sentence changed):', r['key'])
            continue
        at += k
        L, R = context(text, at, -1), context(text, at, 1)
        ql, qr = sd.to_trad(r['file'], L), sd.to_trad(r['file'], R)
        items.append(dict(r, k=k, L=L, R=R, ql=ql, qr=qr))
        queries.extend(q for q in (ql, qr) if len(q) >= 3)
    queries = list(dict.fromkeys(queries))
    json.dump(items, open(os.path.join(args.work, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(queries, open(os.path.join(args.work, 'queries.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'{len(items)} items, {len(queries)} queries → {args.work}')


def load_results(work):
    res = {}
    path = os.path.join(work, 'results.jsonl')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            r = json.loads(line)
            if sd.RESULT_MARKER in r.get('text', '') and not r.get('err'):
                res[r['q']] = r['text']
    return res


def votes(it, res):
    """{字: 书名集合}。只算另一侧前两字也吻合、或片段在此截断的命中。"""
    L, R = sd.T2S.convert(it['L']), sd.T2S.convert(it['R'])
    out = collections.defaultdict(set)
    for q, left in ((it['ql'], True), (it['qr'], False)):
        for raw, nm, book, _ in sd.snippets(res.get(q, '')):
            pat = re.escape(L) + '(.)' if left else '(.)' + re.escape(R)
            for m in re.finditer(pat, nm):
                i = m.start(1)
                other = nm[i + 1:i + 3] if left else nm[max(0, i - 2):i]
                want = R[:2] if left else L[-2:]
                if len(other) == 2 and len(want) == 2 and other != want:
                    continue
                c = raw[i] if len(raw) == len(nm) else nm[i]
                if c not in NOISE:
                    out[sd.T2S.convert(c)].add(book_name(book))
    return out


def verdict(past, a, b):
    if past == 'reject':
        return 'overturn_reject' if not a and len(b) >= 2 else ('weak' if len(a) < 2 and len(b) < 2 else '')
    if a or not b:
        return 'overturn_accept'
    return '' if len(b) >= 2 else 'weak'


def cmd_analyze(args):
    items = json.load(open(os.path.join(args.work, 'items.json'), encoding='utf-8'))
    res = load_results(args.work)
    rows, stat = [], collections.Counter()
    for it in items:
        if not all(q in res for q in (it['ql'], it['qr']) if len(q) >= 3):
            stat['pending'] += 1
            continue
        stat['done'] += 1
        v = votes(it, res)
        k = it['k']
        a, b = v.get(sd.T2S.convert(it['original'][k]), set()), v.get(sd.T2S.convert(it['proposed'][k]), set())
        res_v = verdict(it['past'], a, b)
        stat[res_v or 'agree'] += 1
        if res_v:
            other = {c: x for c, x in v.items() if x is not a and x is not b}
            rows.append(dict(key=it['key'], decision='', verdict=res_v, past=it['past'], file=it['file'], idx=it['idx'],
                             author=it['author'], title=it['title'], original=it['original'], proposed=it['proposed'],
                             original_books=' '.join(sorted(a)), proposed_books=' '.join(sorted(b)),
                             other=' '.join(f"{c}:{'/'.join(sorted(x))}" for c, x in other.items())))
    order = {'overturn_reject': 0, 'overturn_accept': 1, 'weak': 2}
    rows.sort(key=lambda r: order[r['verdict']])
    with open(os.path.join(args.work, 'recheck.tsv'), 'w', encoding='utf-8', newline='') as fp:
        w = csv.DictWriter(fp, delimiter='\t', fieldnames=['key', 'decision', 'verdict', 'past', 'file', 'idx', 'author',
                                                           'title', 'original', 'proposed', 'original_books',
                                                           'proposed_books', 'other'])
        w.writeheader()
        w.writerows(rows)
    state = dict(stat, queries_done=sum(1 for q in json.load(open(os.path.join(args.work, 'queries.json'), encoding='utf-8')) if q in res))
    json.dump(state, open(os.path.join(args.work, 'state.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(state, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('snapshot')
    p.add_argument('--review', required=True)
    p.add_argument('--skip', required=True)
    p.add_argument('--out', default=SNAPSHOT)
    p.set_defaults(fn=cmd_snapshot)
    for name, fn in (('plan', cmd_plan), ('analyze', cmd_analyze)):
        p = sub.add_parser(name)
        p.add_argument('--work', required=True)
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()
