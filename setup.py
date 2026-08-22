from setuptools import find_packages, setup

setup(
    name="ctpbee_kline",
    version="1.0.0",
    description="ctpbee 多周期K线生成工具 (tick/bar 双驱动, 夜盘交易日感知)",
    author="somewheve",
    author_email="somewheve@gmail.com",
    url="https://www.github.com/ctpbee/ckline",
    install_requires=["ctpbee>=1.8"],
    python_requires=">=3.9",
    packages=find_packages(exclude=["tests", "tests.*"]),
)
