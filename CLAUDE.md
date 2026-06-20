# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 参考项目

本项目的预测逻辑、多专家团队、回测归档、权重补丁等设计参考 `D:/3D/lottery-predictor-main`（双色球预测器）。修改本项目的架构级设计时，先对照双色球项目的对应实现，保持风格一致。

## 常用命令

```bash
# 更新开奖数据（从东方财富网抓取）
python update_fc3d_data.py                # 默认最近~500期
python update_fc3d_data.py --all           # 全部历史（~7700期）
python update_fc3d_data.py --pages 20      # 指定页数

# 日常预测
python fc3d_predictor.py --num 5                                    # 预测5注
python fc3d_predictor.py --num 5 --seed 42                          # 固定种子复现
python fc3d_predictor.py --num 5 --archive                          # 预测并归档
python fc3d_predictor.py --num 5 --weight-patch config/fc3d_weight_patch.json

# 数据导入
python fc3d_predictor.py --import-json fc3d_history.json

# 回测
python fc3d_predictor.py --backtest --backtest-cycles 30 --num 5 --seed 42
```

项目无自动化测试套件。验证方式为手动运行上述命令，确认输出格式正确、归档文件生成、回测 JSON 包含预期字段。

## 架构

### 数据流

```
东方财富网 (caipiao.eastmoney.com)
  │  update_fc3d_data.py: requests → BeautifulSoup 解析 HTML 表格
  ▼
fc3d_data.json  ←── 也可通过 --import-json 手动导入
  │  records 按日期倒序: records[0] = 最新一期
  ▼
fc3d_predictor.py
  ├─ predict(): 7专家打分 → 加权聚合 → 候选生成 → 评分排序 → top N
  ├─ backtest(): walk-forward 回测，输出 avg_digit_hits/exact_match_rate/group_match_rate
  └─ archive: → fc3d_archive/{下期期号}.txt
```

### 专家系统的统一接口

7 位专家（`EXPERTS` 字典注册）全部遵循签名：

```python
def xxx_expert(records: List[FC3DRecord]) -> Tuple[List[Dict[int, float]], Dict[str, float]]
```

- **返回值第一部分**：`[pos0_scores, pos1_scores, pos2_scores]`，每个是 `{0-9: 0.0~1.0}` 的按位分数
- **返回值第二部分**：专家元信息字典（如 `{"type": "hot", "window": 60}`），用于输出展示

新增专家只需：实现函数 → 注册到 `EXPERTS` → 在 `DEFAULT_EXPERT_WEIGHTS` 分配默认权重。

### 预测流水线

1. **aggregate_scores()**: 遍历 `EXPERTS`，每位专家对百/十/个位独立打分，按 `weights` 加权求和后归一化
2. **generate_candidates()**: 每位取 top 5 数字做笛卡尔积 → 最多 125 个候选
3. **evaluate_candidate()**: 位置分 + 和值奖励 + 跨度奖励 + 平衡惩罚 + 重复惩罚 → 综合分
4. 按综合分降序排列、去重，取 top N

### 回测机制 (walk-forward)

```python
backtest(records, cycles=30, num=5)
```

从最新一期倒推：第 `i` 期时，用 `records[i+1 : i+121]`（最多 120 期历史）预测 `records[i]`，统计每位数字命中数、直选/组选命中。回测要求 `seed` 固定以复现。

### 权重补丁系统

- `config/fc3d_weight_patch.json` 可选，缺失时不阻断预测
- `parse_weight_patch()` 读取 `expert_weights` 字段，通过 `dict.update()` 合并到 `DEFAULT_EXPERT_WEIGHTS`
- 权重为 0 的专家在 `aggregate_scores` 中被 `continue` 跳过

## 关键约定

- **数据依赖**：预测前必须存在 `fc3d_data.json`，少于 30 期会打印警告但不阻断
- **娱乐声明**：所有输出必须包含"仅供娱乐，不构成投注建议"
- **编码**：UTF-8，文件头含 `# -*- coding: utf-8 -*-`
- **命名**：snake_case 函数/变量，UPPER_CASE 常量，中文注释和文档字符串
- **`fc3d_data.json`** 中 `records` 按日期倒序排列；`digits` 必须是长度为 3 的 `[0-9]` 整数列表
- **归档命名**：`fc3d_archive/{next_period}.txt`，`next_period` = 最新期号 + 1
