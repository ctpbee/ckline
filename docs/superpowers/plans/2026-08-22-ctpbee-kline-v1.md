# ctpbee_kline v1.0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ctpbee_kline 0.2 → 1.0.0: 对接 ctpbee 新 tool_register 架构、夜盘交易日感知的日/周线、单实例多周期 + 任意 N 分钟/小时周期 + 当前 bar 查询/历史缓存 + bar 驱动合成, 保持 0.2 API 兼容。

**Architecture:** 三层单包——`interval.py`(纯函数: 周期解析/分桶/交易日) → `aggregator.py`(每周期一个 `_Aggregator` 状态机, 闭合 bar 经 `tool_register` 原语扇出) → `__init__.py`(公开 `Kline(Tool)`: 构造/接线/订阅)。分发完全复用 `ctpbee.tool_register` 原语(快照迭代/异常隔离/去重), 不自造扇出。设计文档: `docs/superpowers/specs/2026-08-22-ctpbee-kline-v1-design.md`。

**Tech Stack:** Python ≥3.9, ctpbee ≥1.8(E:\AI\ctpbee, dev 分支), 无第三方新依赖; 测试为独立脚本套件(无 pytest), 沿用 ctpbee 仓库 2026-08-21 立下的规矩: 每次改动配测试落地。

---

## 约定(执行前必读)

- **工作目录**: 所有命令在 `E:/AI/ckline`(git 仓库, main 分支)执行, 除非另注明。
- **测试风格**: 每个 `tests/test_*.py` 是独立脚本——顶部 `RESULTS`/`check()` 收集断言, `__main__` 汇总并 `sys.exit(1 if failed else 0)`。**成功标准: 退出码 0 且全部 ✅**。运行方式 `python tests/<name>.py`, 不用 pytest。
- **提交**: 每个任务结束提交一次, 消息格式 `feat|fix|docs|test: ...`, 尾部加 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- **上游接口事实**(已核实, 直接依赖):
  - `ctpbee/tool_register.py` 提供 `tool_register(tool_type)` 装饰器(方法返回后把返回值喂给通道回调)与 `register_tool_hook(obj, key, func)` / `unregister_tool_hook(obj, key, func)`; 回调表挂实例属性 `_linked`——**同一装饰键在不同实例上互不串扰**(实例级路由)。
  - `ctpbee.level.Tool.__init__(name, app=None)`; `Tool.init_app(app)` 注册进 `app.tools`; 基类 `on_tick` 等已装饰, **子类重写需自行装饰**(level.py 注释明示)。
  - `ctpbee.record.Recorder.process_tick_event` 逐 tool 调 `tool.on_tick(tick)`; `process_bar_event` 调 `tool.on_bar(bar)`。
  - `BarData(symbol, exchange, datetime, interval=, volume=, open_price=, high_price=, low_price=, close_price=)`; exchange 接受字符串或枚举(`_exchange_code`, 2026-08-21h); `local_symbol` 自动合成。
  - `TickData` **无** `trading_day` 字段(预留消费)。
- **体积守则**: 新代码不得用 `dict[str, list]`、`X | None` 等运行期求值标注(Python 3.9 兼容); 字符串标注或注释代替。

---

### Task 0: 环境修复(editable 安装)

**Files:** 无代码改动(仅环境; 不提交)

- [ ] **Step 1: 重装两个 editable 包**

当前环境: `ctpbee` editable 安装的 finder 损坏(非仓库 cwd 下 `ctpbee.__file__ is None`), `ctpbee_kline` 是 site-packages 里的 0.2 旧拷贝(会遮蔽仓库代码)。修复:

```bash
python -m pip install -e E:/AI/ctpbee --no-deps
python -m pip install -e E:/AI/ckline
```

注意 `--no-deps`: ctpbee 依赖已装齐, 避免 pip 重装/升级它们。

- [ ] **Step 2: 验证导入(在非仓库 cwd 下)**

```bash
cd E:/AI && python -c "import ctpbee, ctpbee_kline; print(ctpbee.__file__); print(ctpbee_kline.__file__); from ctpbee.tool_register import register_tool_hook; print('primitive OK')"
```

Expected: 两行路径分别指向 `E:\AI\ctpbee\ctpbee\__init__.py` 与 `E:\AI\ckline\ctpbee_kline\__init__.py`(不是 None、不在 site-packages), 且打印 `primitive OK`。

**Fallback**(若 editable 仍坏): 所有测试命令前加 `PYTHONPATH="E:/AI/ctpbee;E:/AI/ckline"`(Windows bash 下分号分隔并整体引号), 并在 Task 5 提交说明中记录环境问题。

- [ ] **Step 3: 旧套件基线(确认改造前是绿的)**

```bash
cd E:/AI/ckline && python tests/test_kline.py
```

Expected: `9 通过 / 0 失败`, 退出码 0。

---

### Task 1: `interval.py` — 周期解析/分桶/交易日

**Files:**
- Create: `ctpbee_kline/interval.py`
- Test: `tests/test_interval.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_interval.py`:

```python
"""interval 套件: 周期解析 / 时间分桶 / 交易日规则。

运行: python tests/test_interval.py   (退出码 0 = 全部通过)
"""
import sys
from datetime import date, datetime

from ctpbee.constant import Interval
from ctpbee_kline.interval import (
    _INTERVAL_META, bucket_start, parse_interval, tick_trading_day, trading_day,
)

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(f"  {'✅' if cond else '❌'} {name}")


def raises_ve(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def test_parse_valid():
    print("── 解析: 规范 9 周期 ──")
    expect = {
        "1m":  (1,  "minute", Interval.MINUTE),
        "5m":  (5,  "minute", Interval.MINUTE),
        "15m": (15, "minute", Interval.MINUTE),
        "30m": (30, "minute", Interval.MINUTE),
        "1h":  (1,  "hour",   Interval.HOUR),
        "2h":  (2,  "hour",   Interval.HOUR),
        "4h":  (4,  "hour",   Interval.HOUR),
        "d":   (1,  "day",    Interval.DAILY),
        "w":   (1,  "week",   Interval.WEEKLY),
    }
    for key, (v, u, e) in expect.items():
        s = parse_interval(key)
        check(f"parse({key!r}) -> value={v} unit={u!r} enum",
              (s.value, s.unit, s.enum) == (v, u, e))
        check(f"parse({key!r}).key == {key!r}", s.key == key)
    check("_INTERVAL_META 恰含 9 个规范周期", set(_INTERVAL_META) == set(expect))


def test_parse_any_n():
    print("── 解析: 任意 N 分钟/小时 ──")
    s7 = parse_interval("7m")
    check("7m -> (7, minute, MINUTE)",
          (s7.value, s7.unit, s7.enum) == (7, "minute", Interval.MINUTE))
    s3 = parse_interval("3h")
    check("3h -> (3, hour, HOUR)",
          (s3.value, s3.unit, s3.enum) == (3, "hour", Interval.HOUR))
    s90 = parse_interval("90m")
    check("90m -> (90, minute, MINUTE)",
          (s90.value, s90.unit, s90.enum) == (90, "minute", Interval.MINUTE))


def test_parse_invalid():
    print("── 解析: 非法输入 ──")
    for bad in ["3x", "0m", "0h", "", "m", "h", "1d", "d5", "1.5m", "5M", None, 123]:
        check(f"parse({bad!r}) raises ValueError",
              raises_ve(lambda b=bad: parse_interval(b)))


def test_bucket_minute_hour():
    print("── 分桶: 分钟/小时 ──")
    base = datetime(2025, 1, 6, 14, 3, 27)  # 周一
    cases = [
        ("1m", base, datetime(2025, 1, 6, 14, 3)),
        ("5m", base, datetime(2025, 1, 6, 14, 0)),
        ("15m", base, datetime(2025, 1, 6, 14, 0)),
        ("30m", base, datetime(2025, 1, 6, 14, 0)),
        ("7m", datetime(2025, 1, 6, 14, 8), datetime(2025, 1, 6, 14, 7)),
        ("7m", datetime(2025, 1, 6, 14, 6), datetime(2025, 1, 6, 14, 0)),
        ("1h", base, datetime(2025, 1, 6, 14, 0)),
        ("2h", base, datetime(2025, 1, 6, 14, 0)),
        ("3h", base, datetime(2025, 1, 6, 12, 0)),
        ("4h", base, datetime(2025, 1, 6, 12, 0)),
        ("1h", datetime(2025, 1, 6, 15, 0), datetime(2025, 1, 6, 15, 0)),
    ]
    for key, dt, want in cases:
        got = bucket_start(dt, parse_interval(key))
        check(f"{key}: {dt.time()} -> {want.time()}", got == want)


def test_trading_day():
    print("── 交易日规则(夜盘感知) ──")
    cases = [
        (datetime(2025, 1, 6, 9, 0), date(2025, 1, 6)),      # 日盘
        (datetime(2025, 1, 6, 14, 59), date(2025, 1, 6)),
        (datetime(2025, 1, 6, 19, 59, 59), date(2025, 1, 6)),
        (datetime(2025, 1, 6, 20, 0), date(2025, 1, 7)),     # 夜盘开启 -> 次日
        (datetime(2025, 1, 6, 22, 0), date(2025, 1, 7)),
        (datetime(2025, 1, 6, 23, 59), date(2025, 1, 7)),
        (datetime(2025, 1, 7, 0, 30), date(2025, 1, 7)),     # 凌晨夜盘 -> 当日
        (datetime(2025, 1, 7, 2, 30), date(2025, 1, 7)),
        (datetime(2025, 1, 7, 3, 0), date(2025, 1, 7)),
    ]
    for dt, want in cases:
        check(f"trading_day({dt}) == {want}", trading_day(dt) == want)


def test_bucket_day_week():
    print("── 分桶: 日线/周线(交易日感知) ──")
    d, w = parse_interval("d"), parse_interval("w")
    check("d: Mon 21:00 -> Tue 00:00",
          bucket_start(datetime(2025, 1, 6, 21, 0), d) == datetime(2025, 1, 7))
    check("d: Tue 09:00 -> Tue 00:00",
          bucket_start(datetime(2025, 1, 7, 9, 0), d) == datetime(2025, 1, 7))
    check("d: Tue 00:30(凌晨夜盘) -> Tue 00:00",
          bucket_start(datetime(2025, 1, 7, 0, 30), d) == datetime(2025, 1, 7))
    check("d: Fri 22:00 -> Sat 00:00",
          bucket_start(datetime(2025, 1, 10, 22, 0), d) == datetime(2025, 1, 11))
    check("w: Wed 10:00 -> Mon 01-06",
          bucket_start(datetime(2025, 1, 8, 10, 0), w) == datetime(2025, 1, 6))
    check("w: Fri 22:00 -> Mon 01-06 (夜盘仍属本周)",
          bucket_start(datetime(2025, 1, 10, 22, 0), w) == datetime(2025, 1, 6))
    check("w: Sat 00:30 -> Mon 2024-12-30 (跨年周)",
          bucket_start(datetime(2025, 1, 4, 0, 30), w) == datetime(2024, 12, 30))


def test_tick_trading_day_hint():
    print("── trading_day 属性预留 ──")

    class WithDate:
        trading_day = date(2025, 3, 3)

    class WithDatetime:
        trading_day = datetime(2025, 3, 3, 21, 0)

    class Bare:
        pass

    check("date 属性直取", tick_trading_day(WithDate()) == date(2025, 3, 3))
    check("datetime 属性取 .date()",
          tick_trading_day(WithDatetime()) == date(2025, 3, 3))
    check("无属性 -> None", tick_trading_day(Bare()) is None)
    check("td_hint 优先于内置规则",
          bucket_start(datetime(2025, 1, 6, 10, 0), parse_interval("d"),
                       date(2025, 1, 9)) == datetime(2025, 1, 9))


if __name__ == "__main__":
    print("=" * 60)
    print("  ctpbee_kline interval 套件")
    print("=" * 60)
    for fn in (test_parse_valid, test_parse_any_n, test_parse_invalid,
               test_bucket_minute_hour, test_trading_day, test_bucket_day_week,
               test_tick_trading_day_hint):
        fn()
    failed = [n for n, ok in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"  结果: {len(RESULTS) - len(failed)} 通过 / {len(failed)} 失败 / {len(RESULTS)} 总计")
    print("=" * 60)
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: 运行验证失败**

```bash
cd E:/AI/ckline && python tests/test_interval.py
```

Expected: 非零退出, `ModuleNotFoundError: No module named 'ctpbee_kline.interval'`(或类似 ImportError)。

- [ ] **Step 3: 实现 `ctpbee_kline/interval.py`**

```python
"""周期解析与时间分桶 — 纯标准库(ctpbee 的 Interval 枚举除外)。

语法: Nm(任意正整数分钟) / Nh(小时) / d(日线) / w(周线)
交易日规则(夜盘感知): >= 20:00 属次日开始计价的交易日; 其余(含凌晨
夜盘与日盘)属当日。tick 自带 trading_day 属性时优先。
"""
import re
from collections import namedtuple
from datetime import date, datetime, timedelta

from ctpbee.constant import Interval

IntervalSpec = namedtuple("IntervalSpec", ["value", "unit", "key", "enum"])

_INTERVAL_RE = re.compile(r"^(\d+)([mh])$")

# 夜盘分界时刻: 此时刻(含)之后的 tick 属于次日开始计价的交易日
_NIGHT_CUTOFF_HOUR = 20

# 规范 9 周期: 错误提示与 0.2 兼容导出用; 任意 N 分钟/小时同样受支持
_INTERVAL_META = {
    key: IntervalSpec(value, unit, key, enum_)
    for key, (value, unit, enum_) in {
        "1m":  (1,  "minute", Interval.MINUTE),
        "5m":  (5,  "minute", Interval.MINUTE),
        "15m": (15, "minute", Interval.MINUTE),
        "30m": (30, "minute", Interval.MINUTE),
        "1h":  (1,  "hour",   Interval.HOUR),
        "2h":  (2,  "hour",   Interval.HOUR),
        "4h":  (4,  "hour",   Interval.HOUR),
        "d":   (1,  "day",    Interval.DAILY),
        "w":   (1,  "week",   Interval.WEEKLY),
    }.items()
}


