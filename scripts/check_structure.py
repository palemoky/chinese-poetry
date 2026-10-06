#!/usr/bin/env python3
"""结构 / 字符层面的自动质检，只报告可疑位置，不修改任何数据。

检查项：
  shi_line_length  诗：整首以五言或七言为主，个别句子字数多/少 1~2 字（疑漏字、衍字）
  ci_pattern       词：与同词牌主流体式相比总字数差 1~2 字，且该字数极少见（疑漏字、衍字）
  ascii_residue    正文中混入的 ASCII 字母/数字（爬取残渣，如 z5、zB）
  cyrillic_greek   西里尔 / 希腊字母乱码
  kana_bopomofo    日文假名 / 注音符号乱码
  box_drawing      制表符号乱码（┾ ╆ 等）与 U+FFFD 替换符
  dup_punct        重复标点（？。 ！。 。。 ，， 、、）
  half_width_punct 紧邻汉字的半角 , ; : !
  bare_pua         {...} 之外的私用区字符
  missing_char     □ 缺字

用法：
  python3 scripts/check_structure.py --baseline scripts/check_baseline.json   # CI：乱码类数量不得增加
  python3 scripts/check_structure.py --write-baseline scripts/check_baseline.json   # 修复后更新基线
  python3 scripts/check_structure.py                 # 打印汇总
  python3 scripts/check_structure.py --out r.jsonl   # 同时输出逐条明细（JSON Lines）
  python3 scripts/check_structure.py --only ci_pattern --show 20
"""
import argparse
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {'author', 'rank', 'settings', '表面结构字', 'error', 'fix_progress'}
SKIP_DIRS = {'loader', 'strains', 'images', 'rank', 'error', 'scripts', 'docs', '.git', '.claude', '.github'}

SENT_SPLIT = re.compile(r'[，。！？；、,!?;：:]')
NOTE = re.compile(r'（[^）]*）|\([^)]*\)')           # 夹注，如（一作……）
PLACEHOLDER = re.compile(r'\{[^}]*\}')               # {疒} 等生僻字占位，计 1 字
FOOTNOTE = re.compile(r'\[\d+\]|〖\d+〗')          # 脚注 / 校注标号 [1] 〖1〗
ZAYAN_TITLE = re.compile(r'[歌行吟引曲謠谣辭辞詞词句]')  # 歌行杂言、摘句，句长本就不齐
ASCII_RES = re.compile(r'[A-Za-z0-9]+')
HANZI = re.compile(r'[\u3400-\u9fff\U00020000-\U0003ffff\ue000-\uf8ff□〇]')
CYRILLIC_GREEK = re.compile(r'[Ѐ-ӿͰ-Ͽ]')
BOX_DRAWING = re.compile(r'[\u2500-\u257f\ufffd]')   # 制表符号乱码与 U+FFFD 替换符（GBK 字节错位）
DUP_PUNCT = re.compile(r'？。|！。|。。|，，|、、')                 # 已规整过的重复标点
HALF_PUNCT = re.compile(r'(?<=[\u4e00-\u9fff])[,;:!]|[,;:!](?=[\u4e00-\u9fff])')   # 紧邻汉字的半角标点
KANA_BOPOMOFO = re.compile(r'[\u3040-\u30fa\u30fc-\u30ff\u3100-\u312f\u31a0-\u31bf]')  # 假名、注音乱码（不含标题分隔符・）
PUA = re.compile(r'[-]')
CI_DIRS = {'宋词', '五代诗词'}
SHI_DIRS = {'全唐诗', '御定全唐詩', '水墨唐诗', '曹操诗集', '纳兰性德'}  # 元曲有衬字，不做字数检查


# 这些检查项一旦增加即视为退化（CI 失败）；缺字、字数异常等多为底本原貌，仅作提示
STRICT = ('bad_json', 'cyrillic_greek', 'kana_bopomofo', 'box_drawing', 'bare_pua', 'ascii_residue',
          'dup_punct', 'half_width_punct')


