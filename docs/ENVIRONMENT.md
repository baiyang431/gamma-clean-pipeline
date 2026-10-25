# 运行环境

本次本地运行使用 Windows 11、CPython 3.13.13。程序和测试只依赖 Python 标准库，无第三方运行依赖。项目声明支持 Python 3.10 及以上；本次没有重新验证其他系统或 Python 版本。

在项目根目录运行，输出目录需不存在：

```console
python -m gamma_clean --input examples/dirty.csv --schema examples/schema.json --output-dir results/demo
python -m unittest discover -s tests -v
python scripts/verify.py
```

更新命令行运行记录：

```console
python scripts/verify.py --save docs/verification.json
```

源码运行无需安装。可选安装使用 `python -m pip install .`，构建依赖为 setuptools >= 77。
