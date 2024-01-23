# K线支持

### 安装

```bash 
pip install ctpbee_kline
```

### 快速使用

```python 
from ctpbee import CtpbeeApi, CtpBee
from ctpbee.constant import *
from ctpbee_kline import Kline


class Main(CtpbeeApi):
    def __init__(self, name):
        super().__init__(name)
        self.init = False

    def on_tick(self, tick: TickData) -> None:
        print("tick回报", tick)

    def on_position(self, position: PositionData) -> None:
        pass

    def on_contract(self, contract: ContractData):
        if contract.symbol == "rb2405":
            self.action.subscribe(contract.local_symbol)

    def on_bar(self, bar: BarData):
        if bar is not None:
            print(bar.interval, bar)

    def on_init(self, init: bool):
        self.info("账户初始化成功回报")
        self.init = True


if __name__ == '__main__':
    kline = Kline("hello ctpbee kline")
    app = CtpBee("market", __name__, refresh=True).with_tools(kline)
    example = Main("DailyCTA")
    app.config.from_json("config.json")
    app.add_extension(example)
    app.start(log_output=True)
```
