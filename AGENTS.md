# AGENTS.md — chinese-poetry Dataset Maintenance

Instructions for AI agents contributing to this dataset. Currently one active task:

---

## Task: Fix Typos & Garbled Characters (乱码修复)

Community task: systematically review all JSON poetry files and fix typos and garbled characters. Progress is tracked in `fix_progress.json` so contributors (human or AI) can pick up where others left off.

---

### Step 1 — Find the next 5 files to review

Files are processed in **priority order**: known-issue files first, then alphabetically by path.

Run this script to get your next batch:

```python
import os, json, re

ROOT = os.path.dirname(os.path.abspath('fix_progress.json'))
SKIP = {'author', 'rank', 'settings', '表面结构字', 'error', 'fix_progress'}
SKIP_DIRS = {'loader', 'strains', 'images', 'rank', '.git', '.claude'}
CYRILLIC_GREEK = re.compile(r'[Ѐ-ӿͰ-Ͽ]')

# Build full file list (alphabetical)
all_files = []
for dirpath, dirs, filenames in os.walk(ROOT):
    dirs[:] = sorted([d for d in dirs if d not in SKIP_DIRS])
    for f in sorted(filenames):
        if not f.endswith('.json') or any(s in f for s in SKIP):
            continue
        rel = os.path.relpath(os.path.join(dirpath, f), ROOT)
        all_files.append(rel)

with open(os.path.join(ROOT, 'fix_progress.json'), 'r', encoding='utf-8') as fp:
    progress = json.load(fp)

reviewed = set(progress.get('reviewed', {}).keys())
pending = [f for f in all_files if f not in reviewed]

# Priority 1: files with confirmed Cyrillic/Greek characters
priority = []
normal = []
for rel in pending:
    fpath = os.path.join(ROOT, rel)
    try:
        content = open(fpath, encoding='utf-8').read()
        if CYRILLIC_GREEK.search(content):
            priority.append(rel)
        else:
            normal.append(rel)
    except Exception:
        normal.append(rel)

queue = priority + normal
print(f"Total: {len(all_files)} | Reviewed: {len(reviewed)} | Pending: {len(pending)}")
print(f"Priority (Cyrillic/Greek detected): {len(priority)}")
print("\nNext 5 files:")
for f in queue[:5]:
    tag = " ⚠ Cyrillic/Greek detected" if f in priority else ""
    print(f"  {f}{tag}")
```

Pick the first 5 from the output.

---

### Step 2 — Review each file

For each file, read it fully and check for the following:

#### 2a. Cyrillic / Greek garbled characters (highest priority)

Encoding errors where non-Chinese characters replaced Chinese ones. Always wrong in poetry text.

Known offenders in this dataset:

| Wrong | Unicode | Likely correct | Confirmed example                      |
|-------|---------|----------------|----------------------------------------|
| и     | U+0438  | 婵             | 风月正и娟 → 风月正婵娟                        |
| б     | U+0431  | 婵             | 风月正б娟 → 风月正婵娟                        |
| Н     | U+041D  | 潺             | НН绕城萦市 → 潺潺绕城萦市                      |
| ь     | U+044C  | 枝             | 一ь杨柳作腰肢 → 一枝杨柳作腰肢                    |
| Α     | U+0391  | 秩             | 七Α开颜 → 七秩开颜                          |
| Ι     | U+0399  | 徽             | Ι州 → 徽州                              |
| Θ     | U+0398  | 种             | Θ瓜邵平 → 种瓜邵平                          |
| с     | U+0441  | □ (lacuna)     | 只守伯禽法，с野万云烟 → □野万云烟 (《全宋词》底本缺字) |
| М     | U+041C  | 剉 / 挫          | 斋时М → 斋时剉；眼М了 → 眼挫了               |
| Λ     | U+039B  | ?              | determine from context + sources below |

The same symbol does not always map to the same character (и and б both → 婵; Θ → 种 but Θ迁 → 鉏麑), so verify every occurrence against a source.

Japanese kana and bopomofo (e.g. け然 → 翛然, 荼コ → 荼蘼, ゐ惶 → 恓惶, 不会ㄐ → 不会搊) are the same kind of garble. The title separator `・` (U+30FB) is legitimate.

