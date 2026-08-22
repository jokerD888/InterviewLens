# Embedding Model Choice

## Current: `BAAI/bge-m3`（本地 `.env` 配置）

- 1024-dim, 569M params, 8192 token context
- Dense+Sparse+ColBERT 多检索方式，中英混合最强

## 决策历史：代码默认 `bge-large-zh-v1.5`

`config.py` 的代码默认值是 `BAAI/bge-large-zh-v1.5`（326M / ~1.3GB / 512 token），
最初选型理由：

| Factor | bge-m3 | bge-large-zh-v1.5 | Verdict |
|--------|--------|-------------------|---------|
| Target text | Single interview questions, 20-200 chars | 512 tokens → plenty of headroom | Tie |
| Language | Chinese + occasional English terms | Subword tokenization handles mixed text | Tie |
| Model size | 569M / ~2.2GB | 326M / ~1.3GB | zh-v1.5 wins (faster CPU) |
| Special features | Dense+Sparse+ColBERT, 8192 tokens | Dense only, 512 tokens | Our need: short Qs, Dense only → zh-v1.5 matches |

## 实际运行：`.env` 覆盖为 `bge-m3`

本地 `.env` 配置 `EMBEDDING_MODEL=BAAI/bge-m3`，实际运行使用 bge-m3。
两模型均为 1024 维，兼容 pgvector schema；`EMBEDDING_DIM=1024` 无需变更。
文件名 `bge_m3.py` 是历史命名（曾计划用 bge-m3，代码默认值后来定为 zh-v1.5，本地再覆盖回 bge-m3）。

面试表述：代码默认 `bge-large-zh-v1.5`，`.env` 覆盖为 `bge-m3`，实际运行是 bge-m3；两模型维度一致（1024）。

