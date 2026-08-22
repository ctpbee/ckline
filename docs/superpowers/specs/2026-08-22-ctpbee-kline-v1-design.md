# ctpbee_kline v1.0 设计文档

日期: 2026-08-22
状态: 已批准
仓库: E:\AI\ckline (ctpbee_kline 包), 依赖 E:\AI\ctpbee (dev 分支, ≥1.8)

## 1. 背景与目标

ctpbee 2026-08-21 的重构(见 ctpbee 仓库 agentic.md changelog)把 `tool_register`
抽成仅依赖标准库的独立原语(`ctpbee/tool_register.py`),基类 `Tool.on_tick/on_bar/...`
默认挂接装饰器(订阅即生效),`add_func/remove_func/subscribe` 公开,并新增
`register_tool_hook/unregister_tool_hook` 导出——明确以"其他库可以使用"为目标。

ctpbee_kline 0.2(2026-05)是旧机制的第一个消费者,存在:

1. **首 tick 订阅 hack**: `on_tick` 首次触发时遍历 `app._extensions` 手动
   `add_func` 各策略的 `on_bar`——首个 tick 之后注册的策略永远收不到 bar;
   且依赖私有 `_extensions`,接线时机不可控。
2. **导入路径过时**: `from ctpbee.level import tool_register`(靠 re-export 苟活)。
3. **测试缺口**: 9 个纯算术用例,订阅分发机制零覆盖。
4. **日/周线按自然日分桶**: 夜盘跨零点 tick(如 00:30)错误归入新交易日。

v1.0 目标: 对接新架构、夜盘交易日感知、四项功能增强、保持 0.2 兼容,发 1.0.0。

## 2. 范围(已确认)

- **架构对接**: 独立 `tool_register` 原语;自动接线时机修复(后注册策略也能收到 bar)
- **夜盘感知**: 内置交易日规则(见 §5.3),tick 带 `trading_day` 属性时优先;
  周线锚定交易周(周一)
- **功能增强**(全部四项):
  1. 单实例多周期: `Kline(["5m", "1h"])`
  2. 任意分钟/小时周期: `"7m"`, `"3h"`(`d`/`w` 仍固定)
  3. 当前 bar 查询 + 历史缓存: `get_current`/`get_bars`
  4. bar 驱动合成: 1m `BarData` 喂入合成高周期 bar
- **兼容**: `Kline("5m")` 旧写法不变;策略 `on_bar` 默认自动分发 + 显式订阅 API
- **发布**: 1.0.0,`ctpbee>=1.8`,`python_requires>=3.9`;PyPI 发布不在本次范围

### 非目标

- 不改 ctpbee 上游(TickData 不加 trading_day 字段——预留消费即可)
- 不做纯引擎/适配层拆分(方案 C 已否决)
- 不做多 Tool 组合注册(方案 B 已否决)
- 不发 PyPI

## 3. 包结构(方案 A)

```
ctpbee_kline/
├── __init__.py      # 公开 Kline(Tool): 构造、接线、分发、兼容
├── interval.py      # 纯标准库: 周期解析、时间分桶、交易日推导
└── aggregator.py    # 每周期一个 _Aggregator: 聚合状态机 + 闭合 bar 事件通道
```

依赖方向: `__init__` → `aggregator` → `interval` → (仅 interval 的 enum 字段
指向 ctpbee 常量,其余纯标准库)。

## 4. `interval.py` — 周期与时间

### 4.1 周期语法

- `Nm` / `Nh`: N 为任意正整数分钟/小时(如 `7m`, `3h`)
- `d` / `w`: 固定日线/周线
- 非法输入 `ValueError`,消息列出完整语法说明

`IntervalSpec` 为不可变 NamedTuple:

| 字段 | 类型 | 说明 |
|---|---|---|
| `value` | `int` | 数值(`d`/`w` 恒为 1) |
| `unit` | `str` | `"minute"` / `"hour"` / `"day"` / `"week"` |
| `key` | `str` | 规范化键(即构造入参,如 `"7m"`) |
| `enum` | `Interval` | 分钟族→`MINUTE`,小时族→`HOUR`,`d`→`DAILY`,`w`→`WEEKLY` |

注: ctpbee `Interval` 枚举无粒度区分,5m/7m/30m 均为 `MINUTE`,属上游限制,
README 如实标注。

