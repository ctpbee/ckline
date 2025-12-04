from setuptools import setup, find_packages

pkg = find_packages()
install_requires = ["ctpbee"]
setup(
    name='ctpbee_kline',
    version='0.2',
    description='ctpbee里面提供的k线生成算法',
    author='somewheve',
    author_email='somewheve@gmail.com',
    url='https://www.github.com/ctpbee/ckline',
    install_requires=install_requires,
    packages=pkg,
)
