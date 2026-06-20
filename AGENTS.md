# AGENTS.md — 福彩3D娱乐预测器

> 本文件面向 AI Coding Agent，总结项目结构、运行方式与开发约定。
> 项目自然语言为中文，代码注释与文档均使用中文。

## 项目概述

本项目是一个轻量级的**福彩3D娱乐预测器**，基于历史开奖数据，使用 7 位规则型专家（hot/cold/missing/cycle/sum/balanced/random）按位打分、加权聚合，输出 top N 注 3D 号码推荐。

- **用途**：仅供娱乐，不构成任何投注建议。
- **定位**：参考 `D:/3D/lottery-predictor-main`（双色球预测器）的多专家团队 + 历史回测 + 权重补丁设计，针对福彩3D（3 位数字 0-9）进行简化实现。
- **主入口**：`fc3d_predictor.py`
- **数据更新**：`update_fc3d_data.py`
- **数据文件**：`fc3d_data.json`
- **归档目录**：`fc3d_archive/`
- **权重补丁**：`config/fc3d_weight_patch.json`

## 技术栈

- **语言**：Python 3（已在 Python 3.14 验证可运行）
- **标准库**：`argparse`、`json`、`math`、`os`、`random`、`sys`、`collections`、`dataclasses`、`datetime`、`typing`
- **第三方库**：
  - `requests`（`update_fc3d_data.py` 用于 HTTP 抓取）
  - `beautifulsoup4`（解析东方财富网 HTML 表格）
- **包管理**：项目未使用 `pyproject.toml`、`requirements.txt`、`setup.py`、`Pipfile` 或 `package.json`，依赖需由运行环境自行保证已安装。
- **构建/部署**：无正式构建流程、无 CI/CD、无容器化、无部署脚本。直接运行 Python 脚本即可。

## 文件组织

```
.
├── fc3d_predictor.py          # 主程序：预测、回测、归档、导入
├── update_fc3d_data.py        # 数据更新：从东方财富网抓取开奖数据
├── fc3d_data.json             # 本地历史开奖数据（JSON）
├── config/
│   └── fc3d_weight_patch.json # 专家权重补丁（可选）
├── fc3d_archive/
│   └── 2025201.txt            # 预测结果归档示例
├── README.md                  # 面向用户的中文说明
├── SKILL.md                   # Agent 触发场景与最小命令集
└── AGENTS.md                  # 本文件
```

## 代码组织

`fc3d_predictor.py` 为单文件脚本，主要模块划分如下：

- **数据模型**：`FC3DRecord`（单期记录）、`PredictionResult`（预测结果）
- **数据加载/保存**：`load_data`、`save_data`
- **统计工具**：`digit_position_frequency`、`digit_overall_frequency`、`missing_gaps`、`normalize_scores`
- **专家实现**：`hot_expert`、`cold_expert`、`missing_expert`、`cycle_expert`、`sum_expert`、`balanced_expert`、`random_expert`
- **专家注册表**：`EXPERTS` 字典、`DEFAULT_EXPERT_WEIGHTS`
- **融合与候选生成**：`aggregate_scores`、`generate_candidates`
- **候选评估**：`evaluate_candidate`（考虑位置分、和值、跨度、平衡、重复惩罚）
- **主预测逻辑**：`predict`
- **输出与归档**：`format_output`、`archive_prediction`
- **回测**：`backtest`（walk-forward，统计 `avg_digit_hits`、`exact_match_rate`、`group_match_rate`）
- **权重补丁解析**：`parse_weight_patch`
- **CLI 入口**：`main`

`update_fc3d_data.py` 功能划分：

- `load_existing_data` / `save_data`：本地数据读写
- `parse_page`：HTML 表格解析
- `fetch_page` / `fetch_all_records`：分页抓取
- `merge_records`：按 `period` 增量去重合并
- `main`：CLI 入口

## 常用命令

### 更新数据

```bash
# 默认抓取最近约 500 期（10 页）
python update_fc3d_data.py

# 抓取全部历史数据（约 7700 期，154 页）
python update_fc3d_data.py --all

# 指定页数
python update_fc3d_data.py --pages 20
```

### 日常预测

```bash
# 预测 5 注
python fc3d_predictor.py --num 5

# 指定随机种子复现实验
python fc3d_predictor.py --num 5 --seed 42

# 加载权重补丁
python fc3d_predictor.py --num 5 --weight-patch config/fc3d_weight_patch.json

# 预测并归档
python fc3d_predictor.py --num 5 --archive
```

