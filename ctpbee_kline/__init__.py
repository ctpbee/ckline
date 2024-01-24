from ctpbee import Tool
from ctpbee.constant import ToolRegisterType, TickData, Interval
from ctpbee.level import tool_register
from ctpbee.constant import BarData


class Kline(Tool):
    def __init__(self):
        """
        :param level:
        """
        super().__init__("kline")
        self.bars = {}
        self.init = False

    @tool_register(ToolRegisterType.TICK)
    def on_tick(self, tick: TickData):
        if not self.init:
            for strategy in self.app._extensions.values():
                self.app.tools[self.name].add_func(func=strategy.on_bar, r_type=ToolRegisterType.TICK)
            self.init = True
        if self.bars.get(tick.local_symbol, None):
            if tick.datetime.minute != self.bars[tick.local_symbol][0].minute:
                bar = BarData(
                    symbol=tick.symbol,
                    exchange=tick.exchange,
                    interval=1,
                    datetime=self.bars[tick.local_symbol][0],
                    volume=tick.volume - self.bars[tick.local_symbol][5],
                    high_price=self.bars[tick.local_symbol][1],
                    open_price=self.bars[tick.local_symbol][2],
                    low_price=self.bars[tick.local_symbol][3],
                    close_price=self.bars[tick.local_symbol][4],
                )
                self.bars[tick.local_symbol] = [tick.datetime, tick.last_price, tick.last_price,
                                                tick.last_price, tick.last_price, tick.volume]
                return bar
            # high
            self.bars[tick.local_symbol][1] = max(self.bars[tick.local_symbol][1], tick.last_price)
            # low
            self.bars[tick.local_symbol][3] = min(self.bars[tick.local_symbol][1], tick.last_price)
            # close
            self.bars[tick.local_symbol][4] = tick.last_price
            return None
        else:
            self.bars[tick.local_symbol] = [tick.datetime, tick.last_price, tick.last_price,
                                            tick.last_price, tick.last_price, tick.volume]
