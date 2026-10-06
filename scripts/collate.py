#!/usr/bin/env python3
"""长期、低频的整部合集对勘：逐句与识典古籍比对，找出一字之差的错字。

为不给识典古籍造成压力，检索分多次、多日完成（每次 --limit 若干条），进度可随时中断与续跑。
完整说明见 docs/宋词对勘.md。

  python3 scripts/collate.py plan    --dir 宋词 --work ~/.cache/chinese-poetry/songci
  node   scripts/shidian/search.mjs  <work>/queries.json <work>/results.jsonl --limit 1200
  python3 scripts/collate.py analyze --work <work>          # 只判定检索已全部完成的作品
  # 审核 <work>/review.tsv 的 decision 列（accept / reject / 自填正确句子）
  python3 scripts/collate.py apply   --work <work> --reviewer <名字> --date YYYY-MM-DD
  python3 scripts/collate.py report  --work <work> --doc docs/宋词对勘.md
  python3 scripts/collate.py next    --work <work>          # 显示下一步要运行的命令

判定规则：
  - 比对前统一异体（OpenCC 繁简 + Unihan 语义/字形异体），工作目录首次分析时自动下载 Unihan
  - fix：他本读法有 ≥2 种古籍支持，且本库读法在检索到的古籍中一种都没有
  - 两读皆有古籍 → 异文不改；一常用一生僻 → 视为异体不改；古书通用字（INTERCHANGEABLE）不改
"""
import argparse
import collections
import csv
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_structure as cs  # noqa: E402
import shidian as sd  # noqa: E402

ROOT = cs.ROOT
STRIDE = 3       # 每隔几句设一个检索点（一条结果片段通常覆盖前后数句）
UNIHAN_URL = 'https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip'
# 古书通用、两写皆可的字对：不视为错字
INTERCHANGEABLE = {frozenset(p) for p in (
    '連聯 閒間 閑間 閒閑 靄藹 蹤縱 晏宴 顛巔 資姿 身生 采採 彩綵 采彩 彫雕 遊游 修脩 沈沉 闇暗 惟唯 唯維 '
    '惟維 歎嘆 蕭簫 楊揚 杖仗 疏疎 暖煖 樽尊 妝粧 卻却 回迴 嶽岳 巖岩 並并 於于 彷仿 佛彿 鍾鐘 冥暝 逕徑 '
    '雲云 后後 穀谷 台臺 籍藉 託托 凰皇 寞莫 展輾 閣閤 只祗 坐座 縣懸 闌欄 熏薰 阪坂 凋彫 燃然 暮莫 旁傍 '
    '蓬篷 煉鍊 漫熳 由繇 磐盤 盤槃 途塗 溪谿 洲州 欹攲 嘯歗 筍笋 杯盃 綫線 鬭鬥 裏裡 個箇').split()}


INTERCHANGEABLE_S = {frozenset(sd.T2S.convert(c) for c in p) for p in INTERCHANGEABLE}


def interchangeable(a, b):
    """繁简两种数据通用：繁体数据直接比，简体数据转简体后比。"""
    return frozenset((a, b)) in INTERCHANGEABLE or frozenset((sd.T2S.convert(a), sd.T2S.convert(b))) in INTERCHANGEABLE_S


