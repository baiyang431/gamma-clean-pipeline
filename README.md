# GAMMA LAB：可重复的数据清洗流水线

一个按 JSON 规则清洗 CSV 的 Python 命令行程序。支持 UTF-8、GB18030 等编码，处理缺失值、重复记录、数值范围、日期和枚举值，并记录被剔除的数据及原因。

## 环境与运行

需要 Python 3.10 或以上，只使用标准库，不需要安装第三方运行依赖。在项目根目录执行：

```console
python --version
python -m gamma_clean --input examples/dirty.csv --schema examples/schema.json --output-dir results/demo
```

`--input` 指定输入 CSV，`--schema` 指定规则。输出目录必须不存在；再次运行可改用 `results/demo2`。程序不会修改输入文件。

默认编码为 `utf-8-sig`，可以读取普通 UTF-8 和带 BOM 的 UTF-8 文件。其他编码用 `--encoding gb18030` 等参数显式指定。

如需安装为命令，可执行 `python -m pip install .`，然后使用 `gamma-clean`。安装阶段使用 setuptools，可能需要联网下载构建依赖。

## 输入与输出

样例数据是 `examples/dirty.csv`，预期清洗结果是 `examples/expected/clean.csv`。规则文件见 `examples/schema.json`：

- `columns` 定义列名、类型和是否必填；类型支持 `string`、`integer`、`number`、`date`。
- 必填值缺失时剔除记录；可选值可以留空或用 `default` 填补。
- `min`、`max` 定义数值范围，`choices` 定义字符串可选值。
- `dedupe_key` 指定去重列，未设置时按全部列去重，保留第一条有效记录。
- `missing_tokens` 默认包含空字符串、`NA`、`N/A`、`NULL`、`null`，区分大小写。

程序去除单元格首尾空白，保留字符串前导零；数值统一格式，日期只接受有效的 `YYYY-MM-DD`。输入表头必须与规则中的列对应，输出按规则中的列顺序排列。

输出均为 UTF-8：

| 文件 | 内容 |
| --- | --- |
| `clean.csv` | 清洗后的有效记录 |
| `rejected.jsonl` | 被剔除记录的原始字段、记录号和原因，记录号包含表头 |
| `report.json` | 输入、输出、非法、重复及填补数量等信息 |

默认允许剔除问题记录后输出结果。加上 `--strict` 后，只要有非法或重复记录就失败且不生成输出目录。

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 严格模式发现问题记录 |
| 2 | 参数、规则、编码或 CSV 格式错误 |
| 3 | 文件读写错误或输出目录已存在 |

## 项目目录

```text
gamma-clean-pipeline/
├── gamma_clean/        # 命令行入口和清洗逻辑
├── examples/           # 合成输入、规则、预期输出
├── tests/              # 单元测试
├── scripts/verify.py   # 命令行运行验证
├── docs/               # 报告、环境、数据说明和运行记录
├── .github/workflows/  # 自动测试配置
├── pyproject.toml
├── LICENSE
└── README.md
```

## 测试

```console
python -m unittest discover -s tests -v
python scripts/verify.py
```

测试结果统一记录在 `docs/REPORT.md`，原始日志为 `docs/unit-tests.txt` 和 `docs/verification.json`。数据来源、许可和用途见 `docs/DATA.md`。

## 限制

只处理带表头、逗号分隔的单个 CSV，不处理 Excel，不自动猜测编码。数值不接受科学计数法、千分位、NaN 或 Infinity；字符串不做 Unicode 字符合并。整个文件在内存中处理，目前只使用合成小数据进行验证。

源码和合成样例采用 MIT 许可，见 `LICENSE`。