兼容: 保留模块级 `_INTERVAL_META`(9 个规范周期 → IntervalSpec 的映射,供
错误提示与 0.2 测试导入兼容),从 `interval.py` 导出。

### 4.2 时间分桶 `bucket_start(dt, spec) -> datetime`

- minute: `dt.replace(minute=dt.minute // N * N, second=0, microsecond=0)`
- hour: `dt.replace(hour=dt.hour // N * N, minute=0, second=0, microsecond=0)`
- day: 交易日的 00:00(见 §5.3)
- week: 交易日所在自然周的周一 00:00

## 5. `aggregator.py` — `_Aggregator(spec, history)`

### 5.1 每合约状态

沿用 0.2 紧凑列表(已被 0.2 的 9 个测试验证,不重造):

```
[bucket_start, high, open, low, close, vol_start, vol_latest]
```

`_bars: dict[local_symbol, list]`;闭合时 bar 丢弃,重开新列表。

### 5.2 两条输入路径共用核心 `_apply()`

| 路径 | 入口 | 成交量语义 | 闭合 bar 的 volume |
|---|---|---|---|
| tick 驱动 | `update_tick(tick)` | CTP 累计量 → 差分 | `vol_latest - vol_start`(重置守卫: 差分 < 0 → 0) |
| bar 驱动 | `update_bar(bar)` | bar 自带区间量 | 各 bar.volume 直接累加 |

闭合判定: `new_bucket > current_bucket`(严格大于;等于→更新;小于→乱序处理,见 §7)。
bar 驱动仅对分钟族/小时族聚合器有效(`d`/`w` 无上游 bar 源,`update_bar` 对其
为 no-op);喂入的 bar.datetime 取其分桶起始(1m bar 的对齐分钟)。

### 5.3 交易日规则(纯函数 `trading_day(dt) -> date`)

```
dt.date() + 1天   若 dt.time() >= 20:00
dt.date()          其余(含 <03:00 凌晨夜盘与日盘)
```

- ≥20:00 的 tick 属于次日开始计价的交易日(当晚夜盘开启次日交易日)
- 凌晨 tick(00:00~02:30 收盘)自然归当日(前夜 21:00 开启的那个交易日)
- tick 携带 `trading_day` 属性(date/datetime)时优先使用
- 覆盖国内期货全部夜盘收盘时点(23:00/01:00/02:30);无夜盘品种夜间无
  tick,规则天然 no-op
- 节假日无 tick 产生,不依赖日历表

### 5.4 分发: 只用原语

`_Aggregator.emit(bar)` 以 `@tool_register(spec.key)` 装饰并返回 bar——
**仅在闭合时被调用**,订阅者每次必收到真 bar,永不收到 None。

- 订阅: `register_tool_hook(agg, spec.key, func)`;退订: `unregister_tool_hook`
- 快照迭代、异常隔离+节流日志、去重、保序——全部由 `ctpbee.tool_register` 提供

### 5.5 查询与历史缓存

- 每合约 `deque(maxlen=history)` 存闭合 bar;闭合时**先 append 历史再 emit**
- `get_current(symbol) -> BarData | None`: 未闭合 bar 的快照(构造 BarData 返回,不动内部状态)
- `get_bars(symbol, n=None) -> list[BarData]`: 最近 n 根闭合 bar(默认全部)

## 6. `__init__.py` — `Kline(Tool)` 公开 API

### 6.1 构造

```python
Kline(intervals="1m", *, history=4096, auto_wire=True, name=None)
```

- `intervals`: str 或 str 列表;单字符串 `Kline("5m")` 为 0.2 兼容写法
- 工具名: 单周期 `kline_{interval}`(0.2 兼容),多周期 `"kline"`,`name` 覆盖
- `history`: 每合约每周期闭合 bar 缓存深度
- `auto_wire=False`: 关闭自动接线,纯显式订阅

### 6.2 框架回调

- 重写 `on_tick`: **自行**装饰 `@tool_register(ToolRegisterType.TICK)`
  (level.py 约定: 子类重写需自行装饰);遍历聚合器 `update_tick`,
  闭合则调 `agg.emit(bar)`
- 重写 `on_bar`: 装饰 `@tool_register(ToolRegisterType.BAR)`;把 bar 喂给
  分钟族/小时族聚合器(bar 驱动路径,`d`/`w` 聚合器对此 no-op;框架
  `process_bar_event` 原生调 `tool.on_bar`)
