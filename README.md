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

## 参考

- `D:/3D/lottery-predictor-main/SKILL.md`
- `D:/3D/lottery-predictor-main/README.md`
