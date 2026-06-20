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


def adjacent_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]:
    """邻号：最近5期各位置数字的±1邻号获得加权加分，捕获数字漂移"""
    if not records:
        return [{d: 0.5 for d in ALL_DIGITS} for _ in range(3)], {"type": "adjacent"}
    pos_scores = []
    # 多期邻号叠加，越近权重越高
    recency_weights = [5.0, 4.0, 3.0, 2.0, 1.0]
    window = min(len(records), len(recency_weights))
    for pos in range(3):
        raw = {d: 0.0 for d in ALL_DIGITS}
        for w_idx in range(window):
            d = records[w_idx].digits[pos]
            for n in [(d - 1) % 10, (d + 1) % 10]:
                raw[n] += recency_weights[w_idx]
        pos_scores.append(normalize_scores(raw))
    recent_digits = [records[0].digits[pos] for pos in range(3)]
    return pos_scores, {"type": "adjacent", "recent": recent_digits}


EXPERTS = {
    "hot": hot_expert,
    "cold": cold_expert,
    "missing": missing_expert,
    "cycle": cycle_expert,
    "sum": sum_expert,
    "balanced": balanced_expert,
    "random": random_expert,
    "adjacent": adjacent_expert,
}

DEFAULT_EXPERT_WEIGHTS = {
    "hot": 1.0,
    "cold": 0.9,
    "missing": 1.0,
    "cycle": 0.8,
    "sum": 0.9,
    "balanced": 0.8,
    "random": 1.0,
    "adjacent": 1.0,
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


def generate_markov_candidates(records: List[FC3DRecord], top_n: int = 300) -> List[Tuple[int, int, int]]:
    """用马尔可夫链式法则生成最可能的完整3位数候选。

    - 指数衰减时间权重：越近期记录权重越高
    - Backoff 插值平滑：P(d3|d1,d2) = 0.6×P_obs + 0.3×P(d3|d2) + 0.1×P(d3)
    """
    if len(records) < 20:
        return []

    decay = 0.015  # 衰减系数，约46期后半衰
    p_d1: Dict[int, float] = defaultdict(float)
    p_d2_given_d1: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    p_d3_given_d1d2: Dict[Tuple[int, int], Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    p_d3: Dict[int, float] = defaultdict(float)        # P(d3) 边际
    p_d3_given_d2: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))  # P(d3|d2)

    total_weight = 0.0
    for i, r in enumerate(records):
        w = math.exp(-decay * i)
        total_weight += w
        d1, d2, d3 = r.digits
        p_d1[d1] += w
        p_d2_given_d1[d1][d2] += w
        p_d3_given_d1d2[(d1, d2)][d3] += w
        p_d3[d3] += w
        p_d3_given_d2[d2][d3] += w

    # Backoff 插值权重
    L3, L2, L1 = 0.6, 0.3, 0.1  # P(d3|d1,d2) : P(d3|d2) : P(d3)

    scored: List[Tuple[Tuple[int, int, int], float]] = []
    for d1 in range(10):
        p1 = p_d1.get(d1, 0.001) / max(total_weight, 1.0)
        d1_weight = sum(p_d2_given_d1[d1].values())
        for d2 in range(10):
            p2 = p_d2_given_d1[d1].get(d2, 0.001) / max(d1_weight, 1.0) if d1_weight > 0 else 0.1
            d12_weight = sum(p_d3_given_d1d2[(d1, d2)].values())
            d2_weight = sum(p_d3_given_d2[d2].values())
            for d3 in range(10):
                # Backoff 插值
                if d12_weight > 0:
                    p3_obs = p_d3_given_d1d2[(d1, d2)].get(d3, 0.0) / d12_weight
                else:
                    p3_obs = 0.0
                if d2_weight > 0:
                    p3_d2 = p_d3_given_d2[d2].get(d3, 0.0) / d2_weight
                else:
                    p3_d2 = 0.0
                p3_marginal = p_d3.get(d3, 0.001) / max(total_weight, 1.0)
                p3 = L3 * p3_obs + L2 * p3_d2 + L1 * p3_marginal
                scored.append(((d1, d2, d3), p1 * p2 * max(p3, 0.0001)))

    scored.sort(key=lambda x: -x[1])
    return [c for c, _ in scored[:top_n]]


