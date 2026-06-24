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
SKIP = {'author', 'rank', 'settings', '表面结构字', 'error'}
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
| с     | U+0441  | ?              | determine from context + sources below |
| М     | U+041C  | ?              | determine from context + sources below |
| Λ     | U+039B  | ?              | determine from context + sources below |

**Detection**: regex `[Ѐ-ӿͰ-Ͽ]`

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

Search by: poem title (`rhythmic` field) + author (`author` field). Compare the suspect line against the authoritative version character by character.

If the authoritative source shows a different character, that is strong evidence for a fix. Record the source URL in the `note` field of your fix entry.

If neither source covers the poem, mark it `needs_review` — do not infer from uncertain sources such as crowdsourced wikis or link-aggregator sites.

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