def parse_interval(spec):
    """解析周期串; 非法输入 ValueError(消息含语法说明)。"""
    if not isinstance(spec, str):
        raise ValueError(
            f"周期必须是字符串, 收到 {type(spec).__name__}: {spec!r}, "
            f"语法: Nm(分钟)/Nh(小时)/d(日线)/w(周线), 如 1m 5m 7m 3h")
    if spec in ("d", "w"):
        return _INTERVAL_META[spec]
    m = _INTERVAL_RE.match(spec)
    if m is None or int(m.group(1)) == 0:
        raise ValueError(
            f"不支持的K线周期: {spec!r}, "
            f"语法: Nm(分钟)/Nh(小时)/d(日线)/w(周线), 如 1m 5m 7m 3h")
    value = int(m.group(1))
    if m.group(2) == "m":
        return IntervalSpec(value, "minute", spec, Interval.MINUTE)
    return IntervalSpec(value, "hour", spec, Interval.HOUR)


def trading_day(dt):
    """tick 时间 -> 所属交易日。>=20:00 属次日; 其余属当日(凌晨夜盘归当日)。"""
    if dt.hour >= _NIGHT_CUTOFF_HOUR:
        return (dt + timedelta(days=1)).date()
    return dt.date()


def tick_trading_day(obj):
    """取数据对象自带 trading_day(预留上游扩展); 无或类型不符返回 None。"""
    td = getattr(obj, "trading_day", None)
    if isinstance(td, datetime):
        return td.date()
    if isinstance(td, date):
        return td
    return None


def bucket_start(dt, spec, td_hint=None):
    """将 dt 对齐到 spec 周期的起始时刻; td_hint 为已知交易日(d/w 用)。"""
    if spec.unit == "minute":
        bucket = dt.minute // spec.value * spec.value
        return dt.replace(minute=bucket, second=0, microsecond=0)
    if spec.unit == "hour":
        bucket = dt.hour // spec.value * spec.value
        return dt.replace(hour=bucket, minute=0, second=0, microsecond=0)
    td = td_hint or trading_day(dt)
    if spec.unit == "day":
        return datetime(td.year, td.month, td.day)
    monday = td - timedelta(days=td.weekday())
    return datetime(monday.year, monday.month, monday.day)
```

- [ ] **Step 4: 运行验证通过**

```bash
cd E:/AI/ckline && python tests/test_interval.py
```

Expected: 退出码 0, 形如 `52 通过 / 0 失败 / 52 总计`。

- [ ] **Step 5: 提交**

```bash
cd E:/AI/ckline && git add ctpbee_kline/interval.py tests/test_interval.py
git commit -m "feat(interval): any-N interval parsing, night-session trading day, bucketing

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `aggregator.py` — 聚合状态机 + emit 事件通道

**Files:**
- Create: `ctpbee_kline/aggregator.py`
- Test: `tests/test_aggregator.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_aggregator.py`:

```python
"""aggregator 套件: 聚合状态机 / emit 事件 / tick-bar 双路径等价 / 历史缓存。

运行: python tests/test_aggregator.py   (退出码 0 = 全部通过)
"""
import sys
from datetime import datetime, timedelta

from ctpbee.constant import BarData, Interval, TickData
from ctpbee.tool_register import register_tool_hook, unregister_tool_hook

from ctpbee_kline.aggregator import BAR_KEY, _Aggregator
from ctpbee_kline.interval import parse_interval

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(f"  {'✅' if cond else '❌'} {name}")


def make_tick(symbol, exchange, dt, last_price, volume):
    return TickData(symbol=symbol, exchange=exchange,
                    local_symbol=f"{symbol}.{exchange}",
                    datetime=dt, last_price=last_price, volume=volume)


def make_bar(symbol, exchange, dt, open_, high, low, close, volume):
    return BarData(symbol=symbol, exchange=exchange, datetime=dt,
                   interval=Interval.MINUTE, volume=volume,
                   open_price=open_, high_price=high,
                   low_price=low, close_price=close)


def ohlcv(bar):
    return (bar.open_price, bar.high_price, bar.low_price,
            bar.close_price, bar.volume)


def feed_ticks(agg, ticks, sink=None):
    """按 Kline 的调用契约喂 tick: 闭合(返回非 None)才 emit。"""
    for t in ticks:
        bar = agg.update_tick(t)
        if bar is not None:
            agg.emit(bar)
            if sink is not None:
                sink.append(bar)


def feed_bars(agg, bars, sink=None):
    for b in bars:
        closed = agg.update_bar(b)
        if closed is not None:
            agg.emit(closed)
            if sink is not None:
                sink.append(closed)


def test_1m_close_and_emit():
    print("── 1m OHLC/差分闭合 + emit 事件 ──")
    agg = _Aggregator(parse_interval("1m"))
    hook = []
    register_tool_hook(agg, BAR_KEY, hook.append)   # 只经 hook 收集, 避免双份
    base = datetime(2025, 1, 6, 14, 3, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 3200, 1000),
        make_tick("rb2505", "SHFE", base + timedelta(seconds=10), 3205, 1100),
        make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 3198, 1150),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1200),
    ])
    check("闭合恰好 1 根", len(hook) == 1)
    b = hook[0]
    check("O/H/L/C = 3200/3205/3198/3198", ohlcv(b)[:4] == (3200, 3205, 3198, 3198))
    check("V = 1150-1000 = 150", b.volume == 150)
    check("datetime = 14:03", b.datetime == base)
    check("interval 枚举为 MINUTE", b.interval == Interval.MINUTE)
    check("symbol/exchange 正确", (b.symbol, b.exchange) == ("rb2505", "SHFE"))
    check("历史缓存同步", len(agg.get_bars("rb2505.SHFE")) == 1)


def test_5m_consecutive():
    print("── 5m 连续两根 ──")
    agg = _Aggregator(parse_interval("5m"))
    closed = []
    base = datetime(2025, 1, 6, 14, 0, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 3200, 1000),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=2), 3210, 1050),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=4), 3195, 1100),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=5), 3205, 1150),
    ], closed)
    check("第一根 O=3200 H=3210 L=3195 C=3195 V=100",
          ohlcv(closed[0]) == (3200, 3210, 3195, 3195, 100))
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base + timedelta(minutes=6), 3215, 1200),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=9), 3200, 1250),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=10), 3190, 1300),
    ], closed)
    check("第二根 O=3205 H=3215 L=3200 C=3200",
          ohlcv(closed[1])[:4] == (3205, 3215, 3200, 3200))


def test_multi_symbol():
    print("── 多合约独立 ──")
    agg = _Aggregator(parse_interval("1m"))
    closed = []
    base = datetime(2025, 1, 6, 14, 0, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 3200, 1000),
        make_tick("i2509", "DCE", base, 800, 5000),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3220, 1100),
        make_tick("i2509", "DCE", base + timedelta(minutes=1), 815, 5200),
    ], closed)
    by_sym = {b.local_symbol: b for b in closed}
    check("两合约各闭合一根", set(by_sym) == {"rb2505.SHFE", "i2509.DCE"})
    check("rb2505 O=3200", by_sym["rb2505.SHFE"].open_price == 3200)
    check("i2509 O=800", by_sym["i2509.DCE"].open_price == 800)


def test_volume_reset():
    print("── 累计量重置 ──")
    agg = _Aggregator(parse_interval("1m"))
    closed = []
    base = datetime(2025, 1, 6, 14, 0, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 3200, 1000),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 50),  # 重置
    ], closed)
    check("重置跨分钟: V=0 (安全回退)", closed[0].volume == 0)

    agg2 = _Aggregator(parse_interval("1m"))
    closed2 = []
    feed_ticks(agg2, [
        make_tick("rb2505", "SHFE", base, 10.0, 1000),
        make_tick("rb2505", "SHFE", base + timedelta(seconds=10), 11.0, 50),   # 重置
        make_tick("rb2505", "SHFE", base + timedelta(seconds=20), 12.0, 60),   # 重置后新累计
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 13.0, 70),
    ], closed2)
    check("重置后新差分计入: V=10 (60-50)", closed2[0].volume == 10)
    check("重置后 close 正确", closed2[0].close_price == 12.0)


def test_out_of_order():
    print("── 乱序 tick 不闭合 ──")
    agg = _Aggregator(parse_interval("1m"))
    closed = []
    base = datetime(2025, 1, 6, 14, 5, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 100.0, 100),
        make_tick("rb2505", "SHFE", datetime(2025, 1, 6, 14, 2, 0), 90.0, 90),  # 乱序
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 95.0, 110),
    ], closed)
    check("乱序不产生额外闭合", len(closed) == 1)
    check("闭合 bar 取 14:05 桶: O=100 H=100 L=90 C=90",
          ohlcv(closed[0])[:4] == (100.0, 100.0, 90.0, 90.0))
    check("闭合 datetime = 14:05", closed[0].datetime == base)


def test_gap_jump():
    print("── tick 跳跃(中间缺 tick) ──")
    agg = _Aggregator(parse_interval("5m"))
    closed = []
    base = datetime(2025, 1, 6, 14, 0, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 3200, 1000),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=15), 3250, 1500),
    ], closed)
    check("跳跃只闭合 1 根 (O=C=3200)",
          len(closed) == 1 and ohlcv(closed[0])[:4] == (3200, 3200, 3200, 3200))


def test_bar_driven_5m():
    print("── bar 驱动: 1m bar 合成 5m ──")
    agg = _Aggregator(parse_interval("5m"))
    closed = []
    base = datetime(2025, 1, 6, 14, 0, 0)
    feed_bars(agg, [
        make_bar("rb2505", "SHFE", base, 3200, 3210, 3195, 3205, 100),
        make_bar("rb2505", "SHFE", base + timedelta(minutes=1), 3205, 3220, 3200, 3215, 150),
        make_bar("rb2505", "SHFE", base + timedelta(minutes=4), 3215, 3218, 3190, 3192, 80),
        make_bar("rb2505", "SHFE", base + timedelta(minutes=5), 3195, 3196, 3180, 3185, 60),
    ], closed)
    check("闭合 1 根 5m", len(closed) == 1)
    check("O=3200 H=3220 L=3190 C=3192 V=100+150+80=330",
          ohlcv(closed[0]) == (3200, 3220, 3190, 3192, 330))
    check("datetime = 14:00", closed[0].datetime == base)


def test_tick_bar_equivalence():
    print("── 双路径等价: 同序列两种喂法 → 相同 5m bar ──")
    base = datetime(2025, 1, 6, 14, 0, 0)
    ticks = [
        make_tick("rb2505", "SHFE", base, 3200, 1000),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=2), 3210, 1050),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=4), 3195, 1100),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=5), 3205, 1150),
    ]
    bars = [
        make_bar("rb2505", "SHFE", base, 3200, 3200, 3200, 3200, 0),
        make_bar("rb2505", "SHFE", base + timedelta(minutes=2), 3210, 3210, 3210, 3210, 50),
        make_bar("rb2505", "SHFE", base + timedelta(minutes=4), 3195, 3195, 3195, 3195, 50),
        make_bar("rb2505", "SHFE", base + timedelta(minutes=5), 3205, 3205, 3205, 3205, 50),
    ]
    via_ticks, via_bars = [], []
    feed_ticks(_Aggregator(parse_interval("5m")), ticks, via_ticks)
    feed_bars(_Aggregator(parse_interval("5m")), bars, via_bars)
    check("tick 路径闭合", len(via_ticks) == 1)
    check("bar 路径闭合", len(via_bars) == 1)
    check("OHLCV 完全一致", ohlcv(via_ticks[0]) == ohlcv(via_bars[0]))
    check("tick 路径 V=1100-1000=100", via_ticks[0].volume == 100)


def test_history_and_current():
    print("── 历史缓存与当前 bar 查询 ──")
    agg = _Aggregator(parse_interval("1m"), history=2)
    closed = []
    base = datetime(2025, 1, 6, 14, 0, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 10.0, 100),
        make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 11.0, 150),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 12.0, 200),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1, seconds=30), 13.0, 250),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=2), 14.0, 300),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=3), 15.0, 400),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=3, seconds=30), 16.0, 450),
    ], closed)
    check("闭合 3 根但缓存 maxlen=2", len(closed) == 3 and len(agg.get_bars("rb2505.SHFE")) == 2)
    check("V 序列 [50, 50, 0] (末根无同桶 tick)",
          [b.volume for b in closed] == [50, 50, 0])
    check("缓存淘汰最旧", [b.datetime.minute for b in agg.get_bars("rb2505.SHFE")] == [1, 2])
    check("get_bars(n=1) 取最新",
          agg.get_bars("rb2505.SHFE", n=1)[0].datetime.minute == 2)
    cur = agg.get_current("rb2505.SHFE")
    check("get_current: 14:03 桶 O=15 H=16 L=15 C=16 V=50",
          ohlcv(cur) == (15.0, 16.0, 15.0, 16.0, 50))
    check("未知合约 get_current=None", agg.get_current("ag2508.SHFE") is None)
    check("未知合约 get_bars=[]", agg.get_bars("ag2508.SHFE") == [])


def test_daily_night_session():
    print("── 日线夜盘感知 ──")
    agg = _Aggregator(parse_interval("d"))
    closed = []
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", datetime(2025, 1, 6, 21, 0), 4000.0, 100),  # 周一夜盘 → 交易日周二
        make_tick("rb2505", "SHFE", datetime(2025, 1, 7, 9, 0), 4010.0, 200),   # 周二日盘
        make_tick("rb2505", "SHFE", datetime(2025, 1, 7, 21, 30), 4005.0, 300), # 周二夜盘 → 交易日周三 → 闭合
    ], closed)
    check("周二交易日 bar 闭合", len(closed) == 1)
    check("datetime = 周二 00:00", closed[0].datetime == datetime(2025, 1, 7))
    check("O=4000 H=4010 L=4000 C=4010 V=100 (边界 tick 开新 bar)",
          ohlcv(closed[0]) == (4000.0, 4010.0, 4000.0, 4010.0, 100))


def test_weekly_anchor():
    print("── 周线锚定交易周 ──")
    agg = _Aggregator(parse_interval("w"))
    closed = []
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", datetime(2025, 1, 4, 0, 30), 500.0, 10),   # 周六凌晨 → 上交易周(跨年)
        make_tick("rb2505", "SHFE", datetime(2025, 1, 8, 10, 0), 510.0, 20),   # 周三 → 本周一 → 闭合上周
        make_tick("rb2505", "SHFE", datetime(2025, 1, 10, 22, 0), 505.0, 30),  # 周五夜盘 → 交易日周六, 仍属本周一
        make_tick("rb2505", "SHFE", datetime(2025, 1, 13, 9, 0), 515.0, 40),   # 下周一 → 闭合本周
    ], closed)
    check("闭合 2 根周线", len(closed) == 2)
    check("第一根锚定 2024-12-30 (跨年)",
          closed[0].datetime == datetime(2024, 12, 30))
    check("第二根锚定 2025-01-06",
          closed[1].datetime == datetime(2025, 1, 6))
    check("本周 O=510 H=510 L=505 C=505 V=10 (下周一 tick 开新 bar)",
          ohlcv(closed[1]) == (510.0, 510.0, 505.0, 505.0, 10))


def test_daily_ignores_bars():
    print("── d/w 聚合器对 bar 输入 no-op ──")
    agg = _Aggregator(parse_interval("d"))
    r = agg.update_bar(make_bar("rb2505", "SHFE",
                                datetime(2025, 1, 7, 14, 0), 1, 2, 0.5, 1.5, 99))
    check("update_bar 返回 None", r is None)
    check("状态未污染", agg.get_current("rb2505.SHFE") is None)


def test_emit_never_none_and_unsubscribe():
    print("── emit 事件契约 ──")
    agg = _Aggregator(parse_interval("1m"))
    seen = []
    register_tool_hook(agg, BAR_KEY, seen.append)
    base = datetime(2025, 1, 6, 14, 0, 0)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base, 10.0, 100),
        make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 11.0, 150),
        make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 12.0, 200),
    ])
    check("hook 恰好在闭合时收到 (1 次)", len(seen) == 1)
    check("收到的必是 BarData", isinstance(seen[0], BarData))
    unregister_tool_hook(agg, BAR_KEY, seen.append)
    feed_ticks(agg, [
        make_tick("rb2505", "SHFE", base + timedelta(minutes=2), 13.0, 300),
    ])
    check("退订后不再收到", len(seen) == 1)


def test_hook_exception_isolated():
    print("── hook 异常隔离(不进 tick 热路径) ──")
    agg = _Aggregator(parse_interval("1m"))
    good = []

    def boom(bar):
        raise RuntimeError("bad hook")

    register_tool_hook(agg, BAR_KEY, boom)      # 先注册坏回调(保序先执行)
    register_tool_hook(agg, BAR_KEY, good.append)
    base = datetime(2025, 1, 6, 14, 0, 0)
    try:
        feed_ticks(agg, [
            make_tick("rb2505", "SHFE", base, 10.0, 100),
            make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 11.0, 200),
        ])
        ok = True
    except Exception:
        ok = False
    check("坏 hook 不沿聚合链向上传播", ok)
    check("坏 hook 不影响后续回调", len(good) == 1)


if __name__ == "__main__":
    print("=" * 60)
    print("  ctpbee_kline aggregator 套件")
    print("=" * 60)
    for fn in (test_1m_close_and_emit, test_5m_consecutive, test_multi_symbol,
               test_volume_reset, test_out_of_order, test_gap_jump,
               test_bar_driven_5m, test_tick_bar_equivalence,
               test_history_and_current, test_daily_night_session,
               test_weekly_anchor, test_daily_ignores_bars,
               test_emit_never_none_and_unsubscribe,
               test_hook_exception_isolated):
        fn()
    failed = [n for n, ok in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"  结果: {len(RESULTS) - len(failed)} 通过 / {len(failed)} 失败 / {len(RESULTS)} 总计")
    print("=" * 60)
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: 运行验证失败**

```bash
cd E:/AI/ckline && python tests/test_aggregator.py
```

Expected: 非零退出, `ModuleNotFoundError: No module named 'ctpbee_kline.aggregator'`。

- [ ] **Step 3: 实现 `ctpbee_kline/aggregator.py`**

```python
"""每周期一个聚合器: tick/bar 双路径状态机 + 闭合 bar 事件通道。

分发完全复用 ctpbee.tool_register 原语: emit 是唯一被装饰的方法,
仅在闭合后被 Kline 调用, 订阅者每次必收到真 BarData, 永不收到 None。
通道键 BAR_KEY 是类级常量(装饰键在类定义时固化), 路由靠"每个聚合器
实例各自持有 _linked 回调表"实现 —— 不同实例互不串扰。
"""
from collections import deque

