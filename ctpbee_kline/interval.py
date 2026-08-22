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
