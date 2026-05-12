"""
ctpbee_kline 测试脚本

验证多周期 K 线生成逻辑的正确性:
  - 时间分桶 (_bucket)
  - OHLC 更新
  - 周期切换
  - 成交量计算
  - 边界情况
"""

from datetime import datetime, timedelta
from ctpbee_kline import Kline, _INTERVAL_META


# ── 辅助函数: 构造模拟 Tick ──

_tick_id = 0


def make_tick(symbol: str, exchange: str, dt: datetime,
              last_price: float, volume: float, **kwargs):
    """构造一个模拟 TickData 对象"""
    global _tick_id
    _tick_id += 1
    from ctpbee.constant import TickData
    t = TickData(
        symbol=symbol,
        exchange=exchange,
        local_symbol=f"{symbol}.{exchange}",
        datetime=dt,
        last_price=last_price,
        volume=volume,
        open_price=kwargs.get("open_price", last_price),
        high_price=kwargs.get("high_price", last_price),
        low_price=kwargs.get("low_price", last_price),
        pre_settlement_price=kwargs.get("pre_settlement_price", last_price),
        bid_price_1=kwargs.get("bid_price_1", 0),
        ask_price_1=kwargs.get("ask_price_1", 0),
        open_interest=kwargs.get("open_interest", 0),
    )
    return t


# ═══════════════════════════════════════════════════════════════════
# 测试 1: _bucket 时间分桶
# ═══════════════════════════════════════════════════════════════════

def test_bucket():
    print("── 测试: 时间分桶 _bucket ──")

    base = datetime(2025, 1, 6, 14, 3, 27)  # 周一

    tests = [
        ("1m",  base, datetime(2025, 1, 6, 14, 3, 0)),
        ("5m",  base, datetime(2025, 1, 6, 14, 0, 0)),
        ("15m", base, datetime(2025, 1, 6, 14, 0, 0)),
        ("30m", base, datetime(2025, 1, 6, 14, 0, 0)),
        ("1h",  base, datetime(2025, 1, 6, 14, 0, 0)),
        ("2h",  base, datetime(2025, 1, 6, 14, 0, 0)),
        ("4h",  base, datetime(2025, 1, 6, 12, 0, 0)),
        ("d",   base, datetime(2025, 1, 6, 0, 0, 0)),
        ("w",   base, datetime(2025, 1, 6, 0, 0, 0)),  # 周一
    ]

    all_ok = True
    for interval, dt, expected in tests:
        k = Kline(interval)
        result = k._bucket(dt)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_ok = False
        print(f"  {status} {interval}: {dt.time()} → {result.time()}  (期望 {expected.time()})")

    # 周线测试: 周三应该归到周一
    wed = datetime(2025, 1, 8, 14, 30, 0)
    k = Kline("w")
    result = k._bucket(wed)
    expected = datetime(2025, 1, 6, 0, 0, 0)
    status = "✅" if result == expected else "❌"
    if result != expected:
        all_ok = False
    print(f"  {status} w (周三): {wed} → {result}  (期望 {expected})")

    # 跨小时边界: 14:59 → 14:00, 15:00 → 15:00
    boundary = datetime(2025, 1, 6, 15, 0, 0)
    k2 = Kline("1h")
    result = k2._bucket(boundary)
    expected = datetime(2025, 1, 6, 15, 0, 0)
    status = "✅" if result == expected else "❌"
    if result != expected:
        all_ok = False
    print(f"  {status} 1h 边界: {boundary.time()} → {result.time()}  (期望 {expected.time()})")

    return all_ok


# ═══════════════════════════════════════════════════════════════════
# 测试 2: 1 分钟 K 线生成
# ═══════════════════════════════════════════════════════════════════

