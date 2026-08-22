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
