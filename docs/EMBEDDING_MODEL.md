# Embedding Model Choice

## Current: `BAAI/bge-large-zh-v1.5`

- 1024-dim, 326M params, 512 token context
- Chinese-optimized, lightweight (~1.3GB)

## Why not `bge-m3`

| Factor | bge-m3 | bge-large-zh-v1.5 | Verdict |
|--------|--------|-------------------|---------|
| Target text | Single interview questions, 20-200 chars | 512 tokens → plenty of headroom | Tie |
| Language | Chinese + occasional English terms | Subword tokenization handles mixed text | Tie |
| Model size | 569M / ~2.2GB | 326M / ~1.3GB | zh-v1.5 wins (faster CPU) |
| Special features | Dense+Sparse+ColBERT, 8192 tokens | Dense only, 512 tokens | Our need: short Qs, Dense only → zh-v1.5 matches |

## Decision: `bge-large-zh-v1.5`

Key reasons:
1. **Text is short**: each `questions.content` is a single interview question (20-200 chars),
   well within 512 token limit.
2. **English terms handled**: BERT subword tokenization naturally handles mixed
   Chinese-English text like "KV Cache 的原理是什么？"
3. **Smaller/faster**: 326M vs 569M params, ~40% faster CPU inference.
4. **Chinese-optimized**: specifically tuned for Chinese semantic retrieval.

If longer text embedding is needed in the future (e.g., full post content),
evaluate re-switching to bge-m3.
