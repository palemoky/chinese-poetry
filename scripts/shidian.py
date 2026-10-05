#!/usr/bin/env python3
"""以识典古籍（shidianguji.com）全文检索为证据，修复乱码、缺字与字数异常。

三步流程，中间产物都放在一个工作目录里（不要放进数据目录）：

  1. build    找出待处理位置，生成检索词
       python3 scripts/shidian.py build --check kana_bopomofo --work /tmp/sd
  2. 检索     node scripts/shidian/search.mjs /tmp/sd/queries.json /tmp/sd/results.jsonl
  3. analyze  比对检索结果，生成审核表 /tmp/sd/review.tsv
       python3 scripts/shidian.py analyze --work /tmp/sd
     审核：逐行检查 decision 列。自动判定可修的预填 accept，可改为 reject，
     或直接填写认定的正确文字（替换该位置 / 该句）；verified 表示「原样经古籍证实」。
  4. apply    按审核表写回数据，并记入 fix_progress.json
       python3 scripts/shidian.py apply --work /tmp/sd

支持的 --check（与 check_structure.py 同名）：
  kana_bopomofo / bare_pua / ascii_residue   乱码：原字必在 GB2312 之外（本数据集的规律）
  missing_char                               □ 缺字：更严格，需 ≥2 种古籍；原书同缺则不补
  shi_line_length / ci_pattern               字数异常句：比对原样与「多/少一字」的他本

依赖：pip install opencc-python-reimplemented；cd scripts/shidian && npm install && npx playwright install chromium
"""
import argparse
import collections
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_structure as cs  # noqa: E402

try:
    from opencc import OpenCC
except ImportError:
    sys.exit('需要 OpenCC：pip install opencc-python-reimplemented')

ROOT = cs.ROOT
S2T, T2S = OpenCC('s2t'), OpenCC('t2s')
HAN = re.compile(r'[㐀-鿿\U00020000-\U0003ffff]')
PUNCT = set('，。、；：？！“”‘’「」『』《》（）·・ 　,.;:?!…')
TRAD_DIRS = {'全唐诗', '御定全唐詩', '四书五经', '论语', '蒙学'}   # 繁体数据
BOXLIKE = set('口囗丶〇')            # 原书缺字方框常被 OCR 成这些字
TOKEN_CHECKS = {'kana_bopomofo', 'bare_pua', 'ascii_residue', 'missing_char'}
LINE_CHECKS = {'shi_line_length', 'ci_pattern'}
YD_CODE = re.compile(r'(?<![A-Za-z0-9_\[])([A-Za-z][A-Za-z0-9]{0,3}|[0-9][A-Za-z][A-Za-z0-9]{0,2})(?![A-Za-z0-9_\]])')


# ---------------------------------------------------------------- 通用

def is_trad(rel):
    return rel.split(os.sep)[0] in TRAD_DIRS


def to_trad(rel, text):
    return text if is_trad(rel) else S2T.convert(text)


def to_dataset_script(rel, text):
    return text if is_trad(rel) else T2S.convert(text)


def in_gb2312(text):
    try:
        T2S.convert(text).encode('gb2312')
        return True
    except UnicodeEncodeError:
        return False


def side(chars, n=6):
    """取紧邻的汉字上下文（跳过标点、遇到其他字符即停，叠字符号「々」展开）。"""
    out = ''
    for c in chars:
        if HAN.match(c):
            out += c
        elif c == '々' and out:
            out += out[-1]
        elif c in PUNCT or c.isspace():
            continue
        else:
            break
        if len(out) == n:
            break
    return out


def one_edit(a, b):
    return cs.one_edit(a, b) or cs.one_edit(b, a)


