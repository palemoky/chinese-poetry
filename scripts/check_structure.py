#!/usr/bin/env python3
"""结构 / 字符层面的自动质检，只报告可疑位置，不修改任何数据。

检查项：
  shi_line_length  诗：整首以五言或七言为主，个别句子字数多/少 1~2 字（疑漏字、衍字）
  ci_pattern       词：与同词牌主流体式相比总字数差 1~2 字，且该字数极少见（疑漏字、衍字）
  ascii_residue    正文中混入的 ASCII 字母/数字（爬取残渣，如 z5、zB）
  cyrillic_greek   西里尔 / 希腊字母乱码
  kana_bopomofo    日文假名 / 注音符号乱码
  box_drawing      制表符号乱码（┾ ╆ 等）与 U+FFFD 替换符
  symbol_garble    竖排标点兼容形（﹀ ︽ 等）、罗马数字（ⅲ ⅶ 等）与日文叠字符号「々」
  simplified_in_trad  繁体书写的诗（全唐诗/poet.*）里混入的简化字（來→来、時→时 等），见 docs/繁体混入简化字.md
  dup_punct        重复标点（？。 ！。 。。 ，， 、、）
  half_width_punct 紧邻汉字的半角 , ; : !
  bare_pua         {...} 之外的私用区字符
  missing_char     □ 缺字
  author_truncated 作者名只剩一个字（导入时丢掉了 GB2312 以外的字，如 向子諲 → 向），诗词文件与作者表都查
  作者字段（author，作者表的 name）同样做乱码检查（西里尔/希腊、假名注音、竖排符号、私用区、U+FFFD）

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
# 竖排标点兼容形与罗马数字是同类乱码（﹀︽ → 僝僽，ⅲ → 𨠑）；「々」不是中文用字，叠字一律写出本字（塺々 → 塺塺）
SYMBOL_GARBLE = re.compile(r'[\ufe30-\ufe4f\u2160-\u217f\u3005]')
PUA = re.compile(r'[-]')
# 繁体诗中混入的简化字 → 繁体正字。只收《简化字总表》中的简化字，且在这批文本里只有一个对应的繁体字。
# 不收字形或异体差异（黄/黃、却/卻、别/別、户/戶、泪/淚、叠/疊……）：底本大量使用，属于原貌，不改；
# 也不收本身就是古字的简化字（无、凭、尔、号），它们在古书里可能本来就这样写，需逐处核对。
# 判定依据与完整的排除清单见 docs/繁体混入简化字.md。
SIMPLIFIED_IN_TRAD = dict(zip(
    '带来将随盖壮堕楼装莱隐数峡鱼寝禅稳属挟惨弹碍惬箧蒋状义萧胆屡巩螀爱蝇两蝉粮偬单夹糁陕聪袜惮峣掺浃侠赍麦颜瞩蟏径墙趋舣毵媭'
    '赠妆惧郸挝殚钴鼹黪闻题馀残笔纷献响赐屦担婵飙狭辀箓荚飔蛱嘱飗鳀时东谁声过乐问语经寻断虽谢说陈齐拟条环炉琼腾颠绵样赊鹃缐'
    '块缝觐钺飨俩偻颢渑鳖徕窭讫硖衅渗娈颣亸骦襕狝锧梼帮浉柠',
    '帶來將隨蓋壯墮樓裝萊隱數峽魚寢禪穩屬挾慘彈礙愜篋蔣狀義蕭膽屢鞏螿愛蠅兩蟬糧傯單夾糝陝聰襪憚嶢摻浹俠齎麥顏矚蠨徑牆趨艤毿嬃'
    '贈妝懼鄲撾殫鈷鼴黲聞題餘殘筆紛獻響賜屨擔嬋飆狹輈籙莢颸蛺囑飀鯷時東誰聲過樂問語經尋斷雖謝說陳齊擬條環爐瓊騰顛綿樣賒鵑線'
    '塊縫覲鉞饗倆僂顥澠鱉徠窶訖硤釁滲孌纇嚲驦襴獮鑕檮幫溮檸'))
TRAD_POEM_FILE = re.compile(r'^全唐诗/poet\.[a-z]+\.\d+\.json$')


def written_in_simplified(text):
    """整首以简体录入的诗不算混入，跳过。繁体文本里总有 GB2312 编不了的繁体字（風、雲、來……），
    简体文本几乎没有；这类字比表中的简化字还少，就无从判断是繁体，当作简体书写。
    与 OpenCC 的简繁判定对比过：没有一首繁体诗因此被跳过。"""
    simp = sum(c in SIMPLIFIED_IN_TRAD for c in text)
    return simp > 0 and non_gb2312_hanzi(text) < simp


def non_gb2312_hanzi(text):
    n = 0
    for c in HANZI_BMP.findall(text):
        try:
            c.encode('gb2312')
        except UnicodeEncodeError:
            n += 1
    return n


HANZI_BMP = re.compile(r'[\u4e00-\u9fff]')


def check_simplified_in_trad(rel, idx, it, lines, report):
    if not TRAD_POEM_FILE.match(rel.replace(os.sep, '/')):
        return
    title = it.get('title') if isinstance(it.get('title'), str) else ''
    if written_in_simplified(title + ''.join(lines)):
        return
    for field, texts in (('title', [title]), ('paragraphs', lines)):
        for text in texts:
            for c in text:
                if c in SIMPLIFIED_IN_TRAD:
                    report('simplified_in_trad', rel, idx, it, f'[{field}] {text}', token=c, detail=f'{c}→{SIMPLIFIED_IN_TRAD[c]}')


CI_DIRS = {'宋词', '五代诗词'}
SHI_DIRS = {'全唐诗', '水墨唐诗', '曹操诗集', '纳兰性德'}  # 元曲有衬字，不做字数检查


# 这些检查项一旦增加即视为退化（CI 失败）；缺字、字数异常等多为底本原貌，仅作提示
STRICT = ('bad_json', 'cyrillic_greek', 'kana_bopomofo', 'symbol_garble', 'box_drawing', 'bare_pua', 'ascii_residue',
          'dup_punct', 'half_width_punct', 'simplified_in_trad', 'author_truncated')
AUTHOR_TABLE = re.compile(r'(^|/)authors?\.[^/]*\.json$')   # 作者表：全唐诗/authors.*.json、宋词/author.song.json 等


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
    """去夹注与校勘方括号，生僻字占位折算为 1 个字符。"""
    s = NOTE.sub('', s)
    s = PLACEHOLDER.sub('〇', s)
    return s.replace('[', '').replace(']', '')


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
                         ('symbol_garble', SYMBOL_GARBLE), ('box_drawing', BOX_DRAWING), ('bare_pua', PUA), ('ascii_residue', ASCII_RES),
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
                             ('symbol_garble', SYMBOL_GARBLE), ('bare_pua', PUA)):
                for m in rx.finditer(body):
                    report(kind, rel, idx, it, f'[{field}] {text}', token=m.group())
    check_author_name(rel, idx, it, it.get('author'), 'author', report)


AUTHOR_GARBLES = (('cyrillic_greek', CYRILLIC_GREEK), ('kana_bopomofo', KANA_BOPOMOFO),
                  ('symbol_garble', SYMBOL_GARBLE), ('box_drawing', BOX_DRAWING), ('bare_pua', PUA))


def check_author_name(rel, idx, it, name, field, report):
    """作者名：乱码，以及只剩一个字（宋词导入时丢掉了 GB2312 以外的字，「张鎡」成了「张」，不同词人被并成一个）。"""
    if not isinstance(name, str):
        return
    body = PLACEHOLDER.sub('', name)
    for kind, rx in AUTHOR_GARBLES:
        for m in rx.finditer(body):
            report(kind, rel, idx, it, f'[{field}] {name}', token=m.group())
    if len(name.strip()) == 1:
        report('author_truncated', rel, idx, it, f'[{field}] {name}', token=name.strip())


def iter_author_tables():
    for dirpath, dirs, filenames in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, f), ROOT)
            if AUTHOR_TABLE.search(rel.replace(os.sep, '/')):
                yield rel


def check_author_tables(report):
    for rel in iter_author_tables():
        with open(os.path.join(ROOT, rel), encoding='utf-8') as fp:
            data = json.load(fp)
        for idx, it in enumerate(data if isinstance(data, list) else []):
            if isinstance(it, dict):
                check_author_name(rel, idx, {'author': it.get('name'), 'title': '作者表'}, it.get('name'), 'name', report)


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
                   detail=f'{main}言诗中出现 {len(s)} 字句')


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

    def report(kind, rel, idx, it, text, token=None, detail=None):
        findings.append({'check': kind, 'file': rel, 'index': idx, 'poem': label(it),
                         'text': text, 'token': token, 'detail': detail})

    ci_poems = []
    for rel in iter_files():
        top = rel.split(os.sep)[0]
        try:
            poems = list(iter_poems(rel))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            report('bad_json', rel, -1, {}, str(e))
            continue
        for idx, it, lines in poems:
            check_chars(rel, idx, it, lines, report)
            check_simplified_in_trad(rel, idx, it, lines, report)
            if top in CI_DIRS and it.get('rhythmic'):
                ci_poems.append((rel, idx, it, lines))
            elif top in SHI_DIRS:
                check_shi(rel, idx, it, lines, report)
    check_ci(ci_poems, report)
    check_author_tables(report)

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
        if kind == 'ascii_residue':
            top = collections.Counter(f['token'] for f in items).most_common(15)
            print('   高频残渣:', '  '.join(f'{t}×{n}' for t, n in top))
        for f in items[:args.show]:
            extra = f" | {f['detail']}" if f['detail'] else ''
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