### 回测

```bash
python fc3d_predictor.py --backtest --backtest-cycles 30 --num 5 --seed 42
```

回测输出 JSON，关注指标：

- `avg_digit_hits`：平均命中数字数
- `exact_match_rate`：直选命中率
- `group_match_rate`：组选命中率

### 导入历史数据

```bash
python fc3d_predictor.py --import-json fc3d_history.json
```

导入文件格式与 `fc3d_data.json` 一致：

```json
{
  "records": [
    {"period": "2025200", "date": "2025-07-18", "digits": [3, 2, 7]}
  ]
}
```

## 数据格式

`fc3d_data.json` 结构：

```json
{
  "metadata": {
    "total_records": 350,
    "date_range": "2025-01-01 至 2026-06-19",
    "last_updated": "2026-06-20 14:07:41",
    "source": "eastmoney-real",
    "is_real": true
  },
  "records": [
    {"period": "2026160", "date": "2026-06-19", "digits": [3, 3, 2]}
  ]
}
```

- `records` 在文件中按日期**倒序**排列，`records[0]` 为最新一期。
- `digits` 必须是长度为 3 的整数列表，每位范围 0-9。

## 权重补丁格式

`config/fc3d_weight_patch.json` 示例：

```json
{
  "expert_weights": {
    "hot": 2.0,
    "cold": 0.1,
    "missing": 1.0,
    "cycle": 0.8,
    "sum": 0.9,
    "balanced": 0.8,
    "random": 0.0
  }
}
```

- 权重补丁**可选**。缺失时自动回退到 `DEFAULT_EXPERT_WEIGHTS`。
- 补丁中未指定的专家保持默认权重。

## 代码风格约定

- 使用 **UTF-8** 编码，文件头包含 `#!/usr/bin/env python3` 和 `# -*- coding: utf-8 -*-`。
- 注释和文档字符串使用中文。
- 类型注解使用 `typing` 模块（`Dict`、`List`、`Optional`、`Tuple` 等）。
- 常量使用全大写（如 `DATA_FILE`、`ALL_DIGITS`）。
- 函数和变量使用小写下划线命名（snake_case）。
- 专家函数统一返回 `Tuple[List[Dict[int, float]], Dict[str, float]]`。
- 尽量保持与 `lottery-predictor-main` 风格一致，便于跨项目维护。

## 测试策略

- 项目**没有自动化测试套件**（无 `pytest`、`unittest` 目录或测试文件）。
- 验证方式以**手动运行**为主：
  1. 运行 `python update_fc3d_data.py` 确认能正常抓取并更新 `fc3d_data.json`。
  2. 运行 `python fc3d_predictor.py --num 5 --seed 42` 确认输出格式正确。
  3. 运行 `python fc3d_predictor.py --backtest --backtest-cycles 30 --num 5 --seed 42` 确认回测 JSON 输出包含预期字段。
  4. 运行 `python fc3d_predictor.py --num 5 --archive` 确认 `fc3d_archive/` 下生成新文件。

## 安全与运行注意事项

- **仅供娱乐**：所有输出必须附带"仅供娱乐，不构成投注建议"的提示。不得向用户承诺中奖。
- **网络抓取**：`update_fc3d_data.py` 访问东方财富网（`caipiao.eastmoney.com`），请遵守目标网站的 robots 协议与访问频率，避免频繁抓取。
- **数据依赖**：运行预测前需确保 `fc3d_data.json` 存在，或先使用 `--import-json` 导入。
- **数据不足警告**：历史数据少于 30 期时，脚本会输出警告但不会阻断执行。
- **无外部服务依赖**：除数据更新脚本的 HTTP 请求外，预测逻辑完全离线运行。

## 扩展与维护提示

- 新增专家：在 `fc3d_predictor.py` 中实现函数并注册到 `EXPERTS`，同时在 `DEFAULT_EXPERT_WEIGHTS` 中分配默认权重。
- 调整评分逻辑：修改 `evaluate_candidate` 中的和值、跨度、平衡、重复惩罚规则。
- 归档路径：默认写入 `fc3d_archive/{next_period}.txt`，`next_period` 由最新一期 `period + 1` 计算。
