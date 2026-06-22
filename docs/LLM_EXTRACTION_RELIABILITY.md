# LLM Extraction Reliability

## Issues encountered

### 1. Enum mismatch — DeepSeek returns values not in schema

**Symptom**: `ValidationError: Input should be '实习', '校招', '社招' or '未知'` etc.

**Root cause**: The LLM function call schema has strict enums (`RoundType`, `Category`, `Level`),
but DeepSeek sometimes returns plausible variations the schema doesn't cover.

| Field | LLM returned | Schema expected |
|-------|-------------|-----------------|
| `level` | "暑期实习" | "实习" |
| `round_type` | "笔试", "主管面", "技术四面" | only "技术一面/二面/三面/HR面/交叉面/其他" |
| `category` | "深度学习", "计算机体系结构" | 10 categories, none AI-specific |

**Fix**: 
- Expanded enum values (schema.py): added "笔试"/"主管面"/"技术四面" to RoundType,
  "深度学习"/"AI基础"/"大模型"/"计算机体系结构" to Category
- Pre-validation normalization (extractor.py): values not matching any enum are silently
  mapped to "其他" to avoid hard failures

### 2. Malformed JSON from DeepSeek

**Symptom**: `RuntimeError: Invalid JSON in tool args: Expecting ',' delimiter`

**Root cause**: DeepSeek occasionally produces minor JSON syntax errors in function call
arguments, such as missing commas between adjacent array elements or object keys.
Retries at lower temperature sometimes fix it, but not always.

**Fix**: Added `json-repair` library (PyPI: `json-repair`) as a fallback in `deepseek.py`.
When `json.loads()` fails, `repair_json()` attempts automatic correction before
raising an error.  This handles:

- Missing commas: `] "` → `], "`, `} {` → `}, {`, etc.
- Trailing commas: `,}` → `}`, `,]` → `]`
- Single-quoted strings
- Unclosed braces/brackets
- Extraneous text after valid JSON

### 3. JSON truncation for long posts

**Symptom**: `RuntimeError: Invalid JSON in tool args: Unterminated string`

**Root cause**: DeepSeek's default `max_tokens=4096` was insufficient for long posts
(e.g., 15-company aggregated interview summaries) with many questions, causing
the JSON output to be truncated mid-string.

**Fix**: Increased `max_tokens` to 8192 in extractor's `call_tool()` invocation.

## Architecture

All fixes are in the extractor call path:

```
DeepSeek response
  │
  ▼
json.loads(raw_args)        ← first attempt
  │
  ├── success → validate against ExtractedPost schema
  │                │
  │                ├── level normalisation ("暑期实习"→"实习")
  │                ├── round_type fallback (unknown→"其他")
  │                ├── category fallback   (unknown→"其他")
  │                └── model_validate()
  │
  └── failure → repair_json(raw_args)  ← json-repair library
                    │
                    ├── success → validate (same as above)
                    └── failure → retry LLM call (up to 3 attempts, temp→0)
```

## Known limitation: Image-only posts (imgMoment)

Some Nowcoder posts contain only screenshots (`momentData.imgMoment[]`) with no
text content. After cleaning, these yield fewer than 200 characters (mostly page
navigation crumbs) and are marked `extract_status='skipped'` with reason
`too_short`.

**Cannot fix with current setup** because `deepseek-v4-flash` is text-only.
DeepSeek's multimodal models (`DeepSeek-VL2`) are separate from the Chat API
and require a different integration.

Impact: ~5/400 posts (1.25%) — negligible. These posts are skipped silently
and do not affect question/answer data quality.

If image OCR becomes necessary in the future, options include:
- Integrate DeepSeek-VL2 multimodal API (separate endpoint, higher cost)
- Pre-process images with a local OCR tool (e.g. PaddleOCR) and feed text to existing pipeline

## Issue: Aggregate summaries displayed as raw JSON

### Symptom

Frontend shows raw JSON instead of formatted Markdown for ~50% of summaries:

```json
{ "high_frequency_topics": [{ "topic": "...", "sample_questions": [...] }], ... }
```

### Root cause

Chain of two failures in the aggregator pipeline:

1. **`edge_cases` type mismatch**: the prompt asks DeepSeek for `edge_cases` as an array, but
   the model sometimes returns a single object `{topic: ..., questions: [...]}`. The
   `render_aggregator_md()` function iterates over it expecting an array → `AttributeError`
   on dict key iteration.

2. **Retry fallback produces JSON again**: the exception triggers a free-form retry
   (no `response_format`). The retry reuses the same prompt which ends with
   "只输出 JSON，不要任何其他内容" → DeepSeek outputs JSON → stored as-is without rendering.

### Fix

1. **`render_aggregator_md()`** (`llm/prompts.py`): wrap single `edge_cases` object into a
   list before iterating; skip non-dict items gracefully.

2. **Remove retry fallback** (`aggregator/aggregator.py`): `response_format="json_object"`
   guarantees valid JSON from DeepSeek. `json-repair` handles rare parse failures.
   No need for a fallback that would store un-rendered JSON.

3. **Repair corrupted data**: query summaries where `content_md` is parseable as raw
   JSON → delete them → re-run aggregate. The good markdown summaries remain cached.

### Lessons

- `response_format="json_object"` with `json-repair` is sufficient; never store raw LLM
  output without deterministic post-processing.
- Renderer must be defensive against LLM type variance (array vs object, null fields).
- Database query for corrupt rows + targeted re-generation is better than a full rebuild.

## Files changed

| File | Change |
|------|--------|
| `pyproject.toml` | Added `json-repair` dependency |
| `llm/schema.py` | Expanded RoundType and Category enums + JSON schema |
| `llm/extractor.py` | Level/round_type/category pre-normalization, max_tokens=8192 |
| `llm/deepseek.py` | JSON repair fallback via `json-repair` |
