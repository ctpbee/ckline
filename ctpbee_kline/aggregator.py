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