def iter_files():
    for dirpath, dirs, filenames in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(filenames):
            if f.endswith('.json') and not any(s in f for s in SKIP):
                yield os.path.relpath(os.path.join(dirpath, f), ROOT)


def iter_poems(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fp:
        data = json.load(fp)
    items = data if isinstance(data, list) else [data]
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        lines = it.get('paragraphs') or it.get('para') or it.get('content')
        if isinstance(lines, str):
            lines = [lines]
        if not isinstance(lines, list) or not all(isinstance(s, str) for s in lines):
            continue
        yield idx, it, lines


def clean(s):
    """去夹注与校勘方括号，生僻字占位折算为 1 个字符，叠字符号「々」展开为前一字。"""
    s = NOTE.sub('', s)
    s = PLACEHOLDER.sub('〇', s)
    s = s.replace('[', '').replace(']', '')
    return re.sub(r'(.)々', r'\1\1', s)


def sentences(lines):
    """按标点切句，每句只保留汉字（书名号、引号等不计字数）。"""
    out = []
    for line in lines:
        for x in SENT_SPLIT.split(clean(line)):
            x = ''.join(HANZI.findall(x))
            if x:
                out.append(x)
    return out


def label(it):
    return f"{it.get('author', '')}《{it.get('title') or it.get('rhythmic') or ''}》"


def check_chars(rel, idx, it, lines, report):
    for line in lines:
        body = FOOTNOTE.sub('', PLACEHOLDER.sub('', line))
        for kind, rx in (('cyrillic_greek', CYRILLIC_GREEK), ('kana_bopomofo', KANA_BOPOMOFO),
                         ('box_drawing', BOX_DRAWING), ('bare_pua', PUA), ('ascii_residue', ASCII_RES),
                         ('dup_punct', DUP_PUNCT), ('half_width_punct', HALF_PUNCT)):
            for m in rx.finditer(body):
                report(kind, rel, idx, it, line, token=m.group())
        if '□' in line:
            report('missing_char', rel, idx, it, line, token='□')
    # 元曲等的标题里混有正文片段，乱码同样会出现在标题中
    for field in ('title', 'rhythmic'):
        text = it.get(field)
        if isinstance(text, str):
            body = PLACEHOLDER.sub('', text)
            for kind, rx in (('cyrillic_greek', CYRILLIC_GREEK), ('kana_bopomofo', KANA_BOPOMOFO),
                             ('bare_pua', PUA)):
                for m in rx.finditer(body):
                    report(kind, rel, idx, it, f'[{field}] {text}', token=m.group())


LEGIT_ODD = re.compile(r'^君不[見见]|^嗚呼|^呜呼|兮')    # 歌行常见的合法加字


def check_shi(rel, idx, it, lines, report):
    sents = sentences(lines)
    if len(sents) < 4:
        return
    lens = collections.Counter(len(s) for s in sents)
    main, n = lens.most_common(1)[0]
    if main not in (5, 7) or n / len(sents) < 0.9 or ZAYAN_TITLE.search(it.get('title') or ''):
        return
    for i, s in enumerate(sents):
        if abs(len(s) - main) == 1 and not LEGIT_ODD.search(s):
            report('shi_line_length', rel, idx, it, s,
                   detail=f'{main}言诗中出现 {len(s)} 字句',
                   ctx={'main': main, 'prev': sents[i - 1] if i else None,
                        'next': sents[i + 1] if i + 1 < len(sents) else None})


def one_edit(short, long_):
    """long_ 删去一个字后等于 short。"""
    return len(long_) == len(short) + 1 and any(
        long_[:k] + long_[k + 1:] == short for k in range(len(long_)))


# 全唐诗 与 御定全唐詩 是同一部书的两个独立来源，可互相对勘
TWIN_SOURCES = {'qts': lambda rel: rel.startswith(os.path.join('全唐诗', 'poet.tang.')),
                'yd': lambda rel: rel.startswith('御定全唐詩' + os.sep)}


def source_of(rel):
    return next((k for k, f in TWIN_SOURCES.items() if f(rel)), None)


def cross_check(findings, neighbor):
    """为字数异常句在另一来源中找对应句：找到「多/少一字」的版本即给出修正候选。"""
    for f in findings:
        if f['check'] != 'shi_line_length' or not source_of(f['file']):
            continue
        other = 'yd' if source_of(f['file']) == 'qts' else 'qts'
        ctx, s = f.pop('ctx'), f['text']
        cands = set()
        if ctx['prev']:
            cands |= neighbor[other]['after'].get(ctx['prev'], set())
        if ctx['next']:
            cands |= neighbor[other]['before'].get(ctx['next'], set())
        if s in cands:
            f['cross'] = 'same'          # 两个来源一致，多半是底本原貌
        else:
            fix = [c for c in cands if len(c) == ctx['main'] and
                   (one_edit(s, c) or one_edit(c, s))]
            if fix:
                f['cross'] = 'candidate'
                f['suggest'] = fix[0]
    for f in findings:
        f.pop('ctx', None)


def ci_tune(it):
    name = (it.get('rhythmic') or '').strip()
    return re.split(r'[・·]', name)[-1] if name else ''


def ci_anomalies(ci_poems):
    """与同词牌主流体式相比总字数差 1~2 字、且该字数极少见的词。

    逐首产出 dict：rel/idx/it/sents/tune/total/main_total/main_n/n_poems/count，
    以及 bad = [(句序, 常体句长), ...]（句数与常体一致且只有 1~2 句不同时），否则为 None。
    """
    groups = collections.defaultdict(list)
    for rel, idx, it, lines in ci_poems:
        sents = sentences(lines)
        if sents and '□' not in ''.join(lines):     # 缺字的另由 missing_char 处理
            groups[ci_tune(it)].append((rel, idx, it, sents))
    for tune, poems in groups.items():
        if len(poems) < 10:
            continue
        totals = collections.Counter(sum(map(len, p[3])) for p in poems)
        main_total, main_n = totals.most_common(1)[0]
        if main_n / len(poems) < 0.4:
            continue
        # 主流体式的句式（句长序列）
        main_sig = collections.Counter(
            tuple(map(len, p[3])) for p in poems if sum(map(len, p[3])) == main_total
        ).most_common(1)[0][0]
        for rel, idx, it, sents in poems:
            total = sum(map(len, sents))
            diff = total - main_total
            if not diff or abs(diff) > 2 or totals[total] / len(poems) > 0.03:
                continue
            sig = tuple(map(len, sents))
            bad = None
            if len(sig) == len(main_sig):
                bad = [(i, main_sig[i]) for i, (a, b) in enumerate(zip(sig, main_sig)) if a != b]
                if len(bad) > 2:
                    bad = None
            yield dict(rel=rel, idx=idx, it=it, sents=sents, tune=tune, total=total,
                       main_total=main_total, main_n=main_n, n_poems=len(poems),
                       count=totals[total], bad=bad)


def check_ci(ci_poems, report):
    for a in ci_anomalies(ci_poems):
        sents = a['sents']
        where = '；'.join(f'「{sents[i]}」{len(sents[i])}字(常体{n})' for i, n in a['bad'] or [])
        report('ci_pattern', a['rel'], a['idx'], a['it'], where,
               detail=f"{a['tune']} 共{a['total']}字，常体{a['main_total']}字"
                      f"（{a['main_n']}/{a['n_poems']}首），本字数仅{a['count']}首")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', help='逐条明细输出路径（.jsonl）')
    ap.add_argument('--only', help='只显示某类检查')
    ap.add_argument('--show', type=int, default=5, help='每类展示的样例数')
    ap.add_argument('--baseline', help='与基线比较：STRICT 类检查的数量若增加则以非零状态退出（用于 CI）')
    ap.add_argument('--write-baseline', help='把当前各类数量写为基线')
    args = ap.parse_args()

    findings = []

    def report(kind, rel, idx, it, text, token=None, detail=None, ctx=None):
        findings.append({'check': kind, 'file': rel, 'index': idx, 'poem': label(it),
                         'text': text, 'token': token, 'detail': detail, 'ctx': ctx})

    # 句子邻接索引：source -> {'after': 前句 -> 后句集合, 'before': 后句 -> 前句集合}
    neighbor = {k: {'after': collections.defaultdict(set), 'before': collections.defaultdict(set)}
                for k in TWIN_SOURCES}
    ci_poems = []
    for rel in iter_files():
        top = rel.split(os.sep)[0]
        try:
            poems = list(iter_poems(rel))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            report('bad_json', rel, -1, {}, str(e))
            continue
        src = source_of(rel)
        for idx, it, lines in poems:
            check_chars(rel, idx, it, lines, report)
            if src:
                sents = sentences(lines)
                for a, b in zip(sents, sents[1:]):
                    neighbor[src]['after'][a].add(b)
                    neighbor[src]['before'][b].add(a)
            if top in CI_DIRS and it.get('rhythmic'):
                ci_poems.append((rel, idx, it, lines))
            elif top in SHI_DIRS:
                check_shi(rel, idx, it, lines, report)
    check_ci(ci_poems, report)
    cross_check(findings, neighbor)

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fp:
            for f in findings:
                fp.write(json.dumps(f, ensure_ascii=False) + '\n')

    by_kind = collections.defaultdict(list)
    for f in findings:
        by_kind[f['check']].append(f)
    for kind, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        if args.only and kind != args.only:
            continue
        files = len({f['file'] for f in items})
        print(f'\n== {kind}: {len(items)} 处，涉及 {files} 个文件')
        if kind == 'shi_line_length':
            c = collections.Counter(f.get('cross', 'unmatched') for f in items)
            print(f"   对勘：有修正候选 {c['candidate']}，另一来源相同 {c['same']}，未匹配 {c['unmatched']}")
            items = sorted(items, key=lambda f: f.get('cross') != 'candidate')
        if kind == 'ascii_residue':
            top = collections.Counter(f['token'] for f in items).most_common(15)
            print('   高频残渣:', '  '.join(f'{t}×{n}' for t, n in top))
        for f in items[:args.show]:
            extra = f" | {f['detail']}" if f['detail'] else ''
            if f.get('cross') == 'candidate':
                extra += f" | 对勘候选：{f['suggest']}"
            elif f.get('cross') == 'same':
                extra += ' | 另一来源相同'
            print(f"   {f['file']}#{f['index']} {f['poem']} {f['text']}{extra}")

    counts = {k: len(v) for k, v in sorted(by_kind.items())}
    if args.write_baseline:
        with open(args.write_baseline, 'w', encoding='utf-8') as fp:
            json.dump(counts, fp, ensure_ascii=False, indent=2)
            fp.write('\n')
        print(f'\nbaseline written: {args.write_baseline}')
    if args.baseline:
        with open(args.baseline, encoding='utf-8') as fp:
            base = json.load(fp)
        worse = {k: (base.get(k, 0), counts.get(k, 0)) for k in STRICT if counts.get(k, 0) > base.get(k, 0)}
        better = {k: (base.get(k, 0), counts.get(k, 0)) for k in base if counts.get(k, 0) < base[k]}
        if better:
            print('\n已减少（可用 --write-baseline 更新基线）：' + '，'.join(f'{k} {a}→{b}' for k, (a, b) in better.items()))
        if worse:
            print('\n::error::以下检查项比基线增加，请修正后再提交：' + '，'.join(f'{k} {a}→{b}' for k, (a, b) in worse.items()))
            return 1
        print('\n与基线比较：没有新增问题')
    return 0


if __name__ == '__main__':
    sys.exit(main())