from ctpbee.constant import BarData
from ctpbee.tool_register import tool_register

from .interval import bucket_start, tick_trading_day

BAR_KEY = "bar"

# 每合约状态列表下标: [bucket, high, open, low, close, cum_volume, exchange]
_B, _H, _O, _L, _C, _V, _E = range(7)


class _Aggregator:
    """单周期聚合状态机; 由 Kline 持有, 一般不单独使用。"""

    def __init__(self, spec, history=4096):
        self.spec = spec
        self._bars = {}       # local_symbol -> 状态列表
        self._last_cum = {}   # local_symbol -> 最近 tick 累计量(仅 tick 路径)
        self._history = {}    # local_symbol -> deque(maxlen=history) 闭合 bar
        self._history_size = history

    # ── 闭合 bar 事件 ──

    @tool_register(BAR_KEY)
    def emit(self, bar):
        """闭合事件的唯一出口; Kline 在每次闭合后调用, 返回 bar 本身。"""
        return bar

    # ── tick 驱动(累计量差分) ──

    def update_tick(self, tick):
        """喂入 tick; 周期切换时返回闭合 bar, 否则 None。"""
        symbol = tick.local_symbol
        bucket = bucket_start(tick.datetime, self.spec, tick_trading_day(tick))
        price = tick.last_price
        state = self._bars.get(symbol)

        if state is None:
            self._bars[symbol] = [bucket, price, price, price, price,
                                  0.0, tick.exchange]
            self._last_cum[symbol] = tick.volume
            return None

        if bucket > state[_B]:
            # 周期切换: 先闭后开; 边界差分不计入(与 0.2 语义一致)
            bar = self._close(symbol)
            self._bars[symbol] = [bucket, price, price, price, price,
                                  0.0, tick.exchange]
            self._last_cum[symbol] = tick.volume
            return bar

        if bucket < state[_B]:
            # 乱序 tick: 不闭合, 就地更新当前 bar(0.2 会错误闭合一根陈旧 bar)
            self._merge(symbol, price, price, price, price, 0.0)
            return None

        last = self._last_cum.get(symbol, tick.volume)
        delta = tick.volume - last if tick.volume >= last else 0.0  # 重置守卫
        self._last_cum[symbol] = tick.volume
        self._merge(symbol, price, price, price, price, delta)
        return None

    # ── bar 驱动(区间量直接累加; d/w 聚合器 no-op) ──

    def update_bar(self, bar):
        """喂入低周期 bar(如 1m); 周期切换时返回闭合 bar, 否则 None。"""
        if self.spec.unit in ("day", "week"):
            return None
        symbol = bar.local_symbol
        bucket = bucket_start(bar.datetime, self.spec, tick_trading_day(bar))
        state = self._bars.get(symbol)

        if state is None:
            self._bars[symbol] = [bucket, bar.high_price, bar.open_price,
                                  bar.low_price, bar.close_price,
                                  float(bar.volume), bar.exchange]
            return None

        if bucket > state[_B]:
            closed = self._close(symbol)
            self._bars[symbol] = [bucket, bar.high_price, bar.open_price,
                                  bar.low_price, bar.close_price,
                                  float(bar.volume), bar.exchange]
            return closed

        # 同周期或乱序: 就地合并(open 保持首根, close 取最新)
        self._merge(symbol, bar.high_price, bar.open_price,
                    bar.low_price, bar.close_price, float(bar.volume))
        return None

    # ── 查询 ──

    def get_current(self, symbol):
        """未闭合 bar 快照; 无状态返回 None。"""
        s = self._bars.get(symbol)
        if s is None:
            return None
        return self._build_bar(symbol, s)

    def get_bars(self, symbol, n=None):
        """最近 n 根闭合 bar(默认全部); 返回列表副本。"""
        h = self._history.get(symbol)
        if h is None:
            return []
        return list(h)[-n:] if n is not None else list(h)

    # ── 内部 ──

    def _merge(self, symbol, high, _open, low, close, delta):
        s = self._bars[symbol]
        if high > s[_H]:
            s[_H] = high
        if low < s[_L]:
            s[_L] = low
        s[_C] = close
        s[_V] += delta

    def _close(self, symbol):
        s = self._bars[symbol]
        bar = self._build_bar(symbol, s)
        self._history.setdefault(
            symbol, deque(maxlen=self._history_size)).append(bar)
        return bar

    def _build_bar(self, symbol, s):
        return BarData(symbol=symbol.split(".")[0], exchange=s[_E],
                       interval=self.spec.enum, datetime=s[_B], volume=s[_V],
                       open_price=s[_O], high_price=s[_H],
                       low_price=s[_L], close_price=s[_C])
