"""Empirical evaluation of BGE-M3 embedding similarities on real entity pairs.

Measures actual cosine similarity distributions on Chinese/English company
and position pairs (both positive synonyms and hard negatives/incompatibles).
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

TOK_PATH = r"D:\code\InferPilot\artifacts\bge-m3-tokenizer"
MODEL_PATH = r"D:\code\InferPilot\artifacts\bge-m3.onnx"

# Comprehensive test pairs:
COMPANY_POSITIVE_PAIRS = [
    ("字节", "字节跳动"),
    ("ByteDance", "字节跳动"),
    ("阿里", "阿里巴巴"),
    ("Alibaba", "阿里巴巴"),
    ("腾讯", "腾讯科技"),
    ("Tencent", "腾讯"),
    ("美团", "美团点评"),
    ("快手", "快手科技"),
    ("拼多多", "PDD"),
    ("小红书", "RED"),
    ("微软", "Microsoft"),
    ("谷歌", "Google"),
    ("百度", "百度在线"),
    ("滴滴", "滴滴出行"),
    ("网易", "网易游戏"),
]

COMPANY_NEGATIVE_PAIRS = [
    ("字节跳动", "快手"),
    ("阿里巴巴", "腾讯"),
    ("美团", "饿了么"),
    ("百度", "腾讯"),
    ("小红书", "知乎"),
    ("拼多多", "京东"),
    ("商汤科技", "旷视科技"),
    ("微软", "谷歌"),
    ("腾讯", "网易"),
    ("快手", "Bilibili"),
    ("华为", "中兴"),
    ("滴滴", "美团"),
]

POSITION_POSITIVE_PAIRS = [
    ("后端开发", "后端工程师"),
    ("后端开发", "服务端开发"),
    ("Java开发", "Java工程师"),
    ("Java开发", "Java后台开发"),
    ("前端开发", "前端工程师"),
    ("前端开发", "Web前端开发"),
    ("算法工程师", "算法研究员"),
    ("机器学习工程师", "算法工程师"),
    ("测试开发", "测开工程师"),
    ("测试开发", "质量保障工程师"),
    ("Android开发", "安卓开发工程师"),
    ("iOS开发", "iOS软件工程师"),
    ("客户端开发", "移动端开发"),
    ("数据分析师", "数据分析"),
    ("运维工程师", "SRE工程师"),
    ("Go开发", "Golang后端开发"),
    ("C++开发", "C++后台开发"),
]

POSITION_NEGATIVE_PAIRS = [
    ("前端开发", "后端开发"),
    ("Java开发", "Go开发"),
    ("Java开发", "C++开发"),
    ("Android开发", "iOS开发"),
    ("测试开发", "后端开发"),
    ("测试开发", "前端开发"),
    ("算法工程师", "后端开发"),
    ("算法工程师", "数据分析师"),
    ("产品经理", "项目经理"),
    ("前端开发", "移动端开发"),
    ("数据分析师", "数据开发工程师"),
    ("运维工程师", "开发工程师"),
    ("架构师", "测试开发"),
    ("UI设计师", "前端开发"),
    ("客户端开发", "服务端开发"),
]


def load_model_and_tokenizer():
    tokenizer = AutoTokenizer.from_pretrained(TOK_PATH)
    session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
    return tokenizer, session


def encode_texts(tokenizer, session, texts: list[str]) -> np.ndarray:
    encoded = tokenizer(texts, padding=True, truncation=True, max_length=128, return_tensors="np")
    inputs = {
        "input_ids": encoded["input_ids"].astype(np.int64),
        "attention_mask": encoded["attention_mask"].astype(np.int64),
    }
    outputs = session.run(None, inputs)
    cls_vec = outputs[0][:, 0]
    norms = np.linalg.norm(cls_vec, axis=1, keepdims=True)
    return cls_vec / np.maximum(norms, 1e-12)


def evaluate():
    tokenizer, session = load_model_and_tokenizer()

    all_groups = {
        "company_positive": COMPANY_POSITIVE_PAIRS,
        "company_negative": COMPANY_NEGATIVE_PAIRS,
        "position_positive": POSITION_POSITIVE_PAIRS,
        "position_negative": POSITION_NEGATIVE_PAIRS,
    }

    results = {}
    for group_name, pairs in all_groups.items():
        pair_results = []
        for a, b in pairs:
            vecs = encode_texts(tokenizer, session, [a, b])
            sim = float(np.dot(vecs[0], vecs[1]))
            pair_results.append({"pair": (a, b), "similarity": sim})

        sims = [item["similarity"] for item in pair_results]
        results[group_name] = {
            "pairs": pair_results,
            "min": float(np.min(sims)),
            "max": float(np.max(sims)),
            "mean": float(np.mean(sims)),
            "median": float(np.median(sims)),
            "p25": float(np.percentile(sims, 25)),
            "p75": float(np.percentile(sims, 75)),
        }

    # Evaluate current threshold 0.85
    threshold = 0.85
    pos_sims = (
        [item["similarity"] for item in results["company_positive"]["pairs"]]
        + [item["similarity"] for item in results["position_positive"]["pairs"]]
    )
    neg_sims = (
        [item["similarity"] for item in results["company_negative"]["pairs"]]
        + [item["similarity"] for item in results["position_negative"]["pairs"]]
    )

    fp_pairs = [
        item for g in ["company_negative", "position_negative"]
        for item in results[g]["pairs"]
        if item["similarity"] >= threshold
    ]
    fn_pairs = [
        item for g in ["company_positive", "position_positive"]
        for item in results[g]["pairs"]
        if item["similarity"] < threshold
    ]

    report = {
        "threshold": threshold,
        "total_positive_pairs": len(pos_sims),
        "total_negative_pairs": len(neg_sims),
        "false_positives_count": len(fp_pairs),
        "false_negatives_count": len(fn_pairs),
        "false_positive_rate": len(fp_pairs) / len(neg_sims) if neg_sims else 0.0,
        "false_positive_examples": fp_pairs,
        "false_negative_examples": fn_pairs,
        "group_stats": {
            k: {
                "min": v["min"],
                "max": v["max"],
                "mean": v["mean"],
                "median": v["median"],
                "p25": v["p25"],
                "p75": v["p75"],
            }
            for k, v in results.items()
        },
        "all_details": results,
    }

    out_file = Path("bge_m3_empirical_benchmark.json")
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Benchmark finished and written to {out_file.absolute()}")
    print("=" * 60)
    print("EMPIRICAL BENCHMARK SUMMARY (BGE-M3 Dense Cosine):")
    for group_name, stat in report["group_stats"].items():
        print(f"[{group_name:18s}] min: {stat['min']:.4f} | max: {stat['max']:.4f} | mean: {stat['mean']:.4f} | median: {stat['median']:.4f}")
    print("-" * 60)
    print(f"At default threshold EMBED_THRESHOLD_HIGH = {threshold}:")
    print(f"  False Positives (Fatal auto-merge bugs!): {len(fp_pairs)} / {len(neg_sims)} (FPR = {len(fp_pairs)/len(neg_sims):.2%})")
    for fp in fp_pairs:
        print(f"    - DANGER: {fp['pair'][0]} <-> {fp['pair'][1]} : sim = {fp['similarity']:.4f} >= {threshold}")
    print(f"  False Negatives (Synonyms falling through to LLM): {len(fn_pairs)} / {len(pos_sims)}")
    for fn in fn_pairs:
        print(f"    - INFO (Requires Tier3 LLM): {fn['pair'][0]} <-> {fn['pair'][1]} : sim = {fn['similarity']:.4f} < {threshold}")
    print("=" * 60)


if __name__ == "__main__":
    evaluate()
