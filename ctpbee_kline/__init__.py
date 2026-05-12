"""
ctpbee K线工具 — 支持多周期K线实时生成

支持的周期:
  1m / 5m / 15m / 30m  — 分钟线
  1h / 2h / 4h          — 小时线
  d                     — 日线
  w                     — 周线

使用方式:
  from ctpbee_kline import Kline
  kline = Kline("5m")           # 5分钟K线
  kline = Kline("1h")           # 1小时K线
  kline = Kline("d")            # 日线
  app = CtpBee(...).with_tools(kline)
"""

from datetime import timedelta
from ctpbee import Tool
from ctpbee.constant import ToolRegisterType, TickData, Interval, BarData
from ctpbee.level import tool_register


# ── 支持的周期及其元数据 ──
_INTERVAL_META = {
    "1m":  (1,     "minute",   Interval.MINUTE),
    "5m":  (5,     "minute",   Interval.MINUTE),
    "15m": (15,    "minute",   Interval.MINUTE),
    "30m": (30,    "minute",   Interval.MINUTE),
    "1h":  (1,     "hour",     Interval.HOUR),
    "2h":  (2,     "hour",     Interval.HOUR),
    "4h":  (4,     "hour",     Interval.HOUR),
    "d":   (1,     "day",      Interval.DAILY),
    "w":   (1,     "week",     Interval.WEEKLY),
}


class Kline(Tool):
    """
    多周期 K 线实时生成工具

    以 tick 驱动——每个 tick 到来时更新当前 K 线。
    当时钟跨越到下一个周期时，闭合上一根 K 线并通过回调推送给所有订阅策略。
    """

    def __init__(self, interval: str = "1m"):
        """
        Args:
            interval: K线周期，支持 "1m" "5m" "15m" "30m" "1h" "2h" "4h" "d" "w"
        """
        super().__init__(f"kline_{interval}")

        meta = _INTERVAL_META.get(interval)
        if meta is None:
            raise ValueError(
                f"不支持的K线周期: {interval}，可选: {', '.join(_INTERVAL_META.keys())}"
            )

        self._interval_value, self._interval_unit, self._interval_enum = meta
        self._interval_str = interval

        # 每个合约的当前 bar 状态: { local_symbol: [bar_start_dt, high, open, low, close, vol_start, vol_latest] }
        self._bars: dict[str, list] = {}
        self._init = False

    # ── 时间分桶 ──

    def _bucket(self, dt):
        """
        将 datetime 对齐到当前周期的起始时间。

        例如 5m 周期: 14:03:27 → 14:00:00
             1h 周期: 14:45:00 → 14:00:00
        """
        if self._interval_unit == "minute":
            bucket = dt.minute // self._interval_value * self._interval_value
            return dt.replace(minute=bucket, second=0, microsecond=0)
        elif self._interval_unit == "hour":
            bucket = dt.hour // self._interval_value * self._interval_value
            return dt.replace(hour=bucket, minute=0, second=0, microsecond=0)
        elif self._interval_unit == "day":
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif self._interval_unit == "week":
            # 周一为 0
            weekday = dt.weekday()
            return (dt - timedelta(days=weekday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        return dt

    # ── Tick 驱动 ──

    @tool_register(ToolRegisterType.TICK)
    def on_tick(self, tick: TickData):
        """
        每个 tick 到来时调用。

        返回:
            BarData | None  — 当周期切换时返回上一根已完成 K 线，否则返回 None。
                             返回值由 ctpbee 框架自动分发给所有已订阅策略的 on_bar 方法。
        """
        # 首次 tick: 向所有已注册策略订阅 on_bar 回调
        if not self._init:
            if self.app is not None:
                for strategy in self.app._extensions.values():
                    self.app.tools[self.name].add_func(
                        func=strategy.on_bar, r_type=ToolRegisterType.TICK
                    )
            self._init = True

        symbol = tick.local_symbol
        bucket = self._bucket(tick.datetime)
        price = tick.last_price
        volume = tick.volume

        current = self._bars.get(symbol)

        if current is None:
            # 第一条 tick: 初始化新 bar
            self._bars[symbol] = [bucket, price, price, price, price, volume, volume]
            return None

        current_bucket = current[0]

        if bucket != current_bucket:
            # ── 周期切换: 闭合上一根 bar ──
            bar_volume = (
                current[6] - current[5] if current[6] >= current[5] else 0
            )
            bar = BarData(
                symbol=tick.symbol,
                exchange=tick.exchange,
                interval=self._interval_enum,
                datetime=current_bucket,
                volume=bar_volume,
                open_price=current[2],
                high_price=current[1],
                low_price=current[3],
                close_price=current[4],
            )
            # 开启新 bar
            self._bars[symbol] = [bucket, price, price, price, price, volume, volume]
            return bar
        else:
            # ── 同一周期: 更新 OHLC ──
            if price > current[1]:
                current[1] = price  # high
            if price < current[3]:
                current[3] = price  # low
            current[4] = price   # close
            current[6] = volume  # latest volume (for bar_volume on close)
            return None
