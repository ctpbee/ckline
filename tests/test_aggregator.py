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
