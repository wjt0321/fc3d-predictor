# 福彩3D预测器概率闭环与双模式优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复当前候选来源与最终排序脱节、回测权重补丁不生效、覆盖目标与直选目标混合的问题，并增加可验证的 `exact` / `coverage` 双模式。

**Architecture:** 保持单文件主程序结构，新增带平滑的完整三位联合概率计算，并把联合概率作为候选评分的一部分。`exact` 模式在统一候选池上按概率优先直接选 top-N；`coverage` 模式保留 MMR 与数字覆盖策略。回测显式传递权重和模式，新增指标用于区分位置命中和数字覆盖。

**Tech Stack:** Python 3 标准库、unittest、现有 JSON 数据格式。

## Global Constraints

- 所有输出和新增注释使用中文。
- 预测器仍仅供娱乐，不构成投注建议，不承诺中奖。
- 只使用 walk-forward 历史信息，不引入未来数据泄漏。
- 保持现有 CLI 兼容；默认模式改为 `exact`，覆盖策略通过 `--mode coverage` 显式启用。
- 默认关闭随机专家；随机种子只用于可复现实验，不作为预测信号。

---

### Task 1: 建立回归测试基线

**Files:**
- Create: `tests/test_fc3d_predictor.py`
- Modify: `fc3d_predictor.py`（仅为测试导入保持现有 API，不先改生产逻辑）

**Interfaces:**
- Tests consume `generate_joint_scores`, `predict`, `backtest`, `DEFAULT_EXPERT_WEIGHTS`。
- Later tasks must make these assertions pass。

- [x] **Step 1: Write failing tests**
  - 验证联合概率对 1000 个三位号码都有有限正值。
  - 验证 `random` 默认权重为 0。
  - 验证 `predict(..., mode="exact")` 与 `predict(..., mode="coverage")` 都返回指定数量且号码不重复。
  - 验证 `backtest(..., weights=patch)` 接受并使用权重参数。
  - 验证回测详情包含 `position_hits` 和 `coverage_size`。

- [x] **Step 2: Run tests and confirm expected failures**

```powershell
python -m unittest discover -s tests -v
```

Expected: FAIL，原因包括新接口尚未存在。

---

### Task 2: 实现联合概率评分闭环

**Files:**
- Modify: `fc3d_predictor.py:322-375, 489-568`
- Test: `tests/test_fc3d_predictor.py`

**Interfaces:**
- Add `generate_joint_scores(records, decay=0.003, alpha=0.5) -> Dict[Tuple[int, int, int], float]`。
- Preserve `generate_markov_candidates(records, top_n=300)` as compatibility wrapper。
- Extend `evaluate_candidate(..., joint_score: Optional[float] = None, joint_weight: float = 0.0)`。

- [x] **Step 1: Implement smoothed joint model**
  - 计算 `P(d1) * P(d2|d1) * P(d3|d1,d2)`。
  - 使用指数时间权重和 additive smoothing。
  - 对所有 1000 个候选返回正的概率。

- [x] **Step 2: Pass joint score into final candidate evaluation**
  - 在 `predict` 中构建候选到联合概率的映射。
  - 以对数概率的 min-max 归一化值加入评分，避免极小概率数值问题。
  - 保持结构分为轻量修正，不让和值、跨度、遗漏规则覆盖联合概率。

- [x] **Step 3: Run focused tests**

```powershell
python -m unittest tests.test_fc3d_predictor.TestJointProbability -v
```

Expected: PASS。

---

### Task 3: 增加 exact / coverage 双模式并修正权重回测

**Files:**
- Modify: `fc3d_predictor.py:571-822, 880-919, 928-1000`
- Test: `tests/test_fc3d_predictor.py`

**Interfaces:**
- Change `predict(..., mode: str = "exact") -> Tuple[List[PredictionResult], Dict, Tuple]` only if current caller contract already expects tuple；otherwise preserve current return contract exactly。
- Change `backtest(..., weights: Optional[Dict[str, float]] = None, mode: str = "exact")`。

- [x] **Step 1: Refactor candidate selection**
  - `exact`：统一候选池评分排序，取消强制马尔可夫/遗漏/转移配额和 9~10 数字覆盖。
  - `coverage`：保留现有 MMR 流程，但使用修正后的联合评分和显式模式。
  - 两种模式都去重并保证最多/恰好返回 `num` 个候选（候选不足时按现有池安全降级）。

- [x] **Step 2: Pass weights through backtest**
  - `backtest` 接收并传递 `weights`、`mode`。
  - CLI 回测使用命令行解析后的权重补丁。

- [x] **Step 3: Add honest metrics**
  - 增加每位位置命中数、位置命中率、预测数字覆盖数。
  - 保留原字段，避免破坏现有使用者。

- [x] **Step 4: Run focused integration tests**

```powershell
python -m unittest tests.test_fc3d_predictor.TestModes tests.test_fc3d_predictor.TestBacktest -v
```

Expected: PASS。

---

### Task 4: 更新 CLI、文档和默认配置

**Files:**
- Modify: `fc3d_predictor.py:928-1000`
- Modify: `README.md`
- Modify: `config/fc3d_weight_patch.json`
- Test: `tests/test_fc3d_predictor.py`

- [x] **Step 1: Add `--mode {exact,coverage}`**
  - 默认 `exact`。
  - 输出中标明模式和“仅供娱乐”提示。

- [x] **Step 2: Set random expert default weight to 0**
  - 保留手动实验能力，补丁仍可显式设为正值。

- [x] **Step 3: Document metric interpretation**
  - 明确 `coverage` 的数字命中不等价于直选命中率。
  - 增加回测示例。

- [x] **Step 4: Run full verification**

```powershell
python -m unittest discover -s tests -v
python fc3d_predictor.py --num 5 --seed 42 --mode exact
python fc3d_predictor.py --num 5 --seed 42 --mode coverage
python fc3d_predictor.py --backtest --backtest-cycles 100 --num 5 --seed 42 --mode exact
python fc3d_predictor.py --backtest --backtest-cycles 100 --num 5 --seed 42 --mode coverage --weight-patch config/fc3d_weight_patch.json
```

- [x] **Step 5: Compare against baseline and record results**
  - 至少跑 1000 期 exact 与 coverage。
  - 同时报告随机基线、覆盖规模、直选命中率和组选命中率。

- [x] **Step 6: Commit changes**

```powershell
git add fc3d_predictor.py README.md config/fc3d_weight_patch.json tests docs/superpowers/plans
 git commit -m "feat: add calibrated exact and coverage prediction modes"
```