def norm_factory(work):
    path = os.path.join(work, 'variant_map.json')
    if not os.path.exists(path):
        print('downloading Unihan for variant normalization …')
        data = urllib.request.urlopen(UNIHAN_URL, timeout=120).read()
        text = zipfile.ZipFile(io.BytesIO(data)).read('Unihan_Variants.txt').decode('utf-8')
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for line in text.splitlines():
            if line.startswith('#') or not line.strip():
                continue
            cp, field, val = line.split('\t')
            if field in ('kSemanticVariant', 'kZVariant'):
                a = sd.T2S.convert(chr(int(cp[2:], 16)))
                for v in val.split():
                    b = sd.T2S.convert(chr(int(v.split('<')[0][2:], 16)))
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
        json.dump({c: find(c) for c in parent}, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
    vmap = json.load(open(path, encoding='utf-8'))
    return lambda t: ''.join(vmap.get(c, c) for c in sd.T2S.convert(t))


def gb(ch):
    try:
        sd.T2S.convert(ch).encode('gb2312')
        return True
    except UnicodeEncodeError:
        return False


# ---------------------------------------------------------------- plan

def cmd_plan(args):
    os.makedirs(args.work, exist_ok=True)
    poems, queries = [], []
    for rel in cs.iter_files():
        if rel.split(os.sep)[0] != args.dir:
            continue
        for idx, it, lines in cs.iter_poems(rel):
            sents = cs.sentences(lines)
            if not sents:
                continue
            t = [sd.to_trad(rel, s) for s in sents]
            qs = [t[i - 1][-3:] + t[i][:3] for i in range(1, len(t), STRIDE)] or [t[0][:6]]
            qs = [q for q in dict.fromkeys(qs) if len(q) >= 4]
            if not qs:
                continue
            poems.append(dict(file=rel, idx=idx, author=it.get('author'), title=it.get('rhythmic') or it.get('title'),
                              sents=sents, queries=qs))
            queries.extend(qs)
    queries = list(dict.fromkeys(queries))       # 保持作品顺序，便于按作品逐批完成
    json.dump(poems, open(os.path.join(args.work, 'poems.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(queries, open(os.path.join(args.work, 'queries.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(dict(dir=args.dir, poems=len(poems), sentences=sum(len(p['sents']) for p in poems), queries=len(queries)),
              open(os.path.join(args.work, 'plan.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'{args.dir}: {len(poems)} poems, {sum(len(p["sents"]) for p in poems)} sentences, {len(queries)} queries → {args.work}')


# ---------------------------------------------------------------- analyze

def load_results(work):
    res = {}
    path = os.path.join(work, 'results.jsonl')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            r = json.loads(line)
            if r.get('text') and not r.get('err'):
                res[r['q']] = r['text']
    return res


def judge_sentence(norm, s, prev, nxt, snips):
    """返回 (as_is_books, {candidate: books})：只考虑同长度一字之差（形近/音近错字）。"""
    S, P, N = norm(s), norm(prev)[-2:], norm(nxt)[:2]
    as_is, cand = set(), collections.defaultdict(set)
    for raw, nsnip, book in snips:
        if P + S + N in nsnip or (S in nsnip and len(S) >= 4):
            as_is.add(book)
        if not (P or N):
            continue
        for m in re.finditer(re.escape(P) + f'(.{{{len(S)}}})' + re.escape(N), nsnip):
            t = m.group(1)
            diff = [k for k in range(len(S)) if S[k] != t[k]]
            if len(diff) == 1:
                k = diff[0]
                cand[(k, raw[m.start(1) + k])].add(book)
    return as_is, cand


def cmd_analyze(args):
    norm = norm_factory(args.work)
    poems = json.load(open(os.path.join(args.work, 'poems.json'), encoding='utf-8'))
    res = load_results(args.work)
    applied = set(json.load(open(os.path.join(args.work, 'applied.json')))) if os.path.exists(os.path.join(args.work, 'applied.json')) else set()
    rows, stat = [], collections.Counter()
    for p in poems:
        if not all(q in res for q in p['queries']):
            stat['poems_pending'] += 1
            continue
        stat['poems_done'] += 1
        snips = []
        for q in p['queries']:
            for raw, _, book, _ in sd.snippets(res[q]):
                n = norm(raw)
                snips.append((raw if len(raw) == len(n) else n, n, book))   # 长度变化时无法逐字对应原形
        sents = p['sents']
        for i, s in enumerate(sents):
            prev, nxt = (sents[i - 1] if i else ''), (sents[i + 1] if i + 1 < len(sents) else '')
            as_is, cand = judge_sentence(norm, s, prev, nxt, snips)
            if not cand and not as_is:
                stat['sent_unknown'] += 1
                continue
            if not cand:
                stat['sent_confirmed'] += 1
                continue
            (k, ch), books = max(cand.items(), key=lambda kv: len(kv[1]))
            ch = sd.to_dataset_script(p['file'], ch)
            wrong = s[k]
            if as_is or len(books) < 2 or gb(wrong) != gb(ch) or interchangeable(wrong, ch) \
                    or norm(wrong) == norm(ch):
                stat['sent_variant_or_weak'] += 1
                continue
            key = f"{p['file']}#{p['idx']}#{i}"
            if key in applied:
                stat['sent_applied'] += 1
                continue
            stat['sent_suspect'] += 1
            rows.append(dict(key=key, decision='accept', file=p['file'], idx=p['idx'], author=p['author'] or '',
                             title=p['title'] or '', original=s, proposed=s[:k] + ch + s[k + 1:],
                             evidence=f"{len(books)} books: {', '.join(sorted(books)[:3])}"))
    with open(os.path.join(args.work, 'review.tsv'), 'w', encoding='utf-8', newline='') as fp:
        w = csv.DictWriter(fp, delimiter='\t', fieldnames=['key', 'decision', 'file', 'idx', 'author', 'title',
                                                           'original', 'proposed', 'evidence'])
        w.writeheader()
        w.writerows(rows)
    state = dict(stat, queries_done=sum(1 for q in json.load(open(os.path.join(args.work, 'queries.json'))) if q in res))
    json.dump(state, open(os.path.join(args.work, 'state.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(state, ensure_ascii=False))
    print(f'review: {args.work}/review.tsv ({len(rows)} suspects; decision = accept / reject / 正确句子)')


# ---------------------------------------------------------------- apply

def cmd_apply(args):
    path_applied = os.path.join(args.work, 'applied.json')
    applied = set(json.load(open(path_applied))) if os.path.exists(path_applied) else set()
    rows = list(csv.DictReader(open(os.path.join(args.work, 'review.tsv'), encoding='utf-8'), delimiter='\t'))
    progress_path = os.path.join(ROOT, 'fix_progress.json')
    progress = json.load(open(progress_path, encoding='utf-8'))
    n = 0
    for row in rows:
        dec = (row['decision'] or '').strip()
        if row['key'] in applied or dec in ('', 'reject'):
            if dec == 'reject':
                applied.add(row['key'])        # 已人工否决，不再出现在审核表
            continue
        new = row['proposed'] if dec == 'accept' else dec
        rel, idx = row['file'], int(row['idx'])
        raw = open(os.path.join(ROOT, rel), encoding='utf-8').read()
        data = json.loads(raw)
        paras = data[idx]['paragraphs']
        hits = [(k, para) for k, para in enumerate(paras) if para.count(row['original']) == 1]
        if len(hits) != 1:
            print(f"skip {row['key']}: sentence not unique"); continue
        k, para = hits[0]
        newp = para.replace(row['original'], new, 1)
        o, nw = json.dumps(para, ensure_ascii=False), json.dumps(newp, ensure_ascii=False)
        if o not in raw:
            print(f"skip {row['key']}: text changed"); continue
        open(os.path.join(ROOT, rel), 'w', encoding='utf-8').write(raw.replace(o, nw, 1))
        e = progress['reviewed'].setdefault(rel, dict(status='clean', fixes=[]))
        e.setdefault('fixes', []).append(dict(original=row['original'], corrected=new, note=(
            f"Collation with 识典古籍 ({row['evidence']}); dataset reading attested in none of the retrieved books"
            + ('' if dec == 'accept' else '; corrected by reviewer'))))
        e['date'], e['reviewer'] = args.date, args.reviewer
        if e.get('status') == 'clean':
            e['status'] = 'fixed'
        applied.add(row['key'])
        n += 1
    sd.recompute_stats(progress)
    open(progress_path, 'w', encoding='utf-8').write(json.dumps(progress, ensure_ascii=False, indent=2))
    json.dump(sorted(applied), open(path_applied, 'w'), ensure_ascii=False)
    print(f'applied {n} corrections; {len(applied)} items closed in total')


# ---------------------------------------------------------------- report / next

def cmd_report(args):
    plan = json.load(open(os.path.join(args.work, 'plan.json')))
    state = json.load(open(os.path.join(args.work, 'state.json'))) if os.path.exists(os.path.join(args.work, 'state.json')) else {}
    applied = len(json.load(open(os.path.join(args.work, 'applied.json')))) if os.path.exists(os.path.join(args.work, 'applied.json')) else 0
    qd = state.get('queries_done', 0)
    table = '\n'.join([
        '| 项目 | 数值 |', '|------|------|',
        f"| 检索进度 | {qd:,} / {plan['queries']:,}（{qd / plan['queries']:.1%}） |",
        f"| 已完成作品 | {state.get('poems_done', 0):,} / {plan['poems']:,} |",
        f"| 原样得到古籍证实的句子 | {state.get('sent_confirmed', 0):,} |",
        f"| 异文或证据不足（不改） | {state.get('sent_variant_or_weak', 0):,} |",
        f"| 待审核疑似错字 | {state.get('sent_suspect', 0):,} |",
        f"| 已处理（写回或否决） | {applied:,} |",
        f"| 更新时间 | {args.date} |" if args.date else ''])
    doc = open(args.doc, encoding='utf-8').read()
    a, b = '<!-- progress:start -->', '<!-- progress:end -->'
    doc = doc[:doc.index(a) + len(a)] + '\n' + table.strip() + '\n' + doc[doc.index(b):]
    open(args.doc, 'w', encoding='utf-8').write(doc)
    print(table)


def cmd_next(args):
    plan = json.load(open(os.path.join(args.work, 'plan.json')))
    res = load_results(args.work)
    q = json.load(open(os.path.join(args.work, 'queries.json')))
    left = sum(1 for x in q if x not in res)
    print(f"{plan['dir']}: {len(q) - left:,}/{len(q):,} queries done, {left:,} left")
    print(f'  node scripts/shidian/search.mjs {args.work}/queries.json {args.work}/results.jsonl --limit 1200')
    print(f'  python3 scripts/collate.py analyze --work {args.work}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan'); p.add_argument('--dir', required=True); p.add_argument('--work', required=True)
    p = sub.add_parser('analyze'); p.add_argument('--work', required=True)
    p = sub.add_parser('apply'); p.add_argument('--work', required=True)
    p.add_argument('--reviewer', required=True); p.add_argument('--date', required=True)
    p = sub.add_parser('report'); p.add_argument('--work', required=True); p.add_argument('--doc', required=True)
    p.add_argument('--date')
    p = sub.add_parser('next'); p.add_argument('--work', required=True)
    args = ap.parse_args()
    args.work = os.path.expanduser(args.work)
    {'plan': cmd_plan, 'analyze': cmd_analyze, 'apply': cmd_apply, 'report': cmd_report, 'next': cmd_next}[args.cmd](args)


if __name__ == '__main__':
    main()
