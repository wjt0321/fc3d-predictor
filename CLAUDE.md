# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 参考项目

本项目的预测逻辑、多专家团队、回测归档、权重补丁等设计参考 `D:/3D/lottery-predictor-main`（双色球预测器）。

## 常用命令

```bash
# 更新开奖数据（从东方财富网抓取）
python update_fc3d_data.py                # 默认最近~500期
python update_fc3d_data.py --all           # 全部历史（~7700期）

# 日常预测
python fc3d_predictor.py --num 5                                    # 预测5注
python fc3d_predictor.py --num 5 --seed 42                          # 固定种子复现
python fc3d_predictor.py --num 5 --archive                          # 预测并归档
python fc3d_predictor.py --num 5 --weight-patch config/fc3d_weight_patch.json

# 回测
python fc3d_predictor.py --backtest --backtest-cycles 100 --num 5 --seed 42

# 数据导入
python fc3d_predictor.py --import-json fc3d_history.json
```

项目无自动化测试套件。验证方式为手动运行上述命令。

## 架构

### 数据流

```
东方财富网 (caipiao.eastmoney.com)
  │  update_fc3d_data.py: requests → BeautifulSoup 解析 HTML
  ▼
fc3d_data.json  (7663期, 2004~2026, records按日期倒序)
  │
  ▼
fc3d_predictor.py
  ├─ 8位专家按位打分 (hot/cold/missing/cycle/sum/balanced/random/adjacent)
  ├─ 马尔可夫链式法则 P(d1)×P(d2|d1)×P(d3|d1,d2) 生成完整3位数候选
  ├─ 遗漏回补 + 跨期转移 + 历史热号 + 相似期匹配
  ├─ MMR 多样性选择 (λ自适应，强制保留多信号源)
  ├─ backtest(): walk-forward 回测
  └─ archive: → fc3d_archive/{下期期号}.txt
```

### 候选生成流水线 (7个信号源)

| 序号 | 信号源 | 数量 | 说明 |
|------|--------|------|------|
| 1 | 独立专家笛卡尔积 | 8×27≈216 | 每位专家 top-3 按位组合 |
| 2 | 聚合专家笛卡尔积 | 216 | aggregate_scores 融合后 top-6 |
| 3 | **马尔可夫联合概率** | 300 | P(d1,d2,d3) 链式法则 + backoff 插值 |
| 4 | 历史热号 | 100 | 最近500期高频完整3位数 |
| 5 | 历史相似期匹配 | 3 | 最近5期最相似片段的下期号码 |
| 6 | 遗漏回补 | 80 | gap_ratio > 0.55 的冷号 |
| 7 | 跨期转移 | 25 | 上期号码的历史跟随者 |

合并去重后 MMR 选择 5 注，强制保留：2马尔可夫 + 1遗漏 + 1转移，λ 自适应 0.45→0.05，确保≥9数字覆盖。

### 专家接口

```python
def xxx_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]
```
返回 `[pos0_scores, pos1_scores, pos2_scores]` + 元信息字典。

## 性能指标

| 指标 | v1 原始 | v4 当前 | 随机基线 | 理论极限 |
|------|---------|---------|---------|---------|
| avg_digit_hits | 1.06 | **2.62** | 2.38 | 2.71 |
| exact_match_rate | 0% | **0.8%** | 0.5% | ~1.5% |
| 零命中期(/200) | ~60 | **0** | ~16 | 0 |

### 已验证无效的假设 (7663期数据, p>0.5)

- 热号/冷号向特定位置回归 → 10%，等于随机
- 预测数字±1-2位偏移命中 → 均匀分布
- 对数映射 (0↔5, 1↔9…) → 27.1%，等于随机
- 10期内延迟命中 → 4.9%，等于随机概率叠加
- 复式6号池预选 → 22%，等于随机
- 更多训练数据 (350→7663) → 命中率不变

## 关键约定

- `fc3d_data.json` 中 `records` 按日期倒序，`digits` 为 `[0-9]` 长度3的整数列表
- 归档：`fc3d_archive/{next_period}.txt`，`next_period` = 最新期号 + 1
- 权重补丁缺失不阻断，自动回退 `DEFAULT_EXPERT_WEIGHTS`
- 仅供娱乐，所有输出必须声明不构成投注建议
- 编码 UTF-8，命名 snake_case，注释中文
