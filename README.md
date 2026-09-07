# 福彩3D娱乐预测器

> ⚠️ 本工具仅供娱乐，不构成任何投注建议。

本项目参考 `D:/3D/lottery-predictor-main`（双色球预测器）的多专家团队 + 历史回测 + 权重补丁设计，针对福彩3D（3位数字 0-9）实现了一个轻量级娱乐预测器。

## 快速开始

```bash
cd D:/3D/fc3d-predictor-skill
python update_fc3d_data.py
python fc3d_predictor.py --num 5
```

## 命令说明

- `python update_fc3d_data.py`：从东方财富网更新最新开奖数据（默认最近约 500 期）
- `python update_fc3d_data.py --all`：更新全部历史数据（约 7700 期）
- `python fc3d_predictor.py --num 5`：日常预测 5 注
- `python fc3d_predictor.py --num 5 --archive`：预测并归档到 `fc3d_archive/`
- `python fc3d_predictor.py --num 5 --seed 42`：使用随机种子复现实验
- `python fc3d_predictor.py --import-json fc3d_history.json`：导入历史开奖数据
- `python fc3d_predictor.py --backtest --backtest-cycles 30 --num 5`：walk-forward 回测
- `python fc3d_predictor.py --num 5 --weight-patch config/fc3d_weight_patch.json`：加载专家权重补丁

## 数据格式

`fc3d_data.json`：

```json
{
  "metadata": {
    "total_records": 200,
    "date_range": "2025-01-01 至 2025-07-18",
    "last_updated": "2026-06-20 12:00:00",
    "source": "eastmoney-real",
    "is_real": true
  },
  "records": [
    {"period": "2025200", "date": "2025-07-18", "digits": [3, 2, 7]}
  ]
}
```

## 专家说明

- `hot`：追热
- `cold`：追冷
- `missing`：高遗漏
- `cycle`：周期
- `sum`：和值趋势
- `balanced`：奇偶/大小平衡
- `random`：随机扰动
- `adjacent`：邻号漂移

## 性能说明

项目不再把单段历史回测结果写成固定性能承诺。回测会随 `--mode`、注数和时间区间变化，并同时输出理论随机基线：

- `exact` 模式：以联合概率排序为主，目标是评估直选；
- `coverage` 模式：以 MMR 扩大数字覆盖，`avg_digit_hits` 通常会更高，但这不等价于直选命中率提升；
- 随机基线按 1000 个等可能号码中无放回抽取 `num` 注计算，比较时必须同时看 `avg_coverage_size`；
- 历史回测结果仅用于检验假设，不能证明未来开奖存在可利用规律。

## 参考

- `D:/3D/lottery-predictor-main/SKILL.md`
- `D:/3D/lottery-predictor-main/README.md`


## 预测模式与回测指标

- `--mode exact`：按统一综合分选择号码，联合概率是主信号，适合评估直选命中率；这是默认模式。
- `--mode coverage`：使用 MMR 增强多样性和数字覆盖，适合观察数字池命中，不代表直选能力更强。

回测会同时输出：

- `exact_match_rate`：5 注中包含完整直选号码的比例；
- `group_match_rate`：5 注中包含相同数字组合（忽略顺序）的比例；
- `position_hit_rate`：每个位置被至少一注命中的比例；
- `avg_digit_hits`：预测号码覆盖集合与开奖号码数字集合的交集大小；
- `avg_coverage_size`：5 注实际覆盖的不同数字数量；
- `random_baseline`：按 1000 个等可能号码、无放回抽取 `num` 注计算的理论随机基线。

`avg_digit_hits` 必须结合 `avg_coverage_size` 解读：coverage 模式会主动扩大覆盖，不能直接拿它与 exact 模式或随机少覆盖的策略比较。所有开奖仍视为独立随机事件，以上结果仅供实验和娱乐，不构成投注建议。
