---
name: fc3d-predictor
description: Use when user asks for 福彩3D预测, 3D推荐号, 福彩3D开奖数据导入, 福彩3D回测, 或直接运行 fc3d_predictor.py 相关命令。
---

# 福彩3D娱乐预测器

## 用途

- 用于福彩3D娱乐预测、趋势分析、历史数据导入、回测和归档
- 默认团队模式融合 7 位专家（hot/cold/missing/cycle/sum/balanced/random）输出 top N 注 3D 号码
- 仅供娱乐，不构成任何投注建议

## 触发场景

- 用户要预测下一期福彩3D号码
- 用户要更新福彩3D开奖数据
- 用户要导入福彩3D历史开奖数据
- 用户要运行回测验证预测效果
- 用户要查看最近专家权重或调整权重补丁
- 用户提到 "3D"、"福彩3D"、"排列三"

## 用户可能会这样说

- “帮我预测下一期福彩3D”
- “给我来 5 注 3D 推荐号”
- “导入一下福彩3D历史数据”
- “跑一下福彩3D回测”
- “把 3D 预测结果归档”

## 架构要点

- **项目位置**：`D:/3D/fc3d-predictor-skill/`，代码参考 `D:/3D/lottery-predictor-main`（双色球预测器）的多专家 + 历史回测设计
- **主入口**：`fc3d_predictor.py`
- **数据更新**：`update_fc3d_data.py`，从东方财富网抓取真实开奖数据
- **数据文件**：`fc3d_data.json`，格式与双色球项目类似，每期含 `period/date/digits`（3位数字）
- **专家集合**：8 位规则型专家
  - `hot`：追热（近期高频）
  - `cold`：追冷（近期低频）
  - `missing`：高遗漏（长期未出）
  - `cycle`：周期性（出现间隔方差）
  - `sum`：和值趋势（历史均值±标准差）
  - `balanced`：奇偶/大小再平衡
  - `random`：随机扰动
  - `adjacent`：邻号漂移（±1邻号加权跟随）
- **融合逻辑**：每位专家独立对百/十/个位打分 → 各自产出 top-4 候选 → 与聚合视角 top-6 候选合并 → MMR 多样性选择（λ 自适应回退，确保5注覆盖≥7个不同数字）→ 输出 top N
- **归档目录**：`fc3d_archive/`，文件名 `YYYYXXX.txt`

## 当前要点

- 输出为 3 位数字（如 `3 2 7` 记为 `327`）
- 默认输出 5 注，可通过 `--num` 调整
- 支持 `--seed` 复现实验
- 支持 `--weight-patch` 加载专家权重补丁
- 支持 `--backtest` 进行 walk-forward 回测
- 数据量少于 30 期会提示数据不足

## 最小命令集

- 更新开奖数据：`python update_fc3d_data.py`
- 日常预测：`python fc3d_predictor.py --num 5`
- 带归档：`python fc3d_predictor.py --num 5 --archive`
- 指定随机种子：`python fc3d_predictor.py --num 5 --seed 42`
- 导入历史数据：`python fc3d_predictor.py --import-json fc3d_history.json`
- 回测：`python fc3d_predictor.py --backtest --backtest-cycles 30 --num 5 --seed 42`
- 加载权重补丁：`python fc3d_predictor.py --num 5 --weight-patch config/fc3d_weight_patch.json`

## 典型执行路径

- 日常预测：先运行 `python update_fc3d_data.py` 更新数据，再运行 `python fc3d_predictor.py --num 5`
- 更新开奖数据：`python update_fc3d_data.py`（默认最近约 500 期）或 `python update_fc3d_data.py --all`（全部历史）
- 实验复现：加上 `--seed 42`
- 数据导入：准备 JSON 文件后运行 `--import-json`
- 效果验证：运行 `--backtest --backtest-cycles 30 --num 5`
- 结果保存：加上 `--archive` 写入 `fc3d_archive/`

## 运行约束

- 必须先有 `fc3d_data.json` 或先用 `--import-json` 导入
- 数据过少时脚本会警告但不阻断
- 权重补丁缺失不阻断预测，自动回退默认权重
- 仅供娱乐，不得作为投资或保证中奖依据

## 不要使用本技能的场景

- 用户讨论的是双色球、大乐透、股票、基金、加密货币
- 用户只是问通用 Python / Git / Markdown 问题
- 用户没有要预测、导入数据、回测、运行本工具的需求

## 识别优先级提示

- 只要用户明确提到“福彩3D”“3D”“排列三”“3D推荐号”“3D回测”，优先考虑本技能
- 只要用户是在 `D:/3D/fc3d-predictor-skill/` 或 `lottery-predictor-main` 相关上下文中要求执行福彩3D相关命令，优先考虑本技能

## Example

### Example 1
- 用户：“帮我预测下一期福彩3D，给我 5 注号码。”
- 应触发：运行 `python fc3d_predictor.py --num 5`，必要时先确认数据是否存在。

### Example 2
- 用户：“更新一下福彩3D开奖数据，然后预测 5 注。”
- 应触发：先运行 `python update_fc3d_data.py`，再运行 `python fc3d_predictor.py --num 5`。

### Example 3
- 用户：“跑一下福彩3D回测，看看命中情况。”
- 应触发：运行 `python fc3d_predictor.py --backtest --backtest-cycles 30 --num 5 --seed 42`，关注 `avg_digit_hits`、`exact_match_rate`、`group_match_rate`。

### Example 4
- 用户：“把 3D 预测结果归档。”
- 应触发：运行 `python fc3d_predictor.py --num 5 --archive`，确认 `fc3d_archive/` 下生成新文件。

## 数据格式

`fc3d_data.json` 示例：

```json
{
  "metadata": {
    "total_records": 200,
    "date_range": "2025-01-01 至 2025-07-18",
    "last_updated": "2026-06-20 12:00:00",
    "source": "manual"
  },
  "records": [
    {
      "period": "2025200",
      "date": "2025-07-18",
      "digits": [3, 2, 7]
    }
  ]
}
```

导入 JSON 格式相同。

## 权重补丁格式

`config/fc3d_weight_patch.json` 示例：

```json
{
  "expert_weights": {
    "hot": 1.2,
    "cold": 0.8,
    "missing": 1.0,
    "cycle": 0.7,
    "sum": 1.1,
    "balanced": 0.9,
    "random": 0.2
  }
}
```

## 参考来源

- 本 Skill 的预测逻辑参考 `D:/3D/lottery-predictor-main`（双色球预测器）的专家团队、回测归档、权重补丁等设计
- 双色球项目文档：`D:/3D/lottery-predictor-main/SKILL.md`、`D:/3D/lottery-predictor-main/README.md`