**Detection**: regex `[Ѐ-ӿͰ-Ͽ]` (Cyrillic/Greek) and `[぀-ヺー-ヿ㄀-ㄯㆠ-ㆿ]` (kana/bopomofo). `python3 scripts/check_structure.py` runs these and other structural checks over the whole dataset, including `title` fields (元曲 titles contain body text).

**Correction approach** (in order of confidence):
1. Obvious from immediate context (single character gap, clear word/phrase)
2. Look up the poem by title/author in authoritative sources (see §Authoritative Sources)
3. Infer from meter (平仄) and rhyme scheme
4. If still uncertain → mark `needs_review`, do not guess

#### 2b. PUA characters (U+E000–U+F8FF)

`{...}` notation like `{疒}`, `{厓厂=}` = **intentional** placeholders for rare unencoded characters. Leave them alone.

Bare PUA chars outside `{}` in sentence body may be genuine errors — check context and sources before changing.

#### 2c. General typos (错别字)

Typo detection requires assessing your own confidence before acting. Apply the following tiers:

**Tier 1 — Fix directly**

You can name the work, author, and the correct line from your training data. Fix the character and cite the source in the `note` field.

Example: "枫叶荻花秋索索" → you recognize《琵琶行》by 白居易，the correct line is "秋瑟瑟". Fix it.

**Tier 2 — Mark `needs_review`, do not fix**

The line reads strangely or a character seems wrong, but you cannot recall the authoritative text with confidence. Add a `needs_review` entry describing what looks suspicious and why. Do not guess.

**Tier 3 — Skip typo checking entirely**

You do not recognize the poem at all. Only apply the mechanical scans (Cyrillic/Greek, PUA). A missed error is safer than a hallucinated "fix".

The threshold in plain terms: **if you are not willing to stake your confidence on it, do not change it.**

Common typo patterns when Tier 1 applies:
- Look-alike (形近字): 日/曰，己/已/巳，戊/戌/戍，土/士，末/未
- Sound-alike (音近字): 关/光，索索/瑟瑟

#### 2d. Do not change

- `·` (U+00B7) in titles like `《宋史·乐志》` — standard Chinese punctuation
- Traditional/simplified variants — intentional
- Archaic character forms

---

### Step 3 — Authoritative sources for verification

When context alone is insufficient, look up the poem in these sources (in order of preference):

| Source | URL | Notes |
|--------|-----|-------|
| 搜韵网 | https://sou-yun.cn | Comprehensive poetry search with rhyme annotation; good for Tang/Song |
| 古文岛 | https://www.guwendao.net | Covers most canonical works; good full-text search |
| 汉典 | https://www.zdic.net | Character-level dictionary; use for verifying individual characters |
| 识典古籍 | https://www.shidianguji.com | Full-text search over scanned editions (OCR + page images), cites book / 卷 / page; independent of web-crawled texts. Best source for 元曲/散曲 (《雍熙乐府》《词林摘艳》《盛世词林》 etc.). Search URL: `https://www.shidianguji.com/search/<query>` (simplified display) or `https://www.shidianguji.com/zh/search/<query>` (traditional display); texts are mostly unpunctuated, so search a 4–6 character run without punctuation. Both displays are automatic conversions, not the original glyphs: simplified display turns rare chars into 类推简化 forms (搊→𫼝, 篘→𫇴, 紞→𬘘), traditional display can over-convert (卜→蔔). Use the traditional display to read a rare character, then write it in the form this dataset already uses (e.g. 䕷 not 𧃲, 裀 not 䄄) |

Search by: poem title (`rhythmic` field) + author (`author` field). Compare the suspect line against the authoritative version character by character.

**Caveat for 元曲**: 古文岛/古诗文网's 元曲 texts largely share this dataset's crawled source and often carry the same garbled characters (e.g. `阁门珠路Λ`). It sometimes lists a second, proofread version of the same piece — use only a version without the garble, and prefer 识典古籍 when the two disagree.

If the authoritative source shows a different character, that is strong evidence for a fix. Record the source URL in the `note` field of your fix entry.

If neither source covers the poem, mark it `needs_review` — do not infer from uncertain sources such as crowdsourced wikis or link-aggregator sites.