```

- [ ] **Step 4: 运行验证通过**

```bash
cd E:/AI/ckline && python tests/test_aggregator.py
```

Expected: 退出码 0, 形如 `42 通过 / 0 失败 / 42 总计`。

- [ ] **Step 5: 提交**

```bash
cd E:/AI/ckline && git add ctpbee_kline/aggregator.py tests/test_aggregator.py
git commit -m "feat(aggregator): dual-path aggregation state machine with tool_register emit channel

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `__init__.py` — 公开 `Kline(Tool)`

**Files:**
- Modify(重写): `ctpbee_kline/__init__.py`
- Test: `tests/test_kline_tool.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_kline_tool.py`:

```python
"""Kline(Tool) 套件: FakeApp 下的自动接线 / 分发 / 显式订阅 / 0.2 兼容。

运行: python tests/test_kline_tool.py   (退出码 0 = 全部通过)
"""
import sys
from datetime import datetime, timedelta

from ctpbee import CtpbeeApi
from ctpbee.constant import BarData, Interval, TickData, ToolRegisterType

from ctpbee_kline import Kline

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(f"  {'✅' if cond else '❌'} {name}")


def raises_ve(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


class FakeApp:
    """只提供 Kline 依赖的两个属性: tools / _extensions。"""

    def __init__(self):
        self.tools = {}
        self._extensions = {}

    def with_tools(self, *args):
        for i in args:
            i.init_app(self)
        return self


class FakeStrategy(CtpbeeApi):
    def __init__(self, name):
        super().__init__(name)
        self.bars = []

    def on_bar(self, bar):
        self.bars.append(bar)


def make_tick(symbol, exchange, dt, last_price, volume):
    return TickData(symbol=symbol, exchange=exchange,
                    local_symbol=f"{symbol}.{exchange}",
                    datetime=dt, last_price=last_price, volume=volume)


def make_bar(symbol, exchange, dt, open_, high, low, close, volume):
    return BarData(symbol=symbol, exchange=exchange, datetime=dt,
                   interval=Interval.MINUTE, volume=volume,
                   open_price=open_, high_price=high,
                   low_price=low, close_price=close)


def test_compat_and_names():
    print("── 0.2 兼容与命名 ──")
    check("Kline() 默认 1m 且名 kline_1m", Kline().name == "kline_1m")
    check("Kline(\"5m\") 名 kline_5m", Kline("5m").name == "kline_5m")
    check("Kline([\"5m\"]) 单元素列表同名", Kline(["5m"]).name == "kline_5m")
    check("Kline([\"5m\",\"1h\"]) 名 kline", Kline(["5m", "1h"]).name == "kline")
    check("name 参数覆盖", Kline("5m", name="kk").name == "kk")
    check("Kline([]) 拒绝", raises_ve(lambda: Kline([])))
    check("Kline(\"3x\") 拒绝", raises_ve(lambda: Kline("3x")))
    check("重复周期去重", len(Kline(["5m", "5m"])._aggs) == 1)


def test_auto_wire_before_and_after():
    print("── 自动接线: 先注册与后注册策略都收到 bar ──")
    app = FakeApp()
    early = FakeStrategy("early")
    app._extensions["early"] = early
    k = Kline("1m")
    app.with_tools(k)                       # init_app → 接线 early
    late = FakeStrategy("late")
    app._extensions["late"] = late          # 首 tick 之后才注册 (0.2 会漏掉)
    base = datetime(2025, 1, 6, 14, 0, 0)
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 3205, 1100))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1200))
    check("先注册策略收到闭合 bar", len(early.bars) == 1)
    check("后注册策略也收到 (0.2 bug 修复)", len(late.bars) == 1)
    check("bar 数据正确", early.bars[0].close_price == 3205
          and early.bars[0].volume == 100)
    check("工具已注册进 app.tools", app.tools.get("kline_1m") is k)


def test_multi_interval_fanout():
    print("── 多周期扇出 ──")
    k = Kline(["1m", "5m"])
    got_1m, got_5m = [], []
    k.subscribe("1m", got_1m.append)
    k.subscribe("5m", got_5m.append)
    base = datetime(2025, 1, 6, 14, 0, 0)
    for minute in range(6):  # 14:00 ~ 14:05
        k.on_tick(make_tick("rb2505", "SHFE",
                            base + timedelta(minutes=minute),
                            3200 + minute, 1000 + 10 * minute))
    check("1m 闭合 5 根", len(got_1m) == 5)
    check("5m 闭合 1 根", len(got_5m) == 1)
    check("5m bar O=3200 C=3204", (got_5m[0].open_price, got_5m[0].close_price)
          == (3200, 3204))
    check("订阅未知周期报错",
          raises_ve(lambda: k.subscribe("15m", lambda b: None)))


def test_subscribe_filter_and_unsubscribe():
    print("── 显式订阅: 合约过滤与退订 ──")
    k = Kline("1m")
    rb_bars, both = [], []
    k.subscribe("1m", rb_bars.append, symbols={"rb2505.SHFE"})
    k.subscribe("1m", both.append)
    base = datetime(2025, 1, 6, 14, 0, 0)
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("i2509", "DCE", base, 800, 5000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1100))
    k.on_tick(make_tick("i2509", "DCE", base + timedelta(minutes=1), 810, 5100))
    check("过滤订阅只收 rb", len(rb_bars) == 1
          and rb_bars[0].local_symbol == "rb2505.SHFE")
    check("无过滤订阅两合约都收", len(both) == 2)
    k.unsubscribe("1m", rb_bars.append)
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=2), 3220, 1200))
    check("退订后不再收到", len(rb_bars) == 1)
    check("另一订阅不受影响", len(both) == 3)


def test_bar_driven_tool():
    print("── bar 驱动 (on_bar 路径) ──")
    k = Kline("5m")
    bars = []
    k.subscribe("5m", bars.append)
    base = datetime(2025, 1, 6, 14, 0, 0)
    k.on_bar(make_bar("rb2505", "SHFE", base, 3200, 3210, 3195, 3205, 100))
    k.on_bar(make_bar("rb2505", "SHFE", base + timedelta(minutes=1),
                      3205, 3220, 3200, 3215, 150))
    k.on_bar(make_bar("rb2505", "SHFE", base + timedelta(minutes=4),
                      3215, 3218, 3190, 3192, 80))
    k.on_bar(make_bar("rb2505", "SHFE", base + timedelta(minutes=5),
                      3195, 3196, 3180, 3185, 60))
    check("5m bar 闭合", len(bars) == 1)
    check("O/H/L/C/V 正确", (bars[0].open_price, bars[0].high_price,
                             bars[0].low_price, bars[0].close_price,
                             bars[0].volume) == (3200, 3220, 3190, 3192, 330))


def test_auto_wire_off():
    print("── auto_wire=False ──")
    app = FakeApp()
    s = FakeStrategy("s")
    app._extensions["s"] = s
    k = Kline("1m", auto_wire=False)
    app.with_tools(k)
    base = datetime(2025, 1, 6, 14, 0, 0)
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1100))
    check("自动接线关闭: 策略不收 bar", len(s.bars) == 0)
    got = []
    k.subscribe("1m", got.append)
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=2), 3220, 1200))
    check("显式订阅仍工作", len(got) == 1)


def test_queries():
    print("── Kline 级查询 ──")
    k = Kline(["1m", "5m"])
    base = datetime(2025, 1, 6, 14, 0, 0)
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 3205, 1100))
    cur = k.get_current("rb2505.SHFE", interval="1m")
    check("多周期 get_current(interval=...)",
          (cur.open_price, cur.close_price, cur.volume) == (3200, 3205, 100))
    check("多周期缺 interval 报错",
          raises_ve(lambda: k.get_current("rb2505.SHFE")))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1200))
    check("get_bars(interval=...)", len(k.get_bars("rb2505.SHFE", interval="1m")) == 1)
    k2 = Kline("1m")
    k2.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k2.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1100))
    check("单周期 get_current 免 interval",
          k2.get_current("rb2505.SHFE").datetime == base + timedelta(minutes=1))
    check("单周期 get_bars(n=1)",
          len(k2.get_bars("rb2505.SHFE", n=1)) == 1)


def test_framework_tick_channel():
    print("── 框架 TICK 通道集成 ──")
    k = Kline("1m")
    seen = []
    k.add_func(seen.append, ToolRegisterType.TICK)
    base = datetime(2025, 1, 6, 14, 0, 0)
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    check("TICK 通道收到 on_tick 返回值(None)",
          len(seen) == 1 and seen[0] is None)


def test_emit_only_closed_to_strategy():
    print("── 策略只收闭合 bar ──")
    app = FakeApp()
    s = FakeStrategy("s")
    app._extensions["s"] = s
    k = Kline("1m")
    app.with_tools(k)
    base = datetime(2025, 1, 6, 14, 0, 0)
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 3205, 1100))
    check("同分钟内不推送", len(s.bars) == 0)
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1200))
    check("跨分钟推送 1 根", len(s.bars) == 1
          and s.bars[0].volume == 100)


if __name__ == "__main__":
    print("=" * 60)
    print("  ctpbee_kline Kline(Tool) 套件")
    print("=" * 60)
    for fn in (test_compat_and_names, test_auto_wire_before_and_after,
               test_multi_interval_fanout, test_subscribe_filter_and_unsubscribe,
               test_bar_driven_tool, test_auto_wire_off, test_queries,
               test_framework_tick_channel, test_emit_only_closed_to_strategy):
        fn()
    failed = [n for n, ok in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"  结果: {len(RESULTS) - len(failed)} 通过 / {len(failed)} 失败 / {len(RESULTS)} 总计")
    print("=" * 60)
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: 运行验证失败**

```bash
cd E:/AI/ckline && python tests/test_kline_tool.py
```

Expected: 非零退出, 多项 ❌(旧 `Kline` 无多周期/显式订阅/查询; 若 `Kline(["1m","5m"])` 直接抛 TypeError/ValueError 则为异常计数)。

- [ ] **Step 3: 重写 `ctpbee_kline/__init__.py`**

```python
"""ctpbee K线工具 v1.0 — 多周期实时生成(tick/bar 双驱动, 夜盘交易日感知)。

用法:
  from ctpbee_kline import Kline
  kline = Kline("5m")                  # 单周期(0.2 兼容)
  kline = Kline(["1m", "5m", "1h"])    # 单实例多周期
  app = CtpBee(...).with_tools(kline)  # 策略 on_bar 自动接收闭合 bar

显式订阅(可选, 与自动分发并存):
  kline.subscribe("5m", my_func, symbols={"rb2505.SHFE"})
"""
from ctpbee import Tool
from ctpbee.constant import ToolRegisterType