def load(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fp:
        return json.load(fp)


def snippets(text):
    """识典古籍结果页 → [(原样片段, 简体规整片段, 书名, 出处)]，片段只保留汉字。"""
    body = text.split('生成语料表格并进行分析', 1)[-1]
    for m in re.finditer(r'([^《》]{6,600}?)\s*《([^》]{1,40})》([^《]{0,80})', body):
        raw = ''.join(c for c in m.group(1) if HAN.match(c))
        norm = T2S.convert(raw)
        if len(norm) != len(raw):          # 简转后长度变化则不做位置映射
            norm = raw
        yield raw, norm, m.group(2), f"《{m.group(2)}》{m.group(3).split('，')[0].strip()}"


# ---------------------------------------------------------------- build

def iter_strings(rel, data):
    """产出 (idx, field, k, text, before_extra, after_extra)：正文各行与标题，带跨行上下文。"""
    items = data if isinstance(data, list) else [data]
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        paras = it.get('paragraphs') if isinstance(it.get('paragraphs'), list) else []
        for k, s in enumerate(paras):
            if isinstance(s, str):
                yield idx, it, 'paragraphs', k, s, ''.join(paras[:k]), ''.join(paras[k + 1:])
        for field in ('title', 'rhythmic'):
            if isinstance(it.get(field), str):
                # 元曲标题截取了正文首句，后接正文
                yield idx, it, field, None, it[field], '', ''.join(p for p in paras if isinstance(p, str))


def token_spans(check, rel, s):
    if check == 'kana_bopomofo':
        for m in re.finditer(cs.KANA_BOPOMOFO.pattern + '+', s):
            yield m.start(), m.end(), len(m.group())
    elif check == 'bare_pua':
        holders = [(a.start(), a.end()) for a in cs.PLACEHOLDER.finditer(s)]
        for m in cs.PUA.finditer(s):
            if not any(a <= m.start() < b for a, b in holders):
                yield m.start(), m.end(), 1
    elif check == 'ascii_residue':
        if not rel.startswith('御定全唐詩'):
            return                          # 编码残渣仅见于御定全唐詩；其他目录多为卷号、校注标记
        for m in YD_CODE.finditer(s):
            a, b = s[m.start() - 1:m.start()], s[m.end():m.end() + 1]
            if HAN.match(a or ' ') or HAN.match(b or ' '):
                yield m.start(), m.end(), 2 if len(m.group()) == 4 else 1
    elif check == 'missing_char':
        for m in re.finditer(r'□+', s):
            if m.end() - m.start() <= 4:
                yield m.start(), m.end(), m.end() - m.start()


def build_tokens(check):
    items = []
    for rel in cs.iter_files():
        try:
            data = load(rel)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for idx, it, field, k, s, before, after in iter_strings(rel, data):
            if check == 'missing_char' and field != 'paragraphs':
                continue
            for a, b, n in token_spans(check, rel, s):
                L = side((before + s[:a])[::-1])[::-1]
                R = side(s[b:] + after)
                if check == 'missing_char' and len(L) < 4 and len(R) < 4:
                    continue
                tL, tR = to_trad(rel, L), to_trad(rel, R)
                queries = list(dict.fromkeys(q for q in (tL[-6:], tR[:6], tL[-4:], tR[:4]) if len(q) >= 4))
                if not queries:
                    continue
                items.append(dict(check=check, file=rel, idx=idx, field=field, k=k, start=a, end=b,
                                  token=s[a:b], n=n, left=L, right=R, queries=queries,
                                  author=it.get('author'), title=it.get('title') or it.get('rhythmic'),
                                  ctx=s[max(0, a - 8):b + 8]))
    return items


def build_lines(check):
    found = []
    if check == 'shi_line_length':
        def report(kind, rel, idx, it, text, token=None, detail=None, ctx=None):
            if kind == 'shi_line_length':
                found.append((rel, idx, it, text, ctx['main'], ctx['prev'] or '', ctx['next'] or ''))
        for rel in cs.iter_files():
            if rel.split(os.sep)[0] in cs.SHI_DIRS:
                for idx, it, lines in cs.iter_poems(rel):
                    cs.check_shi(rel, idx, it, lines, report)
    else:
        ci = [(rel, idx, it, lines) for rel in cs.iter_files() if rel.split(os.sep)[0] in cs.CI_DIRS
              for idx, it, lines in cs.iter_poems(rel) if it.get('rhythmic')]
        for a in cs.ci_anomalies(ci):
            for i, main in a['bad'] or []:
                if abs(len(a['sents'][i]) - main) == 1:
                    sents = a['sents']
                    found.append((a['rel'], a['idx'], a['it'], sents[i], main,
                                  sents[i - 1] if i else '', sents[i + 1] if i + 1 < len(sents) else ''))
    items = []
    for rel, idx, it, s, main, prev, nxt in found:
        # 句子两侧须是标点或行首尾；否则多半紧挨着乱码/残渣，不能按「增删一字」处理
        raw = ''.join(p for p in it.get('paragraphs') or [] if isinstance(p, str))
        noisy = any((raw[m.start() - 1:m.start()] or '，') not in PUNCT or (raw[m.end():m.end() + 1] or '，') not in PUNCT
                    for m in re.finditer(re.escape(s), raw)) or s not in raw
        ts, tp, tn = to_trad(rel, s), to_trad(rel, prev), to_trad(rel, nxt)
        queries = [q for q in ((tp[-3:] + ts[:3]) if len(tp) >= 3 else '', (ts[-3:] + tn[:3]) if len(tn) >= 3 else '') if q]
        items.append(dict(check=check, file=rel, idx=idx, s=s, main=main, prev=prev, next=nxt, noisy=noisy,
                          queries=queries or [ts[:5]], author=it.get('author'),
                          title=it.get('title') or it.get('rhythmic'), ctx=s))
    return items


def cmd_build(args):
    os.makedirs(args.work, exist_ok=True)
    items = build_tokens(args.check) if args.check in TOKEN_CHECKS else build_lines(args.check)
    for i, it in enumerate(items):
        it['id'] = i
    queries = sorted({q for it in items for q in it['queries']})
    json.dump(items, open(os.path.join(args.work, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(queries, open(os.path.join(args.work, 'queries.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'{args.check}: {len(items)} items, {len(queries)} queries → {args.work}')
    print(f'next: node scripts/shidian/search.mjs {args.work}/queries.json {args.work}/results.jsonl [--cdp URL]')


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


def analyze_token(it, res):
    L, R, n = T2S.convert(to_trad(it['file'], it['left'])), T2S.convert(to_trad(it['file'], it['right'])), it['n']
    gap = it['check'] == 'missing_char'
    need = (2 if n == 1 else 3) if gap else 1
    votes, books, srcs, ctxlen = collections.Counter(), collections.defaultdict(set), collections.defaultdict(set), {}
    lacuna = set()
    seen = set()
    for q in it['queries']:
        for raw, norm, book, src in snippets(res.get(q, '')):
            if (norm, book) in seen:
                continue
            seen.add((norm, book))
            best = None
            for lk in range(min(6, len(L)), need - 1, -1):
                for rk in range(min(6, len(R)), need - 1, -1):
                    if lk + rk < 4 or (gap and (lk < need or rk < need)):
                        continue
                    m = re.search(re.escape(L[len(L) - lk:]) + f'([\\u3400-\\u9fff\\U00020000-\\U0003ffff]{{{n}}})' + re.escape(R[:rk]), norm)
                    if m and (best is None or lk + rk > best[1]):
                        best = (raw[m.start(1):m.end(1)], lk + rk)
            if not best:
                continue
            cand = best[0]
            if gap and BOXLIKE & set(cand):
                lacuna.add(book)
                continue
            votes[cand] += 1
            books[cand].add(book)
            srcs[cand].add(src)
            ctxlen[cand] = max(ctxlen.get(cand, 0), best[1])
    # 乱码的原字绝大多数在 GB2312 之外，GB2312 内的候选多为 OCR 误识：排在后面，且须更强证据
    gb = {c: (not gap) and any(in_gb2312(ch) for ch in c) for c in votes}
    cands = sorted(votes, key=lambda c: (gb[c], -len(books[c]), -ctxlen[c], -votes[c]))
    cands = [c for c in cands if not gb[c] or (len(books[c]) >= 2 and ctxlen[c] >= 6)]
    it['candidates'] = [dict(text=c, books=len(books[c]), hits=votes[c], ctx=ctxlen[c], gb2312=gb[c],
                             sources=sorted(srcs[c])[:3]) for c in cands[:4]]
    it['lacuna_books'] = sorted(lacuna)
    top = it['candidates'][0] if cands else None
    second = it['candidates'][1] if len(cands) > 1 else None
    if gap:
        ok = bool(top) and top['books'] >= 2 and (not second or top['books'] >= 2 * second['books']) \
            and len(lacuna) < top['books'] \
            and not (top['books'] < 3 and (T2S.convert(top['text'])[0] == L[-1:] or T2S.convert(top['text'])[-1] == R[:1]))
    else:
        ok = bool(top) and top['ctx'] >= 4 and (top['books'] >= 2 or top['hits'] >= 2) \
            and (not second or second['ctx'] < top['ctx'] or top['hits'] >= 2 * second['hits'])
    it['status'] = 'fix' if ok else ('source_lacuna' if gap and lacuna and not top else 'ambiguous' if top else 'none')
    it['proposed'] = to_dataset_script(it['file'], top['text']) if top else ''


def analyze_line(it, res):
    s, main = T2S.convert(to_trad(it['file'], it['s'])), it['main']
    tp, tn = T2S.convert(to_trad(it['file'], it['prev'])), T2S.convert(to_trad(it['file'], it['next']))
    P, N = tp[-2:], tn[:2]
    if not P and len(tn) >= 3:
        N = tn[:3]
    if not N and len(tp) >= 3:
        P = tp[-3:]
    as_is, cand, raw_form, seen = set(), collections.defaultdict(set), {}, set()
    for q in it['queries']:
        for raw, norm, book, src in snippets(res.get(q, '')):
            if (norm, book) in seen:
                continue
            seen.add((norm, book))
            if re.search(re.escape(P) + re.escape(s) + re.escape(N), norm):
                as_is.add(book)
            for m in re.finditer(re.escape(P) + f'([\\u3400-\\u9fff\\U00020000-\\U0003ffff]{{{main}}})' + re.escape(N), norm):
                t = m.group(1)
                if t != s and one_edit(s, t):
                    cand[t].add(book)
                    raw_form.setdefault(t, raw[m.start(1):m.end(1)])
    ranked = sorted(cand.items(), key=lambda kv: -len(kv[1]))
    it['candidates'] = [dict(text=t, books=len(b), sources=sorted(b)[:3]) for t, b in ranked[:4]]
    it['as_is_books'] = sorted(as_is)
    a, c = len(as_is), (len(ranked[0][1]) if ranked else 0)
    if c >= 2 and c >= 2 * a and (len(ranked) == 1 or c >= 2 * len(ranked[1][1])):
        it['status'] = 'noisy' if it.get('noisy') else 'fix'   # noisy：句旁有乱码/残渣，需人工替换
    elif a >= 2 and a >= 2 * c:
        it['status'] = 'as_is'
    else:
        it['status'] = 'ambiguous' if (a or c) else 'none'
    # 只把增删的那一个字施加到原句上，保留原句其余字形
    it['proposed'] = apply_edit(it['file'], it['s'], s, ranked[0][0], raw_form[ranked[0][0]]) if ranked else ''


def apply_edit(rel, orig, norm, target, target_raw):
    """norm（原句的简体规整形）→ target 是一字增删；把同样的增删施加到原句上，保留原句其余字形。
    插入的字取古籍原样字形 target_raw，再转成该目录的繁简。"""
    if len(target) == len(norm) + 1:
        j = next(k for k in range(len(target)) if target[:k] + target[k + 1:] == norm)
        return orig[:j] + to_dataset_script(rel, target_raw[j]) + orig[j:]
    j = next(k for k in range(len(norm)) if norm[:k] + norm[k + 1:] == target)
    return orig[:j] + orig[j + 1:]


def cmd_analyze(args):
    items = json.load(open(os.path.join(args.work, 'items.json'), encoding='utf-8'))
    res = load_results(args.work)
    missing = {q for it in items for q in it['queries']} - set(res)
    for it in items:
        (analyze_line if it['check'] in LINE_CHECKS else analyze_token)(it, res)
    json.dump(items, open(os.path.join(args.work, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open(os.path.join(args.work, 'review.tsv'), 'w', encoding='utf-8', newline='') as fp:
        w = csv.writer(fp, delimiter='\t')
        w.writerow(['id', 'status', 'decision', 'file', 'author', 'title', 'original', 'proposed', 'evidence'])
        for it in items:
            c = it['candidates'][0] if it['candidates'] else None
            if it['check'] in LINE_CHECKS:
                original = it['s']
                ev = (f"{c['books']} books: {', '.join(c['sources'])}" if c else '') + \
                     (f" | as-is in {len(it['as_is_books'])}: {', '.join(it['as_is_books'][:3])}" if it['as_is_books'] else '')
            else:
                original = it['ctx']
                ev = '; '.join(f"{x['text']}×{x['books']}书{x['hits']}次 {x['sources'][0] if x['sources'] else ''}" for x in it['candidates'][:3])
                if it.get('lacuna_books'):
                    ev += f" | 原书同缺: {', '.join(it['lacuna_books'][:3])}"
            decision = {'fix': 'accept', 'as_is': 'verified'}.get(it['status'], '')
            w.writerow([it['id'], it['status'], decision, it['file'], it.get('author') or '', it.get('title') or '',
                        original, it['proposed'], ev])
    c = collections.Counter(it['status'] for it in items)
    print(f"{len(items)} items: " + ', '.join(f'{k} {v}' for k, v in c.most_common()))
    if missing:
        print(f'warning: {len(missing)} queries have no results yet — rerun search.mjs to retry them')
    print(f'review: {args.work}/review.tsv (edit the decision column), then: python3 scripts/shidian.py apply --work {args.work}')


# ---------------------------------------------------------------- apply

def recompute_stats(progress):
    st = progress.setdefault('stats', {})
    statuses = collections.Counter(e.get('status') for e in progress['reviewed'].values())
    st['reviewed'] = len(progress['reviewed'])
    for k in ('clean', 'fixed', 'needs_review'):
        st[k] = statuses.get(k, 0)


def cmd_apply(args):
    items = {it['id']: it for it in json.load(open(os.path.join(args.work, 'items.json'), encoding='utf-8'))}
    rows = list(csv.DictReader(open(os.path.join(args.work, 'review.tsv'), encoding='utf-8'), delimiter='\t'))
    progress_path = os.path.join(ROOT, 'fix_progress.json')
    progress = json.load(open(progress_path, encoding='utf-8'))
    edits = collections.defaultdict(list)          # (file, idx, field, k) -> [(start, end, new)]
    records = collections.defaultdict(list)
    for row in rows:
        it, dec = items[int(row['id'])], (row['decision'] or '').strip()
        c = it['candidates'][0] if it['candidates'] else None
        if dec in ('', 'reject'):
            if args.record_pending and it['status'] != 'source_lacuna':
                records[it['file']].append(dict(original=row['original'], corrected=None, note=(
                    f"needs_review [{it['check']}]: 识典古籍 evidence insufficient" + (f"; candidates: {row['evidence']}" if row['evidence'] else ''))))
            continue
        if dec == 'verified':
            records[it['file']].append(dict(original=row['original'], corrected=row['original'], note=(
                f"[{it['check']}] attested as-is in {len(it.get('as_is_books', []))} books on 识典古籍 "
                f"({', '.join(it.get('as_is_books', [])[:3])}); no change")))
            continue
        new = it['proposed'] if dec == 'accept' else dec
        if it['check'] in LINE_CHECKS:
            data = load(it['file'])
            paras = data[it['idx']]['paragraphs']
            hits = [(k, p) for k, p in enumerate(paras) if it['s'] in p]
            if len(hits) != 1 or hits[0][1].count(it['s']) != 1:
                print(f"skip #{it['id']}: sentence not unique in poem"); continue
            k, p = hits[0]
            a = p.index(it['s'])
            edits[(it['file'], it['idx'], 'paragraphs', k)].append((a, a + len(it['s']), new))
            corrected = new
        else:
            edits[(it['file'], it['idx'], it['field'], it['k'])].append((it['start'], it['end'], new))
            corrected = it['ctx'].replace(it['token'], new, 1)
        src = ', '.join(c['sources'][:2]) if c else ''
        shown = it['s'] if 'token' not in it else ''.join(f'U+{ord(ch):04X}' if cs.PUA.match(ch) else ch for ch in it['token'])
        note = (f"[{it['check']}] {shown} → {new}; 识典古籍"
                + (f" ({c['books']} books, e.g. {src})" if c else '') + ('' if dec == 'accept' else '; decided by reviewer'))
        records[it['file']].append(dict(original=row['original'], corrected=corrected, note=note))

    by_file = collections.defaultdict(dict)
    for key, spans in edits.items():
        by_file[key[0]][key[1:]] = spans
    for rel, keyed in by_file.items():
        path = os.path.join(ROOT, rel)
        raw = open(path, encoding='utf-8').read()
        data = json.loads(raw)
        items_ = data if isinstance(data, list) else [data]
        for (idx, field, k), spans in keyed.items():
            old = items_[idx][field][k] if k is not None else items_[idx][field]
            new = old
            for a, b, txt in sorted(spans, reverse=True):
                new = new[:a] + txt + new[b:]
            o, n = json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False)
            if o in raw:
                raw = raw.replace(o, n, 1)          # 按原文替换，不重新序列化，保持文件格式
            elif n not in raw:
                print(f'skip {rel}#{idx}: original text not found')
        open(path, 'w', encoding='utf-8').write(raw)

    for rel, fx in records.items():
        e = progress['reviewed'].setdefault(rel, dict(status='clean', fixes=[]))
        e.setdefault('fixes', [])
        known = {(x['original'], x['corrected']) for x in e['fixes']}
        for x in fx:
            if (x['original'], x['corrected']) in known:
                continue
            # 同一位置已有 needs_review 记录：就地更新，而不是另起一条
            old = next((y for y in e['fixes'] if y['corrected'] is None and y['original'] == x['original']), None)
            if old is not None and x['corrected'] is not None:
                old['corrected'] = x['corrected']
                old['note'] += f" | resolved {args.date}: {x['note']}"
            elif old is None:
                e['fixes'].append(x)
        e['date'], e['reviewer'] = args.date, args.reviewer
        if any(x['corrected'] is None for x in e['fixes']):
            e['status'] = 'needs_review'
        elif any(x['corrected'] != x['original'] for x in e['fixes']):
            e['status'] = 'fixed'
    recompute_stats(progress)
    open(progress_path, 'w', encoding='utf-8').write(json.dumps(progress, ensure_ascii=False, indent=2))
    n_fix = sum(len(v) for v in edits.values())
    print(f'applied {n_fix} edits in {len(by_file)} files; recorded {sum(len(v) for v in records.values())} entries in fix_progress.json')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--check', required=True, choices=sorted(TOKEN_CHECKS | LINE_CHECKS))
    b.add_argument('--work', required=True)
    a = sub.add_parser('analyze')
    a.add_argument('--work', required=True)
    p = sub.add_parser('apply')
    p.add_argument('--work', required=True)
    p.add_argument('--reviewer', required=True, help='AI model name or GitHub handle')
    p.add_argument('--date', required=True, help='YYYY-MM-DD')
    p.add_argument('--record-pending', action='store_true', help='also record undecided items as needs_review')
    args = ap.parse_args()
    {'build': cmd_build, 'analyze': cmd_analyze, 'apply': cmd_apply}[args.cmd](args)


if __name__ == '__main__':
    main()
