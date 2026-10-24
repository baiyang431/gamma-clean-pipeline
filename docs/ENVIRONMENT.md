# 运行环境说明

## 实际本地环境

- 操作系统：Windows 11，AMD64。
- 解释器：CPython 3.13.13。
- 程序与测试运行依赖：仅 Python 标准库，第三方运行依赖为 0。
- 构建工具：setuptools；项目元数据要求 setuptools >= 77，本地构建使用 82.0.1。

实际 CLI 验证时的环境由脚本读取并写入 `verification.json`，时间使用 UTC。验证不是模拟输出。

还实际完成了 wheel 构建、在无第三方包的隔离虚拟环境中离线安装、从项目目录外调用安装后的 `gamma-clean --version` 及样例清洗，结果与源码运行一致。

## 支持范围与验证范围

项目声明 Python >= 3.10。提供 Windows/Linux、Python 3.10/3.13 的 GitHub Actions 矩阵，但本地实测只证明当前 Windows + Python 3.13.13 环境的结果；其他环境须等待对应 CI 或实际运行确认。

直接运行不需要 `pip install`，也不需要下载数据：

```console
python -m gamma_clean --input examples/dirty.csv --schema examples/schema.json --output-dir results/local
python -m unittest discover -s tests -v
python scripts/verify.py
```

这些命令在项目根目录执行，输出目录必须不存在。使用新目录即可再次运行。Shell 的显示编码可能影响中文在终端的外观，产物本身按明确的 UTF-8 字节写出。

## 更新实测证据

```console
python scripts/verify.py --save docs/verification.json
```

这会使用当前环境重新验证并更新证据文件，时间和环境字段会随之变化。`unit-tests.txt` 应保存当前真实测试日志，不应手填通过结论。每次代码改变后需重新运行测试。

## 隔离安装（可选）

```console
python -m venv .venv
```

Windows 不用激活也可执行：

```console
.venv\Scripts\python -m pip install .
.venv\Scripts\gamma-clean --version
```

Linux/macOS 将解释器和命令路径换为 `.venv/bin/python` 和 `.venv/bin/gamma-clean`。安装阶段可能需要下载 setuptools，源码直接运行没有这个需求。