- `emit` 的调用点在 `on_tick`/`on_bar` 内,闭合即推,顺序: 先 append 历史
  再 emit

### 6.3 自动接线(替代 0.2 首 tick hack)

- `init_app(app)`: 调 `Tool.init_app`;给当时已存在的策略接线
  (策略 `on_bar` 注册到各聚合器 emit 通道)
- 之后每个 tick: 以一次 `len(app._extensions)` 整数比较监测,数量变化时
  做 diff,只接新增策略(维持 `_wired` id 集合)
- 接线仍读私有 `app._extensions`(0.2 已如此依赖,上游稳定;README 标注)

### 6.4 显式订阅

```python
kline.subscribe("5m", func, symbols=None)   # symbols: Optional[set[str]|list[str]]
kline.unsubscribe("5m", func)
```

- 包装 `register_tool_hook/unregister_tool_hook`
- `symbols` 给定时用闭包过滤 `bar.local_symbol`;Kline 按 `(interval_key, func)`
  簿记闭包,`unsubscribe` 传原函数即可对称退订

### 6.5 导出

`Kline`(及 `_INTERVAL_META` 兼容导出)。

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| 非法周期串 | `ValueError`,消息含语法说明 |
| 累计量重置(差分<0) | bar volume 记 0(0.2 行为,保留) |
| 乱序 tick(new_bucket < current) | 不闭合、就地更新当前 bar(0.2 会错误闭合一根陈旧 bar——修复) |
| hook 异常 | 原语隔离 + 节流日志,不进 tick 热路径 |
| `tick.trading_day` 存在 | 优先使用,不做格式校验之外的容错 |

## 8. 测试计划(独立脚本套件,无 pytest;`python tests/<name>.py` 非零退出码即失败)

延续 ctpbee 2026-08-21 立下的规矩: **每次改动配测试落地**。

| 套件 | 覆盖 |
|---|---|
| `tests/test_interval.py` | 解析合法/非法/任意 N;分桶对齐(1m~30m, 1h~4h, 7m, 3h, d, w);交易日规则(20:00 边界前后、00:30 夜盘、02:30/03:00、日盘、trading_day 属性优先);周锚定(周三→周一、跨月周) |
| `tests/test_aggregator.py` | OHLC 更新/差分/闭合/跳跃(中间缺 tick)/多合约独立/累计量重置/乱序不闭合;emit 仅闭合时触发(hook 计数=闭合数,永不 None);tick 与 bar 两路等价(同一分钟序列两种喂法 → 相同高周期 bar);历史缓存与 get_current 快照不可变性 |
| `tests/test_kline_tool.py` | FakeApp(假 `_extensions`/`tools` dict)下: init_app 接线;**后注册策略收到 bar**;显式订阅/退订/合约过滤;`Kline("5m")` 兼容与命名 `kline_5m`;多周期扇出互不串扰;auto_wire=False;默认 1m |

环境前置: 当前 `ctpbee` editable 安装的 finder 在非仓库 cwd 下损坏
(`ctpbee.__file__ is None`),`ctpbee_kline` 是 site-packages 旧拷贝——
先 `pip install -e E:/AI/ctpbee --force-reinstall --no-deps` 与
`pip install -e E:/AI/ckline` 修复,套件不得依赖 cwd。

## 9. 打包与文档

- `setup.py`: version 1.0.0,`install_requires=["ctpbee>=1.8"]`,
  `python_requires=">=3.9"`
- README 重写: 新 API(多周期/任意周期/查询/bar 驱动/显式订阅)、夜盘交易日
  语义、`Interval` 枚举无粒度与 `_extensions` 私有依赖的如实标注
- 版本号变更遵循 semver

## 10. 已确认的决策记录

| 决策 | 选择 | 备选(否决原因) |
|---|---|---|
| 结构 | A: 单 Kline + 三层内部分层 | B 多 Tool 组合(tools 污染/重复循环); C 纯引擎解耦(YAGNI) |
| 交易日来源 | 内置规则 + tick 属性预留 | 上游加字段(改动面大、三份 md_api 需同步) |
| 分发模型 | 自动分发默认 + 显式订阅并存 | 纯显式(0.2 用户 on_bar 静默失效) |
| 版本 | 1.0.0 + pin ctpbee>=1.8 | 不设下限(旧 ctpbee 导入报错难排查); dev 版(无必要) |
