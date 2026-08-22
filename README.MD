# ctpbee_kline — 多周期 K 线生成工具

tick/bar 双驱动、夜盘交易日感知的多周期 K 线合成。
基于 ctpbee ≥1.8 的 `tool_register` 独立原语构建。

## 安装

```bash
pip install ctpbee_kline      # 依赖 ctpbee>=1.8, Python>=3.9
```

## 快速使用(0.2 兼容)

```python
from ctpbee import CtpbeeApi, CtpBee
from ctpbee.constant import *
from ctpbee_kline import Kline


class Main(CtpbeeApi):
    def on_tick(self, tick: TickData) -> None:
        pass

    def on_bar(self, bar: BarData):
        print(bar.interval, bar)   # 逐根收到闭合 K 线


kline = Kline()                     # 默认 1m
app = CtpBee("market", __name__, refresh=True).with_tools(kline)
app.config.from_json("config.json")
app.add_extension(Main("DailyCTA"))
app.start()
```

策略的 `on_bar` 自动收到闭合 K 线——包括**启动之后才注册**的策略。

## 多周期 / 任意周期

```python
kline = Kline(["1m", "5m", "15m", "1h"])   # 单实例多周期, 一次 tick 全部更新
kline = Kline("7m")                         # 任意 N 分钟/小时: "3m" "7m" "3h" ...
kline = Kline("d")                          # 日线(夜盘感知); "w" 周线
```

## 显式订阅与合约过滤

```python
kline.subscribe("5m", my_func)                          # 该周期闭合 bar
kline.subscribe("5m", my_func, symbols={"rb2505.SHFE"}) # 只收指定合约
kline.unsubscribe("5m", my_func)
```

自动分发与显式订阅并存; `Kline("5m", auto_wire=False)` 可关闭自动分发。

## bar 驱动(无需 tick)

Recorder 的 bar 事件(如 1m bar)可直接驱动分钟/小时族合成:

```python
kline = Kline(["5m", "1h"])   # 1m bar 喂入 → 5m/1h 闭合 bar 照常推送
```

## 查询当前 bar 与历史

```python
kline.get_current("rb2505.SHFE")                 # 未闭合 bar 快照(单周期实例)
kline.get_bars("rb2505.SHFE", n=100)             # 最近 100 根闭合 bar
kline.get_current("rb2505.SHFE", interval="5m")  # 多周期实例需指定 interval
```

历史缓存深度由 `Kline(..., history=4096)` 控制。

## 夜盘交易日语义

`TickData` 目前无 `trading_day` 字段, 本工具内置规则推导:
**20:00(含)之后的 tick 属次日开始计价的交易日**, 其余(含凌晨夜盘与
日盘)属当日。若 tick 将来携带 `trading_day` 属性则自动优先使用。
日线 = 交易日全天(含其前夜夜盘); 周线锚定交易日所在自然周(周一)。

## 已知限制

- ctpbee `Interval` 枚举无粒度: 5m/7m/30m 的 `BarData.interval` 均为
  `MINUTE`——需区分时用 bar 的 `datetime` 对齐关系或自行记录周期。
- 自动接线读取 `app._extensions`(上游私有结构, 多年稳定)。
- 无节假日日历; 节假日无 tick 自然不产生 bar, 跨节假日周线按自然周归组。

## 测试

```bash
python tests/test_interval.py && python tests/test_aggregator.py && python tests/test_kline_tool.py
```