# tool_register 独立原语(ctpbee>=1.8, 见 ctpbee/tool_register.py)
from ctpbee.tool_register import register_tool_hook, tool_register, \
    unregister_tool_hook

from .aggregator import BAR_KEY, _Aggregator
from .interval import _INTERVAL_META, parse_interval

__all__ = ["Kline", "_INTERVAL_META"]


class Kline(Tool):
    """多周期 K 线实时生成工具。"""

    def __init__(self, intervals="1m", *, history=4096, auto_wire=True,
                 name=None):
        """
        Args:
            intervals: 周期 str 或 str 列表, 语法 Nm/Nh/d/w(如 "7m", "3h")
            history:   每合约每周期闭合 bar 缓存深度
            auto_wire: True 时策略 on_bar 自动接线(含后续注册的策略)
            name:      工具名; 缺省单周期 kline_{interval}, 多周期 "kline"
        """
        if isinstance(intervals, str):
            intervals = [intervals]
        intervals = list(intervals)
        if not intervals:
            raise ValueError(
                "至少需要一个K线周期, 如 Kline(\"5m\") 或 Kline([\"1m\", \"5m\"])")
        default_name = f"kline_{intervals[0]}" if len(intervals) == 1 else "kline"

        aggs = {}  # 去重保序
        for s in intervals:
            spec = parse_interval(s)
            aggs.setdefault(spec.key, _Aggregator(spec, history))

        self._aggs = aggs
        self._auto_wire = auto_wire
        self._wired = set()     # 已接线策略 id
        self._ext_count = -1    # 上次同步时的策略数(每 tick 一次整数比较)
        self._sub_book = {}     # (interval_key, 原函数) -> symbols 过滤闭包
        super().__init__(name or default_name)

    # ── 框架回调 ──

    @tool_register(ToolRegisterType.TICK)
    def on_tick(self, tick):
        """Recorder 每 tick 调用; 闭合 bar 经各聚合器 emit 推给订阅者。"""
        if self._auto_wire and self.app is not None:
            self._sync_wire()
        for agg in self._aggs.values():
            bar = agg.update_tick(tick)
            if bar is not None:
                agg.emit(bar)

    @tool_register(ToolRegisterType.BAR)
    def on_bar(self, bar):
        """Recorder 的 bar 事件(如 1m bar)驱动分钟/小时族聚合器。"""
        for agg in self._aggs.values():
            closed = agg.update_bar(bar)
            if closed is not None:
                agg.emit(closed)

    # ── 接线与订阅 ──

    def init_app(self, app):
        super().init_app(app)
        if self._auto_wire:
            self._sync_wire()

    def _sync_wire(self):
        """给尚未接线的策略 on_bar 注册到各聚合器(0.2 首 tick hack 的修复)。"""
        exts = self.app._extensions
        if len(exts) == self._ext_count:
            return
        self._ext_count = len(exts)
        for ext in exts.values():
            if id(ext) in self._wired:
                continue
            self._wired.add(id(ext))
            on_bar = getattr(ext, "on_bar", None)
            if callable(on_bar):
                for agg in self._aggs.values():
                    register_tool_hook(agg, BAR_KEY, on_bar)

    def subscribe(self, interval, func, symbols=None):
        """显式订阅周期闭合 bar; symbols 给定时按 bar.local_symbol 过滤。"""
        agg = self._require_agg(interval)
        if symbols is None:
            register_tool_hook(agg, BAR_KEY, func)
            return
        allow = set(symbols)

        def filtered(bar, _func=func, _allow=allow):
            if bar.local_symbol in _allow:
                _func(bar)

        self._sub_book[(interval, func)] = filtered
        register_tool_hook(agg, BAR_KEY, filtered)

    def unsubscribe(self, interval, func):
        """退订(与 subscribe 对称; symbols 过滤订阅传原函数即可)。"""
        agg = self._require_agg(interval)
        wrapped = self._sub_book.pop((interval, func), func)
        unregister_tool_hook(agg, BAR_KEY, wrapped)

    def _require_agg(self, interval):
        agg = self._aggs.get(interval)
        if agg is None:
            raise ValueError(
                f"此Kline未启用周期 {interval!r}, 启用的周期: {list(self._aggs)}")
        return agg

    # ── 查询 ──

    def _agg_for(self, interval):
        if interval is None:
            if len(self._aggs) == 1:
                return next(iter(self._aggs.values()))
            raise ValueError(
                f"多周期实例必须指定 interval, 可选: {list(self._aggs)}")
        return self._require_agg(interval)

    def get_current(self, symbol, interval=None):
        """未闭合 bar 快照(多周期实例需指定 interval)。"""
        return self._agg_for(interval).get_current(symbol)

    def get_bars(self, symbol, n=None, interval=None):
        """最近 n 根闭合 bar(默认全部)。"""
        return self._agg_for(interval).get_bars(symbol, n)