def generate_gap_candidates(records: List[FC3DRecord], top_n: int = 30) -> List[Tuple[int, int, int]]:
    """遗漏回补：统计历史上出现过的每个完整3位数的遗漏间隔，
    找到 current_gap/max_gap > 0.6 的号码，这些号码更可能近期回补。
    """
    if len(records) < 30:
        return []

    # 记录每个号码的出现位置（从最新算，0=最新一期）
    last_seen: Dict[Tuple[int, int, int], int] = {}
    intervals: Dict[Tuple[int, int, int], List[int]] = defaultdict(list)
    prev_seen: Dict[Tuple[int, int, int], int] = {}

    for i, r in enumerate(records):
        num = tuple(r.digits)
        if num not in last_seen:
            last_seen[num] = i
        if num in prev_seen:
            intervals[num].append(i - prev_seen[num])
        prev_seen[num] = i

    candidates = []
    for num, gap in last_seen.items():
        if gap < 10:  # 最近10期内出现过的排除
            continue
        ivs = intervals.get(num, [])
        if len(ivs) < 2:
            continue
        max_gap = max(ivs)
        avg_gap = sum(ivs) / len(ivs)
        if max_gap < 5:
            continue
        gap_ratio = gap / max_gap if max_gap > 0 else 0.0
        if gap_ratio > 0.55 and gap > avg_gap * 0.8:
            # gap_ratio越高越可能回补
            candidates.append((num, gap_ratio))

    candidates.sort(key=lambda x: -x[1])
    return [c for c, _ in candidates[:top_n]]


def generate_transition_candidates(records: List[FC3DRecord], top_n: int = 15) -> List[Tuple[int, int, int]]:
    """跨期转移：给定最近一期号码，找历史上同样号码出现后下一期最常跟随的号码。

    先精确匹配（上期号码完全相同），数据不足时降级为组选匹配（数字集相同）。
    """
    if len(records) < 5:
        return []

    last_draw = tuple(records[0].digits)
    exact_followers: Counter = Counter()
    group_followers: Counter = Counter()
    last_set = set(last_draw)

    for i in range(len(records) - 1):
        prev_num = tuple(records[i + 1].digits)
        next_num = tuple(records[i].digits)
        if prev_num == last_draw:
            exact_followers[next_num] += 1
        if set(prev_num) == last_set:
            group_followers[next_num] += 1

    # 优先精确匹配，不够再补组选
    result = [c for c, _ in exact_followers.most_common(top_n)]
    if len(result) < top_n:
        existing = set(result)
        for c, _ in group_followers.most_common(top_n * 2):
            if c not in existing and c != last_draw:
                result.append(c)
            if len(result) >= top_n:
                break
    return result


def mmr_select(
    candidates: List[Tuple[int, int, int]],
    scores: List[float],
    num: int = 5,
    lambda_param: float = 0.65,
) -> List[int]:
    """用 MMR (Maximal Marginal Relevance) 从候选池中选出既高分又多样的候选。

    lambda_param: 相关性权重（0~1），越大越偏向高分，越小越偏向多样性。
    """
    selected_indices: List[int] = []
    selected_sets: List[set] = []
    remaining = list(range(len(candidates)))

    for _ in range(min(num, len(candidates))):
        best_idx = -1
        best_mmr = float("-inf")
        for idx in remaining:
            cand_set = set(candidates[idx])
            max_sim = 0.0
            for ss in selected_sets:
                inter = len(cand_set & ss)
                union = len(cand_set | ss)
                sim = inter / union if union > 0 else 1.0
                if sim > max_sim:
                    max_sim = sim
            mmr = lambda_param * scores[idx] - (1.0 - lambda_param) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx
        if best_idx >= 0:
            selected_indices.append(best_idx)
            selected_sets.append(set(candidates[best_idx]))
            remaining.remove(best_idx)

    return selected_indices


