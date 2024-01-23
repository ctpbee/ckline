from ctpbee import Tool
from ctpbee.constant import ToolRegisterType, TickData
from ctpbee.level import tool_register
from ctpbee.constant import BarData


class Kline(Tool):
    def __init__(self, level):
        """
        :param level:
        """
        super().__init__(level)
        self.bars = {}
        self.init = False
        if type(level) != list:
            raise TypeError("请传入k线支持级别列表 如果支持1min, 3分钟请使用level=[1,3]传入参数")
        self.level: list = level

    @tool_register(ToolRegisterType.TICK)
    def on_tick(self, tick: TickData):
        if not self.init:
            for strategy in self._app._extensions.values():
                self.app.tools[self.name].add_func(func=strategy.on_bar, r_type=ToolRegisterType.TICK)
        if self.bars.get(tick.local_symbol, None):
            if tick.datetime.minute != self.bars[tick.local_symbol][0].minute:
                bar = BarData(
                    symbol=tick.symbol,
                    exchange=tick.exchange,
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