def test_1m_bar():
    print("\n── 测试: 1分钟K线生成 ──")

    k = Kline("1m")
    sym = "rb2505.SHFE"
    base = datetime(2025, 1, 6, 14, 3, 0)

    # Tick 1: 14:03:00, price=3200, vol=1000
    t1 = make_tick("rb2505", "SHFE", base, 3200, 1000)
    r1 = k.on_tick(t1)
    assert r1 is None, "第一条 tick 应返回 None (初始化)"

    # Tick 2: 同一分钟, price=3205, vol=1100
    t2 = make_tick("rb2505", "SHFE", base + timedelta(seconds=10), 3205, 1100)
    r2 = k.on_tick(t2)
    assert r2 is None, "同一分钟应返回 None"

    # Tick 3: 同一分钟, price=3198 (新低), vol=1150
    t3 = make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 3198, 1150)
    r3 = k.on_tick(t3)
    assert r3 is None, "同一分钟应返回 None"

    # Tick 4: 下一分钟 14:04:00, price=3210, vol=1200
    t4 = make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 1200)
    r4 = k.on_tick(t4)
    assert r4 is not None, "跨分钟应返回 BarData"

    # 验证 bar 数据
    assert r4.symbol == "rb2505", f"symbol 应为 rb2505, 实际 {r4.symbol}"
    assert r4.open_price == 3200, f"open 应为 3200, 实际 {r4.open_price}"
    assert r4.high_price == 3205, f"high 应为 3205, 实际 {r4.high_price}"
    assert r4.low_price == 3198, f"low 应为 3198, 实际 {r4.low_price}"
    assert r4.close_price == 3198, f"close 应为 3198 (最后 tick), 实际 {r4.close_price}"
    assert r4.volume == 150, f"volume 应为 1150-1000=150, 实际 {r4.volume}"
    assert r4.datetime == base, f"datetime 应为 {base}, 实际 {r4.datetime}"

    print("  ✅ OHLC: O=3200 H=3205 L=3198 C=3198")
    print("  ✅ Volume: 150")
    print("  ✅ Datetime: 14:03")

    return True


# ═══════════════════════════════════════════════════════════════════
# 测试 3: 5 分钟 K 线
# ═══════════════════════════════════════════════════════════════════

def test_5m_bar():
    print("\n── 测试: 5分钟K线生成 ──")

    k = Kline("5m")
    base = datetime(2025, 1, 6, 14, 0, 0)

    # 14:00-14:04 的 ticks
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=2), 3210, 1050))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=4), 3195, 1100))

    # 14:05 — 跨周期
    r = k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=5), 3205, 1150))

    assert r is not None, "跨5分钟应返回 BarData"
    assert r.open_price == 3200, f"open 应为 3200, 实际 {r.open_price}"
    assert r.high_price == 3210, f"high 应为 3210, 实际 {r.high_price}"
    assert r.low_price == 3195, f"low 应为 3195, 实际 {r.low_price}"
    assert r.close_price == 3195, f"close 应为 3195, 实际 {r.close_price}"
    assert r.volume == 100, f"volume 应为 1100-1000=100, 实际 {r.volume}"
    assert r.datetime == base, f"datetime 应为 14:00"

    print("  ✅ 5m bar 正确闭合: O=3200 H=3210 L=3195 C=3195 V=100")

    # 14:05-14:09 的 ticks
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=6), 3215, 1200))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=9), 3200, 1250))

    # 14:10 — 跨周期
    r2 = k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=10), 3190, 1300))

    assert r2 is not None
    assert r2.open_price == 3205, f"open 应为 3205, 实际 {r2.open_price}"
    assert r2.high_price == 3215, f"high 应为 3215, 实际 {r2.high_price}"
    assert r2.low_price == 3200, f"low 应为 3200, 实际 {r2.low_price}"
    assert r2.close_price == 3200, f"close 应为 3200, 实际 {r2.close_price}"

    print("  ✅ 第二根 5m bar: O=3205 H=3215 L=3200 C=3200")

    return True


# ═══════════════════════════════════════════════════════════════════
# 测试 4: 多合约独立 bar
# ═══════════════════════════════════════════════════════════════════

def test_multi_symbol():
    print("\n── 测试: 多合约独立K线 ──")

    k = Kline("1m")
    base = datetime(2025, 1, 6, 14, 0, 0)

    # rb2505 的 tick
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(seconds=30), 3210, 1050))

    # i2509 的 tick (不同合约)
    k.on_tick(make_tick("i2509", "DCE", base, 800, 5000))
    k.on_tick(make_tick("i2509", "DCE", base + timedelta(seconds=30), 810, 5100))

    # rb2505 跨分钟
    r_rb = k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3220, 1100))
    assert r_rb is not None and r_rb.symbol == "rb2505", "rb2505 应闭合"
    assert r_rb.open_price == 3200

    # i2509 跨分钟
    r_i = k.on_tick(make_tick("i2509", "DCE", base + timedelta(minutes=1), 815, 5200))
    assert r_i is not None and r_i.symbol == "i2509", "i2509 应闭合"
    assert r_i.open_price == 800

    print("  ✅ rb2505 和 i2509 的 bar 各自独立")
    print("  ✅ rb2505: O=3200, i2509: O=800")

    return True


# ═══════════════════════════════════════════════════════════════════
# 测试 5: 成交量计数器重置
# ═══════════════════════════════════════════════════════════════════

