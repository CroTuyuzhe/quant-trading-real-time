<div align="center">

# rt-trade-signal

> *「盘中盯盘太累？让 AI 帮你盯趋势、判拐点、给信号。」*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)
[![OpenClaw Skill](https://img.shields.io/badge/OpenClaw-Skill-blueviolet)](https://docs.openclaw.ai)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet)](https://claude.ai/code)
[![Data Source](https://img.shields.io/badge/Data-Sina%20%2B%20Tencent-green)](https://finance.sina.com.cn)

<br>

你还在盯着分时图猜涨跌？<br>
你还在纠结「这个位置该买还是该卖」？<br>
你还在错过趋势启动的第一时间入场点？<br>

**盘中实时趋势分析引擎，6 维因子驱动，提前预判拐点。**

<br>

`/buy 600900` → 检测上升趋势，提前买入　|　`/sell 000001` → 检测下跌趋势，尽快卖出

[核心逻辑](#核心逻辑) · [安装](#安装) · [使用](#使用) · [因子体系](#6-维趋势因子) · [效果示例](#效果示例)

</div>

---

## 核心逻辑

**只分析当天分钟数据，不看历史交易日。**

传统技术分析看 K 线形态，rt-trade-signal 看**趋势方向**：

| 你的指令 | 系统在做什么 | 信号 |
|---------|-------------|------|
| `/buy 600900` | 检测上升趋势是否正在形成 | ✅ 趋势形成 → 买入 |
| `/buy 600900` | 发现仍在下跌 / 加速下跌中 | ⏳ 趋势未到 → 等待 |
| `/sell 000001` | 检测下跌趋势是否正在形成 | ✅ 趋势形成 → 卖出 |
| `/sell 000001` | 发现仍在上涨 / 加速上涨中 | ⏳ 趋势向上 → 等待 |

> 核心思想：**不预测点位，只判断趋势方向。趋势对了，入场时机自然对。**

---

## 6 维趋势因子

| 因子 | 作用 | 关键指标 |
|------|------|---------|
| 📈 **价格趋势** | 趋势是基础 | 短期 / 长期最小二乘斜率方向与强度 |
| ⚡ **动量状态** | 拐点前兆 | 三段斜率变化率 → 加速上升 / 减速见顶 |
| 📊 **均线排列** | 趋势确认 | MA5 - MA20 差值变化 → 强化 / 瓦解 / 收窄 |
| 📊 **量能趋势** | 趋势验证 | 近 10 分钟成交量斜率 → 放量确认方向 |
| 🔄 **反转信号** | 拐点预判 | 下跌减速 + 量回升 = 底部；上涨减速 + 放量 = 顶部 |
| 🚀 **突破阶段** | 入场时机 | 距前高距离 + 蓄势 / 确认 / 失败 |

### 决策逻辑（简化版）

```
BUY 路径：
  上升趋势加速形成 ──────────→ 🟢 强买入
  价格趋势向上 + 量能配合 ───→ 🟢 买入
  下跌减速 + 见底信号 ──────→ 🟢 抄底买入
  蓄势待突破 + 多头排列 ────→ 🟢 追突破买入
  下跌加速中 ──────────────→ ⏳ 等待
  见顶信号 ────────────────→ ⏳ 等回调

SELL 路径：
  下跌趋势加速形成 ──────────→ 🔴 强卖出
  见顶信号（上涨减速+放量）──→ 🔴 卖出
  空头排列形成 ────────────→ 🔴 卖出
  突破失败 ────────────────→ 🔴 回撤卖出
  上涨加速中 ──────────────→ ⏳ 等更好卖点
  蓄势突破阶段 ────────────→ ⏳ 等突破结果
```

---

## 安装

### Claude Code

```bash
# 克隆到 Claude Code 的 skills 目录
git clone https://github.com/CroTuyuzhe/quant-trading-real-time.git ~/.claude/skills/rt-trade-signal
```

安装后在 Claude Code 中直接输入 `/buy 600900` 或 `/sell 000001` 即可触发。

### OpenClaw

```bash
# 克隆到 OpenClaw 的 skills 目录
git clone https://github.com/CroTuyuzhe/quant-trading-real-time.git ~/.openclaw/workspace/skills/rt-trade-signal
```

或下载 `.skill` 文件通过 OpenClaw 安装。

### 依赖

```bash
# 无强制依赖，纯 Python 3.9+ 标准库即可运行
# 可选：akshare（兜底数据源）
pip install akshare
```

---

## 使用

### 触发指令

在 Claude Code 或 OpenClaw 对话中直接输入：

| 指令 | 说明 |
|------|------|
| `/buy 600900` | 买入分析 — 长江电力 |
| `/buy 300750` | 买入分析 — 宁德时代 |
| `/sell 000001` | 卖出分析 — 平安银行 |
| `/sell 601318` | 卖出分析 — 中国平安 |

指令格式：`/buy <6位股票代码>` 或 `/sell <6位股票代码>`

### 命令行使用（独立运行）

```bash
# 单次分析
python3 scripts/rt_signal.py --code 600900 --action buy --once

# 循环监控（每 30 秒，最长 30 分钟）
python3 scripts/rt_signal.py --code 600900 --action buy --interval 30 --max-minutes 30
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--code` | 必填 | 6 位股票代码 |
| `--action` | 必填 | `buy` 或 `sell` |
| `--interval` | 30 | 轮询间隔（秒） |
| `--max-minutes` | 30 | 最大运行时间（分钟） |
| `--once` | false | 单次分析模式 |

---

## 效果示例

### 场景一：买入长江电力

```
> /buy 600900

📊 趋势驱动买卖信号 | 600900 买入
============================================================

[21:32:23] #1 🟢买入！  综合:0.740  ¥27.01
        └─ ⚡蓄势待突破 → 📊多头排列强化
```

**解读**：价格接近前高 27.02，缩量蓄势 + MA 多头排列强化 → 上升趋势正在形成，买入信号。

### 场景二：卖出平安银行（趋势向上，不宜卖）

```
> /sell 000001

📊 趋势驱动买卖信号 | 000001 卖出
============================================================

[21:32:29] #1 ⏳等待   综合:0.070  ¥11.27
        └─ 📈上升趋势加速，不宜卖出 → ⚡突破阶段，不宜卖出 → 📊多头排列
```

**解读**：上升趋势加速 + 放量突破确认 + 多头排列 → 三个信号全部指向「不该卖」。

### 场景三：宁德时代见顶预警

```
> /sell 300750

📊 趋势驱动买卖信号 | 300750 卖出
============================================================

[21:33:15] #1 ⏳等待   综合:0.460  ¥401.17
        └─ 🔃见顶信号 → 🔄上涨减速，可能见顶
```

**解读**：检测到上涨减速 + 异常放量（见顶信号），但趋势仍 up，信号冲突 → 建议继续观察。

---

## 数据源

| 源 | 用途 | 方式 |
|------|------|------|
| **新浪财经** | 实时行情 + 五档盘口 + 分钟 K 线 | HTTP API（主） |
| **腾讯财经** | 实时行情兜底 | HTTP API |
| **akshare** | 东财全市场快照 | Python 包（可选兜底） |

> 东方财富主 API 在部分网络环境下不可用，故新浪为主。数据实时免费，无需注册。

---

## 项目结构

```
rt-trade-signal/
├── SKILL.md                 # Agent Skill 入口（OpenClaw / Claude Code）
├── scripts/
│   └── rt_signal.py         # 核心引擎（趋势分析 + 决策循环）
├── references/              # 参考文档（预留）
├── LICENSE
└── README.md
```

---

## 注意事项

- **仅交易时间有效**：9:30-11:30、13:00-15:00（周一至周五），非交易时间自动等待
- **只看当天数据**：不引入历史交易日，避免跨日噪声干扰
- **趋势需要数据积累**：开盘前 30 分钟信号可能不够准确
- **不是交易建议**：本工具仅供辅助参考，投资决策请自行判断

---

## Star History

<a href="https://www.star-history.com/?repos=CroTuyuzhe%2Fquant-trading-real-time&type=date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=CroTuyuzhe/quant-trading-real-time&type=date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=CroTuyuzhe/quant-trading-real-time&type=date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=CroTuyuzhe/quant-trading-real-time&type=date" />
 </picture>
</a>

---

<div align="center">

MIT License © [CroTuyuzhe](https://github.com/CroTuyuzhe)

</div>
