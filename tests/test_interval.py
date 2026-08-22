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