def test_volume_reset():
    print("\n── 测试: 成交量重置边界 ──")

    k = Kline("1m")
    base = datetime(2025, 1, 6, 14, 0, 0)

    # 第一分钟: vol 1000 → 1200
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))

    # 跨分钟, 但 volume 突然变小 (模拟 CTP 重置)
    t2 = make_tick("rb2505", "SHFE", base + timedelta(minutes=1), 3210, 50)
    r = k.on_tick(t2)

    assert r is not None
    assert r.volume == 0, f"成交量重置时应返回 0, 实际 {r.volume}"

    print("  ✅ 成交量重置: bar_volume=0 (安全回退)")

    return True


# ═══════════════════════════════════════════════════════════════════
# 测试 6: 跨越大周期 (如跳过 10 分钟)
# ═══════════════════════════════════════════════════════════════════

def test_gap():
    print("\n── 测试: Tick 跳跃 (中间缺 tick) ──")

    k = Kline("5m")
    base = datetime(2025, 1, 6, 14, 0, 0)

    # 14:00 有 tick
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))

    # 直接跳到 14:15 (跨过了 14:05, 14:10 两个周期, 没有中间 tick)
    t2 = make_tick("rb2505", "SHFE", base + timedelta(minutes=15), 3250, 1500)
    r = k.on_tick(t2)

    assert r is not None, "跨周期应返回 BarData"
    # 注意: 中间没有 tick, 所以 14:00 的 bar 以唯一 tick 的数据为 OHLC
    assert r.open_price == 3200 and r.close_price == 3200

    print("  ✅ 跳跃场景: 14:00 bar 正确闭合 (O=C=3200)")
    print("  ⚠️  注意: 中间缺失的 14:05/14:10 bar 被跳过 — 这是预期行为 (tick 驱动)")

    return True


# ═══════════════════════════════════════════════════════════════════
# 测试 7: 1 小时 K 线
# ═══════════════════════════════════════════════════════════════════

def test_1h_bar():
    print("\n── 测试: 1小时K线生成 ──")

    k = Kline("1h")
    base = datetime(2025, 1, 6, 14, 0, 0)

    # 14:00-14:59 的数据
    k.on_tick(make_tick("rb2505", "SHFE", base, 3200, 1000))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=30), 3250, 1200))
    k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(minutes=59), 3220, 1300))

    # 15:00 — 跨小时
    r = k.on_tick(make_tick("rb2505", "SHFE", base + timedelta(hours=1), 3230, 1400))

    assert r is not None, "跨小时应返回 BarData"
    assert r.open_price == 3200
    assert r.high_price == 3250
    assert r.low_price == 3200
    assert r.close_price == 3220
    assert r.volume == 300
    assert r.datetime == base

    print("  ✅ 1h bar: O=3200 H=3250 L=3200 C=3220 V=300")

    return True


# ═══════════════════════════════════════════════════════════════════
# 测试 8: 参数校验
# ═══════════════════════════════════════════════════════════════════

def test_invalid_interval():
    print("\n── 测试: 非法参数校验 ──")

    try:
        Kline("3m")
        print("  ❌ 应该抛出 ValueError")
        return False
    except ValueError as e:
        print(f"  ✅ 正确拒绝非法周期: {e}")

    try:
        Kline("10s")
        print("  ❌ 应该抛出 ValueError")
        return False
    except ValueError as e:
        print(f"  ✅ 正确拒绝非法周期: {e}")

    return True


# ═══════════════════════════════════════════════════════════════════
# 测试 9: 多实例独立性
# ═══════════════════════════════════════════════════════════════════

def test_multi_instance():
    print("\n── 测试: 多实例独立 ──")

    k_5m = Kline("5m")
    k_1h = Kline("1h")

    assert k_5m.name == "kline_5m", f"name 应为 kline_5m, 实际 {k_5m.name}"
    assert k_1h.name == "kline_1h", f"name 应为 kline_1h, 实际 {k_1h.name}"
    assert k_5m.name != k_1h.name, "两个实例应有不同名称"

    print("  ✅ k_5m.name = kline_5m")
    print("  ✅ k_1h.name = kline_1h")
    print("  ✅ 多实例不冲突")

    return True


# ═══════════════════════════════════════════════════════════════════
# 运行所有测试
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  ctpbee_kline 测试套件")
    print("=" * 60)

    tests = [
        ("时间分桶", test_bucket),
        ("1分钟K线", test_1m_bar),
        ("5分钟K线", test_5m_bar),
        ("多合约独立", test_multi_symbol),
        ("成交量重置", test_volume_reset),
        ("Tick跳跃", test_gap),
        ("1小时K线", test_1h_bar),
        ("参数校验", test_invalid_interval),
        ("多实例独立", test_multi_instance),
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            ok = fn()
            if ok:
                passed += 1
            else:
                failed += 1
                print(f"  ⚠️  {name}: 有断言失败")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  ❌ {name}: 异常 - {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"  结果: {passed} 通过 / {failed} 失败 / {len(tests)} 总计")
    print("=" * 60)