```

- [ ] **Step 4: 运行验证通过**

```bash
cd E:/AI/ckline && python tests/test_kline_tool.py
```

Expected: 退出码 0, 形如 `34 通过 / 0 失败 / 34 总计`。

- [ ] **Step 5: 提交**

```bash
cd E:/AI/ckline && git add ctpbee_kline/__init__.py tests/test_kline_tool.py
git commit -m "feat(kline): multi-interval Tool on standalone tool_register, fixed auto-wiring, explicit subscribe

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 移除旧套件 + 全量回归

**Files:**
- Delete: `tests/test_kline.py`(用例已全部迁移/升级进三个新套件)

- [ ] **Step 1: 确认旧用例已迁移**

对照清单(旧 `tests/test_kline.py` → 新去处):
- 时间分桶 test_bucket → `test_interval.py::test_bucket_minute_hour` + `test_bucket_day_week`
- 1m/5m/1h K线 → `test_aggregator.py::test_1m_close_and_emit` / `test_5m_consecutive` / (`1h` 并入 `test_bucket_minute_hour` 的分桶 + 聚合机制本身与周期无关)
- 多合约/成交量重置/tick跳跃 → `test_multi_symbol` / `test_volume_reset` / `test_gap_jump`
- 参数校验/多实例 → `test_kline_tool.py::test_compat_and_names`

- [ ] **Step 2: 删除旧套件**

```bash
cd E:/AI/ckline && git rm tests/test_kline.py
```

- [ ] **Step 3: 全量回归(三个套件 + 上游 7 套件)**

```bash
cd E:/AI/ckline && python tests/test_interval.py && python tests/test_aggregator.py && python tests/test_kline_tool.py
cd E:/AI/ctpbee && for t in tests/test_hotpath_optimization.py tests/test_position_hotpath.py tests/test_dispatcher.py tests/test_tool_register.py tests/test_config_env.py tests/test_upper_layers.py tests/test_examples_strategies.py; do python $t || break; done
```

Expected: ckline 三个套件各自退出码 0; ctpbee 7 套件全绿(129 checks)——确认 v1.0 未破坏上游。

- [ ] **Step 4: 提交**

```bash
cd E:/AI/ckline && git add -A && git commit -m "test: replace 0.2 suite with interval/aggregator/tool suites (cases migrated)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 打包与文档(1.0.0)

**Files:**
- Modify: `setup.py`
- Rewrite: `README.MD`

- [ ] **Step 1: 更新 `setup.py`**

整文件替换为:

```python
from setuptools import find_packages, setup

setup(
    name="ctpbee_kline",
    version="1.0.0",
    description="ctpbee 多周期K线生成工具 (tick/bar 双驱动, 夜盘交易日感知)",
    author="somewheve",
    author_email="somewheve@gmail.com",
    url="https://www.github.com/ctpbee/ckline",
    install_requires=["ctpbee>=1.8"],
    python_requires=">=3.9",
    packages=find_packages(exclude=["tests", "tests.*"]),
)
```

- [ ] **Step 2: 重写 `README.MD`**

整文件替换为:

```markdown
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
```

- [ ] **Step 3: 验证打包元数据 + 全量回归**

```bash
cd E:/AI/ckline && python setup.py --version && python -c "import ctpbee_kline as m; print(m.Kline, m._INTERVAL_META.keys())"
```

Expected: `1.0.0`; 导出正常。

```bash
cd E:/AI/ckline && python tests/test_interval.py && python tests/test_aggregator.py && python tests/test_kline_tool.py
```

Expected: 三个退出码 0。

- [ ] **Step 4: 提交**

```bash
cd E:/AI/ckline && git add setup.py README.MD
git commit -m "chore: release 1.0.0 — pin ctpbee>=1.8, rewrite docs for new APIs

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 完成标准

- [ ] 三个新套件全绿(interval / aggregator / tool), 退出码 0
- [ ] ctpbee 上游 7 套件仍全绿(129 checks)
- [ ] `Kline("5m")` 旧写法行为不变(名字、默认自动分发、on_bar 收闭合 bar)
- [ ] 后注册策略能收到 bar(0.2 核心 bug 修复)
- [ ] `setup.py` 版本 1.0.0, `ctpbee>=1.8`, `python_requires>=3.9`
- [ ] PyPI **未**发布(范围外)
```
