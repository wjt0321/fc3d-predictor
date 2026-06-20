#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
福彩3D娱乐预测器 (FC 3D Predictor)

参考 lottery-predictor-main 双色球项目风格：
- 多专家（hot/cold/missing/cycle/sum/balanced/random）按位打分
- 历史数据驱动，支持回测
- 输出带解释，仅供娱乐，不构成投注建议
"""

import argparse
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

DATA_FILE = "fc3d_data.json"
ARCHIVE_DIR = "fc3d_archive"
ALL_DIGITS = list(range(10))


@dataclass
class FC3DRecord:
    period: str
    date: str
    digits: List[int]

    @property
    def sum_value(self) -> int:
        return sum(self.digits)

    @property
    def span(self) -> int:
        return max(self.digits) - min(self.digits)

    def as_number(self) -> str:
        return "".join(str(d) for d in self.digits)


@dataclass
class PredictionResult:
    number: str
    digits: List[int]
    score: float
    sum_value: int
    span: int
    explain: Dict[str, float] = field(default_factory=dict)


def load_data(data_path: str) -> List[FC3DRecord]:
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"数据文件不存在: {data_path}，请先创建或导入数据")
    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    records = [
        FC3DRecord(
            period=str(r.get("period", "")),
            date=str(r.get("date", "")),
            digits=[int(d) for d in r["digits"]],
        )
        for r in raw.get("records", [])
        if "digits" in r and len(r["digits"]) == 3
    ]
    # 按日期倒序，records[0] 为最新一期
    records.sort(key=lambda x: x.date, reverse=True)
    return records


def save_data(data_path: str, records: List[FC3DRecord]) -> None:
    payload = {
        "metadata": {
            "total_records": len(records),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "manual",
        },
        "records": [
            {"period": r.period, "date": r.date, "digits": r.digits} for r in records
        ],
    }
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def recent_window(records: List[FC3DRecord], n: int) -> List[FC3DRecord]:
    return records[:n] if n > 0 else records


def digit_position_frequency(records: List[FC3DRecord]) -> List[Counter]:
    """返回3个位置的数字频率 Counter 列表"""
    counters = [Counter() for _ in range(3)]
    for r in records:
        for i, d in enumerate(r.digits):
            counters[i][d] += 1
    return counters


def digit_overall_frequency(records: List[FC3DRecord]) -> Counter:
    c = Counter()
    for r in records:
        c.update(r.digits)
    return c


def missing_gaps(records: List[FC3DRecord]) -> Dict[int, int]:
    """每个数字距离上次出现的期数间隔（0表示最近一期出现）"""
    gaps = {d: float("inf") for d in ALL_DIGITS}
    for i, r in enumerate(records):
        for d in set(r.digits):
            if gaps[d] == float("inf"):
                gaps[d] = i
    return {d: (g if g != float("inf") else len(records)) for d, g in gaps.items()}


def normalize_scores(scores: Dict[int, float]) -> Dict[int, float]:
    values = list(scores.values())
    if not values:
        return scores
    min_v, max_v = min(values), max(values)
    if max_v - min_v < 1e-9:
        return {k: 1.0 for k in scores}
    return {k: (v - min_v) / (max_v - min_v) for k, v in scores.items()}


def hot_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """追热：近期高频数字得分高"""
    pos_freq = digit_position_frequency(records[:60])
    pos_scores = [normalize_scores({d: float(c[d]) for d in ALL_DIGITS}) for c in pos_freq]
    overall = digit_overall_frequency(records[:60])
    overall_scores = normalize_scores({d: float(overall[d]) for d in ALL_DIGITS})
    # 位置分与全局热号融合
    fused = []
    for p in pos_scores:
        fused.append(normalize_scores({d: p[d] * 0.6 + overall_scores[d] * 0.4 for d in ALL_DIGITS}))
    return fused, {"window": 60, "type": "hot"}


def cold_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """追冷：近期低频数字得分高"""
    pos_freq = digit_position_frequency(records[:60])
    pos_scores = [normalize_scores({d: 1.0 / (1.0 + c[d]) for d in ALL_DIGITS}) for c in pos_freq]
    overall = digit_overall_frequency(records[:60])
    overall_scores = normalize_scores({d: 1.0 / (1.0 + overall[d]) for d in ALL_DIGITS})
    fused = []
    for p in pos_scores:
        fused.append(normalize_scores({d: p[d] * 0.6 + overall_scores[d] * 0.4 for d in ALL_DIGITS}))
    return fused, {"window": 60, "type": "cold"}


def missing_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """高遗漏：长期未出数字得分高"""
    gaps = missing_gaps(records)
    base = normalize_scores({d: float(gaps[d]) for d in ALL_DIGITS})
    # 对3个位置使用相同的遗漏分，再叠加位置历史分布微调
    pos_freq = digit_position_frequency(records[:120])
    fused = []
    for c in pos_freq:
        pos_bias = normalize_scores({d: 1.0 / (1.0 + c[d]) for d in ALL_DIGITS})
        fused.append(normalize_scores({d: base[d] * 0.7 + pos_bias[d] * 0.3 for d in ALL_DIGITS}))
    return fused, {"type": "missing"}


def cycle_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """周期：间隔方差小者周期性强，若当前接近历史平均周期则加分"""
    intervals = defaultdict(list)
    last_seen = {}
    for i, r in enumerate(records):
        for d in r.digits:
            if d in last_seen:
                intervals[d].append(i - last_seen[d])
            last_seen[d] = i
    scores = {}
    for d in ALL_DIGITS:
        vals = intervals[d]
        if len(vals) >= 3:
            mean = sum(vals) / len(vals)
            var = sum((x - mean) ** 2 for x in vals) / len(vals)
            gap = last_seen.get(d, len(records))
            # 方差小、当前间隔接近平均 → 周期点临近，加分
            scores[d] = max(0.0, 1.0 - math.sqrt(var) / max(mean, 1.0)) * max(0.0, 1.0 - abs(gap - mean) / max(mean, 1.0))
        else:
            scores[d] = 0.0
    base = normalize_scores(scores)
    fused = [base.copy() for _ in range(3)]
    return fused, {"type": "cycle"}


def sum_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """和值：历史平均±1标准差为目标，生成3位组合按和值接近程度打分"""
    sums = [r.sum_value for r in records[:120]]
    if len(sums) < 2:
        target_lo, target_hi = 10, 17
    else:
        mean = sum(sums) / len(sums)
        std = math.sqrt(sum((x - mean) ** 2 for x in sums) / len(sums))
        target_lo, target_hi = mean - std, mean + std
    # 返回按位的均匀分数，实际在和值融合阶段用整体组合评分修正
    base = {d: 0.5 for d in ALL_DIGITS}
    return [base.copy() for _ in range(3)], {"type": "sum", "target_lo": target_lo, "target_hi": target_hi}


def balanced_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """平衡：奇偶、大小尽量均衡"""
    # 统计近期奇偶大小趋势，略偏向弱势方
    recent = records[:30]
    odd_ratio = sum(1 for r in recent for d in r.digits if d % 2 == 1) / max(1, len(recent) * 3)
    big_ratio = sum(1 for r in recent for d in r.digits if d >= 5) / max(1, len(recent) * 3)
    # 弱势方加分，追求再平衡
    scores = {}
    for d in ALL_DIGITS:
        s = 0.5
        if d % 2 == 1 and odd_ratio < 0.5:
            s += 0.25
        if d % 2 == 0 and odd_ratio > 0.5:
            s += 0.25
        if d >= 5 and big_ratio < 0.5:
            s += 0.25
        if d < 5 and big_ratio > 0.5:
            s += 0.25
        scores[d] = s
    base = normalize_scores(scores)
    return [base.copy() for _ in range(3)], {"type": "balanced", "odd_ratio": odd_ratio, "big_ratio": big_ratio}


def random_expert(_records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """随机扰动"""
    base = {d: random.random() for d in ALL_DIGITS}
    base = normalize_scores(base)
    return [base.copy() for _ in range(3)], {"type": "random"}


EXPERTS = {
    "hot": hot_expert,
    "cold": cold_expert,
    "missing": missing_expert,
    "cycle": cycle_expert,
    "sum": sum_expert,
    "balanced": balanced_expert,
    "random": random_expert,
}

DEFAULT_EXPERT_WEIGHTS = {
    "hot": 1.0,
    "cold": 0.9,
    "missing": 1.0,
    "cycle": 0.8,
    "sum": 0.9,
    "balanced": 0.8,
    "random": 0.3,
}


def aggregate_scores(
    records: List[FC3DRecord],
    weights: Optional[Dict[str, float]] = None,
) -> Tuple[List[Dict[int, float]], Dict[str, Dict[str, float]]]:
    weights = weights or DEFAULT_EXPERT_WEIGHTS
    pos_scores = [Counter({d: 0.0 for d in ALL_DIGITS}) for _ in range(3)]
    expert_infos = {}
    for name, fn in EXPERTS.items():
        w = weights.get(name, 0.0)
        if w <= 0:
            continue
        scores, info = fn(records)
        expert_infos[name] = info
        for pos in range(3):
            for d in ALL_DIGITS:
                pos_scores[pos][d] += scores[pos][d] * w
    # softmax-like 归一化到 [0,1]
    normalized = []
    for c in pos_scores:
        vals = [c[d] for d in ALL_DIGITS]
        max_v = max(vals)
        min_v = min(vals)
        if max_v - min_v < 1e-9:
            normalized.append({d: 0.5 for d in ALL_DIGITS})
        else:
            normalized.append({d: (c[d] - min_v) / (max_v - min_v) for d in ALL_DIGITS})
    return normalized, expert_infos


def generate_candidates(pos_scores: List[Dict[int, float]], top_k_per_pos: int = 5) -> List[Tuple[int, int, int]]:
    """按每位 top_k 做笛卡尔积生成候选"""
    top_per_pos = [
        [d for d, _ in sorted(scores.items(), key=lambda x: -x[1])[:top_k_per_pos]]
        for scores in pos_scores
    ]
    candidates = []
    for a in top_per_pos[0]:
        for b in top_per_pos[1]:
            for c in top_per_pos[2]:
                candidates.append((a, b, c))
    return candidates


def evaluate_candidate(
    cand: Tuple[int, int, int],
    pos_scores: List[Dict[int, float]],
    records: List[FC3DRecord],
    sum_target: Optional[Tuple[float, float]] = None,
) -> Tuple[float, Dict[str, float]]:
    digits = list(cand)
    score = 0.0
    explain = {}
    for i, d in enumerate(digits):
        score += pos_scores[i][d]
    explain["position"] = score

    # 和值奖励
    s = sum(digits)
    if sum_target:
        lo, hi = sum_target
        if lo <= s <= hi:
            bonus = 1.0
        else:
            bonus = max(0.0, 1.0 - min(abs(s - lo), abs(s - hi)) / max(1.0, (hi - lo)))
        explain["sum"] = bonus
        score += bonus

    # 跨度奖励：常见跨度 3-7 略加分
    span = max(digits) - min(digits)
    span_bonus = 0.0
    if 3 <= span <= 7:
        span_bonus = 0.5
    explain["span"] = span_bonus
    score += span_bonus

    # 避免全奇/全偶/全大/全小过度集中
    balance_penalty = 0.0
    odd_count = sum(1 for d in digits if d % 2 == 1)
    big_count = sum(1 for d in digits if d >= 5)
    if odd_count in (0, 3) or big_count in (0, 3):
        balance_penalty = -0.3
    explain["balance"] = balance_penalty
    score += balance_penalty

    # 避免与最新一期完全重复或过于相似
    if records:
        last = records[0].digits
        same = sum(1 for a, b in zip(digits, last) if a == b)
        dup_penalty = -0.2 * same
        explain["repeat"] = dup_penalty
        score += dup_penalty

    return score, explain


def predict(
    records: List[FC3DRecord],
    num: int = 5,
    weights: Optional[Dict[str, float]] = None,
    seed: Optional[int] = None,
) -> List[PredictionResult]:
    if seed is not None:
        random.seed(seed)
    if len(records) < 30:
        print(f"[警告] 历史数据仅 {len(records)} 条，建议至少 50 条以上再参考预测结果", file=sys.stderr)

    pos_scores, expert_infos = aggregate_scores(records, weights)

    # 确定和值目标范围
    sums = [r.sum_value for r in records[:120]]
    if len(sums) >= 2:
        mean = sum(sums) / len(sums)
        std = math.sqrt(sum((x - mean) ** 2 for x in sums) / len(sums))
        sum_target = (mean - std, mean + std)
    else:
        sum_target = (10.0, 17.0)

    candidates = generate_candidates(pos_scores, top_k_per_pos=5)
    scored = []
    for cand in candidates:
        score, explain = evaluate_candidate(cand, pos_scores, records, sum_target)
        scored.append((cand, score, explain))

    scored.sort(key=lambda x: -x[1])
    seen = set()
    results = []
    for cand, score, explain in scored:
        key = tuple(cand)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            PredictionResult(
                number="".join(str(d) for d in cand),
                digits=list(cand),
                score=score,
                sum_value=sum(cand),
                span=max(cand) - min(cand),
                explain=explain,
            )
        )
        if len(results) >= num:
            break
    return results, expert_infos, sum_target


def format_output(
    results: List[PredictionResult],
    expert_infos: Dict[str, Dict[str, float]],
    sum_target: Tuple[float, float],
    records: List[FC3DRecord],
) -> str:
    lines = []
    lines.append("=" * 50)
    lines.append("福彩3D 娱乐预测结果（仅供娱乐，不构成投注建议）")
    lines.append("=" * 50)
    if records:
        lines.append(f"历史数据：共 {len(records)} 期，最新一期 {records[0].period} ({records[0].date}) 开奖 {records[0].as_number()}")
    lines.append(f"和值目标区间：{sum_target[0]:.1f} ~ {sum_target[1]:.1f}")
    lines.append(f"参与专家：{', '.join(expert_infos.keys())}")
    lines.append("-" * 50)
    for i, r in enumerate(results, 1):
        explain_str = " | ".join(f"{k}={v:+.2f}" for k, v in r.explain.items())
        lines.append(
            f"第{i}注：{r.number}  和值={r.sum_value}  跨度={r.span}  综合分={r.score:.2f}  ({explain_str})"
        )
    lines.append("-" * 50)
    lines.append("提示：彩票开奖为独立随机事件，所有预测方法均无科学依据保证中奖。")
    return "\n".join(lines)


def archive_prediction(results: List[PredictionResult], records: List[FC3DRecord], archive_dir: str = ARCHIVE_DIR) -> str:
    os.makedirs(archive_dir, exist_ok=True)
    next_period = ""
    if records and records[0].period:
        try:
            next_period = str(int(records[0].period) + 1)
        except ValueError:
            next_period = records[0].period
    else:
        next_period = datetime.now().strftime("%Y%m%d")
    filename = os.path.join(archive_dir, f"{next_period}.txt")
    lines = [
        f"period={next_period}",
        f"generated_at={datetime.now().isoformat()}",
        f"mode=team",
        f"history_count={len(records)}",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"ticket{i}={r.number}|sum={r.sum_value}|span={r.span}|score={r.score:.3f}")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return filename


def backtest(records: List[FC3DRecord], cycles: int = 30, num: int = 5, seed: Optional[int] = None) -> Dict:
    """Walk-forward 回测：用前 N 期预测下一期，统计命中数字数"""
    if seed is not None:
        random.seed(seed)
    cycles = min(cycles, len(records) - 1)
    metrics = []
    for i in range(cycles):
        history = records[i + 1 : i + 121]  # 预测第 i 期时，使用之后最多120期作为历史
        actual = records[i]
        if len(history) < 20:
            continue
        results, _, _ = predict(history, num=num)
        pred_set = set()
        for r in results:
            pred_set.update(r.digits)
        actual_set = set(actual.digits)
        hit_any = len(pred_set & actual_set)
        exact_match = any(r.digits == actual.digits for r in results)
        # 组选：号码相同不论顺序
        group_match = any(sorted(r.digits) == sorted(actual.digits) for r in results)
        metrics.append(
            {
                "period": actual.period,
                "actual": actual.as_number(),
                "predictions": [r.number for r in results],
                "digit_hits": hit_any,
                "exact_match": exact_match,
                "group_match": group_match,
            }
        )
    if not metrics:
        return {"cycles": 0}
    total = len(metrics)
    return {
        "cycles": total,
        "avg_digit_hits": sum(m["digit_hits"] for m in metrics) / total,
        "exact_match_rate": sum(1 for m in metrics if m["exact_match"]) / total,
        "group_match_rate": sum(1 for m in metrics if m["group_match"]) / total,
        "details": metrics,
    }


def parse_weight_patch(path: str) -> Dict[str, float]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("expert_weights", {})


def main():
    parser = argparse.ArgumentParser(description="福彩3D 娱乐预测器")
    parser.add_argument("--data", "-d", default=DATA_FILE, help="历史数据文件路径")
    parser.add_argument("--num", "-n", type=int, default=5, help="输出注数")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument("--backtest", "-b", action="store_true", help="运行回测")
    parser.add_argument("--backtest-cycles", type=int, default=30, help="回测期数")
    parser.add_argument("--weight-patch", help="专家权重补丁 JSON 路径")
    parser.add_argument("--archive", action="store_true", help="预测结果写入归档")
    parser.add_argument("--import-json", help="从 JSON 文件导入历史数据并覆盖 fc3d_data.json")
    args = parser.parse_args()

    if args.import_json:
        with open(args.import_json, "r", encoding="utf-8") as f:
            raw = json.load(f)
        records = [
            FC3DRecord(
                period=str(r.get("period", "")),
                date=str(r.get("date", "")),
                digits=[int(d) for d in r["digits"]],
            )
            for r in raw.get("records", [])
            if "digits" in r and len(r["digits"]) == 3
        ]
        save_data(args.data, records)
        print(f"已导入 {len(records)} 条记录到 {args.data}")
        return

    records = load_data(args.data)

    weights = DEFAULT_EXPERT_WEIGHTS.copy()
    if args.weight_patch:
        patch = parse_weight_patch(args.weight_patch)
        weights.update(patch)

    if args.backtest:
        result = backtest(records, cycles=args.backtest_cycles, num=args.num, seed=args.seed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    results, expert_infos, sum_target = predict(records, num=args.num, weights=weights, seed=args.seed)
    print(format_output(results, expert_infos, sum_target, records))

    if args.archive:
        path = archive_prediction(results, records)
        print(f"\n已归档：{path}")


if __name__ == "__main__":
    main()