---

### Step 3b — Batch tools (dataset-wide, alternative to the per-file loop)

Per-file review cannot scale to rare poems you do not recognize. These tools fix whole categories of defects with 识典古籍 as evidence, and leave every decision reviewable.

| Tool | Purpose |
|------|---------|
| `scripts/check_structure.py` | Scan the whole dataset: garbles (Cyrillic/Greek, kana/bopomofo, box-drawing, U+FFFD, bare PUA, ASCII residue), `□` gaps, line-length and 词牌 anomalies. Report only. |
| `scripts/twin_fix.py` | Collate 御定全唐詩 against 全唐诗/poet.tang.* and restore ASCII residue codes via `scripts/yuding_codes.tsv`. |
| `scripts/shidian.py` + `scripts/shidian/search.mjs` | Evidence pipeline: `build` → search 识典古籍 → `analyze` → review `review.tsv` → `apply`. |

```bash
pip install opencc-python-reimplemented
(cd scripts/shidian && npm install && npx playwright install chromium)
W=/tmp/sd_kana                                   # work dir — never inside the data directories
python3 scripts/shidian.py build --check kana_bopomofo --work $W
node scripts/shidian/search.mjs $W/queries.json $W/results.jsonl   # add --cdp http://127.0.0.1:9333 to reuse an open browser
python3 scripts/shidian.py analyze --work $W     # writes $W/review.tsv
# review: decision column = accept / reject / verified / or type the correct text yourself
python3 scripts/shidian.py apply --work $W --reviewer <model or handle> --date YYYY-MM-DD [--record-pending]
```

Rules built into `analyze` (learned the hard way — keep them if you change it):
- **Garbles replaced a character outside GB2312.** Every confirmed 御定 residue code but one, and every kana/PUA garble, hides a non-GB2312 character, so GB2312 candidates are OCR noise and are dropped. Exceptions exist for edition variants (e.g. 纤纤 vs 攕攕) — flag them in the note.
- **The same garble symbol or PUA code point can stand for different characters** in different files; each occurrence needs its own evidence.
- **`□` gaps** are mostly lacunae in the base text. Filling one from another edition needs ≥2 independent books; if a book shows a box-like OCR char (`口 囗 丶 〇`) at the same spot, the source has the same gap — do not fill.
- **Compare in simplified form** (`t2s` on both sides) so variants like 峯/峰 do not hide matches, but **write back with the dataset's own glyphs**: change only the inserted/deleted character, and use the form the dataset already uses (e.g. 搊 not 𫼝, 䕷 not 𧃲, 殢 not 𣨼).
- **Line edits next to garbage are not line edits**: `noisy` status means the sentence touches a residue/garble — replace that token instead of inserting a character.
- `missing_char` and `ascii_residue` are slow (thousands of queries); expect ~4 s per query, run overnight, and reruns resume where they stopped.

---

### Step 4 — Fix and update progress

1. **Edit the file**: change only the erroneous characters, nothing else.

2. **Update `fix_progress.json`** — add each reviewed file to the `reviewed` object:

```json
{
  "reviewed": {
    "宋词/ci.song.13000.json": {
      "date": "YYYY-MM-DD",
      "reviewer": "<AI model name or GitHub handle>",
      "status": "clean",
      "fixes": []
    },
    "元曲/yuanqu.json": {
      "date": "YYYY-MM-DD",
      "reviewer": "<AI model name or GitHub handle>",
      "status": "fixed",
      "fixes": [
        {
          "original": "Θ瓜邵平",
          "corrected": "种瓜邵平",
          "note": "Greek Θ → 种; verified at https://www.gushiwen.cn/..."
        }
      ]
    }
  }
}
```

Status values:
- `clean` — no issues found
- `fixed` — issues found and corrected
- `needs_review` — suspicious but not corrected; include details in `fixes` with `corrected: null`

Also increment the top-level `stats` counters (`reviewed`, `clean`, `fixed`, `needs_review`).

---

### Step 5 — Report

After the batch, summarize:
- Files processed and their status
- Total characters fixed
- Any `needs_review` items with the suspect text and your reasoning
- Overall progress: X / 1589 files reviewed

**Do not commit.** The maintainer will review and commit manually.