def evaluate_candidate(
    cand: Tuple[int, int, int],
    pos_scores: List[Dict[int, float]],
    records: List[FC3DRecord],
    sum_target: Optional[Tuple[float, float]] = None,
) -> Tuple[float, Dict[str, float]]:
    digits = list(cand)
    score = 0.0
    explain: Dict[str, float] = {}
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

    # 跨度趋势：基于近期跨度序列做均值回归或突破判断
    span = max(digits) - min(digits)
    span_bonus = 0.0
    if records and len(records) >= 10:
        recent_spans = [r.span for r in records[:10]]
        avg_span = sum(recent_spans) / len(recent_spans)
        span_dist = abs(span - avg_span)
        if 1.5 <= span_dist <= 3.5:
            span_bonus = 0.4  # 适度偏离近期均值，有均值回归空间
        elif span_dist > 3.5:
            span_bonus = 0.6  # 大幅偏离，可能趋势突破
        else:
            span_bonus = 0.15  # 过于接近均值，信号弱
    else:
        span_bonus = 0.5 if 3 <= span <= 7 else 0.0
    explain["span"] = span_bonus
    score += span_bonus

    # 形态感知：组六/组三/豹子周期判断
    unique = len(set(digits))  # 3=组六, 2=组三, 1=豹子
    pattern_bonus = 0.0
    if records and len(records) >= 20:
        recent_unique = [len(set(r.digits)) for r in records[:20]]
        zuliu_count = recent_unique.count(3)
        zusan_count = recent_unique.count(2)
        zuliu_ratio = zuliu_count / 20
        zusan_ratio = zusan_count / 20
        if unique == 3 and zuliu_ratio < 0.65:  # 组六不足，加分
            pattern_bonus = (0.72 - zuliu_ratio) * 2.5
        elif unique == 2 and zusan_ratio < 0.22:  # 组三不足，加分
            pattern_bonus = (0.27 - zusan_ratio) * 2.5
        elif unique == 1:  # 豹子极少出现，不鼓励
            pattern_bonus = -0.5
    explain["pattern"] = pattern_bonus
    score += pattern_bonus

    # 避免全奇/全偶/全大/全小过度集中
    balance_penalty = 0.0
    odd_count = sum(1 for d in digits if d % 2 == 1)
    big_count = sum(1 for d in digits if d >= 5)
    if odd_count in (0, 3):
        balance_penalty -= 0.2
    if big_count in (0, 3):
        balance_penalty -= 0.2
    explain["balance"] = balance_penalty
    score += balance_penalty

    # 避免与最新一期完全重复或过于相似
    if records:
        last = records[0].digits
        same = sum(1 for a, b in zip(digits, last) if a == b)
        dup_penalty = -0.25 * same
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

    weights = weights or DEFAULT_EXPERT_WEIGHTS.copy()

    # 确定和值目标范围
    sums = [r.sum_value for r in records[:120]]
    if len(sums) >= 2:
        mean = sum(sums) / len(sums)
        std = math.sqrt(sum((x - mean) ** 2 for x in sums) / len(sums))
        sum_target = (mean - std, mean + std)
    else:
        sum_target = (10.0, 17.0)

    # === 每位专家独立产出候选，保留各自独特视角 ===
    all_scored: List[Tuple[Tuple[int, int, int], float, Dict[str, float]]] = []
    seen_candidates: set = set()

    for name, fn in EXPERTS.items():
        w = weights.get(name, 0.0)
        if w <= 0:
            continue
        expert_scores, info = fn(records)
        expert_cands = generate_candidates(expert_scores, top_k_per_pos=3)
        for cand in expert_cands:
            key = tuple(cand)
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            score, explain = evaluate_candidate(cand, expert_scores, records, sum_target)
            all_scored.append((cand, score * w, explain))

    # 也加入融合视角的候选（聚合所有专家打分）
    pos_scores, expert_infos = aggregate_scores(records, weights)
    agg_cands = generate_candidates(pos_scores, top_k_per_pos=6)
    for cand in agg_cands:
        key = tuple(cand)
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        score, explain = evaluate_candidate(cand, pos_scores, records, sum_target)
        all_scored.append((cand, score, explain))

    # === 马尔可夫链式法则候选：三位联合概率 P(d1,d2,d3) ===
    markov_cands = generate_markov_candidates(records, top_n=300)
    markov_scored: List[Tuple[Tuple[int, int, int], float, Dict[str, float]]] = []
    for cand in markov_cands:
        key = tuple(cand)
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        score, explain = evaluate_candidate(cand, pos_scores, records, sum_target)
        markov_scored.append((cand, score, explain))
        all_scored.append((cand, score, explain))

    # === 历史热号：最近N期中出现过的完整3位数 ===
    # 最近200期中实际开出过的号码，按出现次数加权
    recent_hot: Counter = Counter()
    for r in records[:200]:
        recent_hot[tuple(r.digits)] += 1
    hot_candidates = recent_hot.most_common(80)
    for cand_tuple, freq in hot_candidates:
        if freq < 2:
            continue  # 只保留至少出现2次的热号
        key = cand_tuple
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        score, explain = evaluate_candidate(cand_tuple, pos_scores, records, sum_target)
        all_scored.append((cand_tuple, score, explain))

    # === 历史相似期匹配：找与最近5期最相似的历史片段 ===
    if len(records) >= 15:
        recent_5 = records[:5]
        # 特征：每期数字集合 + 和值
        def seq_similarity(hist_start: int) -> float:
            sim = 0.0
            for offset in range(5):
                if hist_start + offset >= len(records):
                    break
                r_hist = records[hist_start + offset]
                r_recent = recent_5[min(offset, len(recent_5) - 1)]
                # 数字重叠 Jaccard
                set_h = set(r_hist.digits)
                set_r = set(r_recent.digits)
                inter = len(set_h & set_r)
                union = len(set_h | set_r)
                jaccard = inter / union if union > 0 else 0
                # 和值接近度
                sum_dist = abs(r_hist.sum_value - r_recent.sum_value) / 27.0
                sim += jaccard * 0.6 + (1.0 - sum_dist) * 0.4
            return sim

        sim_scores = []
        for start in range(1, len(records) - 6):
            sim = seq_similarity(start)
            sim_scores.append((start, sim))
        sim_scores.sort(key=lambda x: -x[1])

        # 取top-3相似片段的下一个开奖号
        for start, sim in sim_scores[:3]:
            if sim < 1.5:  # 相似度过滤
                continue
            next_draw = records[start - 1] if start > 0 else None
            if next_draw is None:
                continue
            cand_tuple = tuple(next_draw.digits)
            if cand_tuple in seen_candidates:
                continue
            seen_candidates.add(cand_tuple)
            score, explain = evaluate_candidate(cand_tuple, pos_scores, records, sum_target)
            all_scored.append((cand_tuple, score, explain))

    # === 遗漏回补候选：冷号回补信号 ===
    gap_cands = generate_gap_candidates(records, top_n=50)
    gap_scored: List[Tuple[Tuple[int, int, int], float, Dict[str, float]]] = []
    for cand in gap_cands:
        key = cand
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        score, explain = evaluate_candidate(cand, pos_scores, records, sum_target)
        gap_scored.append((cand, score, explain))
        all_scored.append((cand, score, explain))

    # === 跨期转移候选：上期号码的跟随规律 ===
    trans_cands = generate_transition_candidates(records, top_n=15)
    trans_scored: List[Tuple[Tuple[int, int, int], float, Dict[str, float]]] = []
    for cand in trans_cands:
        key = cand
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        score, explain = evaluate_candidate(cand, pos_scores, records, sum_target)
        trans_scored.append((cand, score, explain))
        all_scored.append((cand, score, explain))

    # === 强制保留：每种信号源至少1个，确保多维度覆盖 ===
    # 2个马尔可夫 + 1个遗漏回补 + 1个跨期转移 + 1个MMR自由选择
    forced_indices: List[int] = []
    forced_sets: List[set] = []

    def _force_add(source_list, count=1):
        nonlocal forced_indices, forced_sets
        for item in source_list[:count]:
            for i, (cand, _, _) in enumerate(all_scored):
                if cand == item[0] and i not in forced_indices:
                    forced_indices.append(i)
                    forced_sets.append(set(cand))
                    break

    _force_add(markov_scored, 2)
    _force_add(gap_scored, 1)
    _force_add(trans_scored, 1)
    markov_scored.sort(key=lambda x: -x[1])
    forced_indices: List[int] = []
    forced_sets: List[set] = []
    for mc in markov_scored[:2]:
        for i, (cand, _, _) in enumerate(all_scored):
            if cand == mc[0]:
                forced_indices.append(i)
                forced_sets.append(set(cand))
                break

    cand_list = [s[0] for s in all_scored]
    score_list = [s[1] for s in all_scored]

    # MMR 选择剩余的槽位（5 - 已强制保留数）
    remaining_slots = num - len(forced_indices)
    results = []
    selected_indices: List[int] = list(forced_indices)

    remaining_pool = [i for i in range(len(cand_list)) if i not in forced_indices]
    remaining_cands = [cand_list[i] for i in remaining_pool]
    remaining_scores = [score_list[i] for i in remaining_pool]

    for lamb in [0.45, 0.35, 0.25, 0.15, 0.05]:
        extra_indices = mmr_select(remaining_cands, remaining_scores, num=remaining_slots, lambda_param=lamb)
        selected_indices = forced_indices + [remaining_pool[i] for i in extra_indices]
        results = []
        for idx in selected_indices:
            cand, score, explain = all_scored[idx]
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
        digits_covered = set(d for r in results for d in r.digits)
        if len(digits_covered) >= 9:
            break

    # 强制补齐：如果仍未覆盖全部10个数字，从聚合视角补充缺失数字的候选
    all_digits_set = set(range(10))
    missing = all_digits_set - set(d for r in results for d in r.digits)
    if missing:
        # 为遗漏数字现场生成候选：放入最高分位置，其余位置选高分数字
        extra_cands = []
        for miss_d in missing:
            best_pos = max(range(3), key=lambda p: pos_scores[p].get(miss_d, 0))
            other_digits = []
            for p in range(3):
                if p != best_pos:
                    top_d = max((d for d in ALL_DIGITS if d != miss_d),
                                key=lambda d: pos_scores[p].get(d, 0))
                    other_digits.append(top_d)
            cand = [0, 0, 0]
            cand[best_pos] = miss_d
            other_idx = 0
            for p in range(3):
                if p != best_pos:
                    cand[p] = other_digits[other_idx]
                    other_idx += 1
            extra_cands.append(tuple(cand))
        # 将额外候选加入池中
        for cand in extra_cands:
            if tuple(cand) not in seen_candidates:
                seen_candidates.add(tuple(cand))
                score, explain = evaluate_candidate(cand, pos_scores, records, sum_target)
                all_scored.append((cand, score, explain))
                cand_list.append(cand)
                score_list.append(score)

        # 重新用极低λ做MMR，优先覆盖所有数字
        selected_indices = mmr_select(cand_list, score_list, num=num, lambda_param=0.05)
        results = []
        for idx in selected_indices:
            cand, score, explain = all_scored[idx]
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
        history = records[i + 1 : i + 201]  # 最多200期历史，平衡统计功效与时效性
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
