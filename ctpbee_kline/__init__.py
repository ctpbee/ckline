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
