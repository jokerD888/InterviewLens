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

## Files changed

| File | Change |
|------|--------|
| `pyproject.toml` | Added `json-repair` dependency |
| `llm/schema.py` | Expanded RoundType and Category enums + JSON schema |
| `llm/extractor.py` | Level/round_type/category pre-normalization, max_tokens=8192 |
| `llm/deepseek.py` | JSON repair fallback via `json-repair` |
