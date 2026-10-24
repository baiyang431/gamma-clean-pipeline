# GAMMA LAB：可重复的数据清洗流水线

[GitHub 仓库](https://github.com/baiyang431/gamma-clean-pipeline) · [自动测试](https://github.com/baiyang431/gamma-clean-pipeline/actions)

一个 Python 命令行项目：按 JSON 规则读取 CSV，处理编码、缺失值、重复记录与非法值，输出干净数据、剔除记录和可复现报告。

运行和测试只依赖 Python 标准库，无需联网安装第三方运行依赖。样例是合成测试数据，不包含真实人员信息。

## 1. 快速运行

需要 Python 3.10 或更高版本。在项目根目录执行以下命令；Windows PowerShell、Linux 和 macOS 的命令相同。若系统使用 `python3`，将命令中的 `python` 换成 `python3`。

```console
python --version
python -m gamma_clean --input examples/dirty.csv --schema examples/schema.json --output-dir results/demo
```

预期显示：

```text
OK: input=11 output=4 invalid=6 duplicates=1
```

输出目录包含：

| 文件 | 内容 |
| --- | --- |
| `clean.csv` | 规范化后的有效数据，UTF-8、无 BOM、LF 换行 |
| `rejected.jsonl` | 每条被剔除记录的原始字段、逻辑记录号和原因 |
| `report.json` | 行数、填补数、编码、规则版本以及输入、配置和输出的 SHA-256 |

**输出目录必须不存在。** 再运行时使用新目录，如 `results/demo2`。程序不覆盖已有结果，也不修改原始输入。

运行完整验证：

```console
python -m unittest discover -s tests -v
python scripts/verify.py
```

当前本地验证记录见 [docs/verification.json](docs/verification.json)，实验解读见 [docs/REPORT.md](docs/REPORT.md)。独立的人工预期结果见 [examples/expected/clean.csv](examples/expected/clean.csv)。

## 2. 完整目录

```text
gamma-clean-pipeline/
├── .gitattributes
├── .gitignore
├── .github/
│   └── workflows/
│       └── test.yml              # Windows/Linux、Python 3.10/3.13 CI 配置
├── LICENSE
├── README.md
├── pyproject.toml                # 项目元数据；第三方运行依赖为空
├── gamma_clean/
│   ├── __init__.py               # 版本号
│   ├── __main__.py               # 命令行入口与退出码
│   └── core.py                   # 规则校验、清洗、去重、结果发布
├── scripts/
│   └── verify.py                 # 实际调用 CLI，验证复现和失败行为
├── tests/
│   └── test_pipeline.py          # 31 项测试，部分含多组边界子用例
├── examples/
│   ├── dirty.csv                # 11 条合成脏数据
│   ├── schema.json              # 字段、缺失值、范围及去重规则
│   └── expected/
│       └── clean.csv            # 独立预期：4 条有效数据
└── docs/
    ├── DATA.md                  # 来源、许可、划分与数据版本
    ├── ENVIRONMENT.md           # 环境、依赖和运行方式
    ├── REPORT.md                # 实现与验证报告
    ├── SUBMISSION.md            # 提交说明与已知待确认项
    ├── verification.json        # CLI 复现验证实测记录
    └── unit-tests.txt           # 单元测试实测日志
```

运行后生成的 `results/` 不提交到 Git；发布压缩包也不包含临时结果和本地 Git 元数据。

## 3. 清洗规则与顺序

1. 校验 JSON 配置，拒绝未知字段、重复键、错误类型、相互冲突的范围及不合法默认值。
2. 使用声明的编码严格解码，默认 `utf-8-sig`，兼容 UTF-8 BOM。不猜测编码，不用替换字符掩盖解码错误。
3. 严格解析逗号分隔 CSV。表头必须恰好包含配置列；输入列顺序可以不同，输出按配置顺序排列。列数错误、坏引号、空白记录等结构问题导致整次失败。
4. 对单元格做 Unicode NFC 规范化并去除首尾空白，保留字段内部空格和换行。
5. 根据缺失标记处理必填、可选及默认值。必填值缺失则剔除该记录；可选值缺失输出空字符串，配置了默认值时填补。
6. 校验类型、数值边界、日期和枚举。非法值剔除整条记录，记录所有有问题字段的原因。
7. 按规范化后的去重键比较，保留第一条有效记录。无效记录不占用去重键；后续同键但其他字段不同的记录也会被剔除并保留原值，供核对。
8. 在同一父目录的临时目录写齐三个文件，再重命名发布。普通写入错误会清理临时目录；严格模式或输入校验失败不发布结果。

### 字段规则

配置示例见 `examples/schema.json`。顶层 `version` 必须为整数 `1`，`columns` 为非空列表。

| 属性 | 规则 |
| --- | --- |
| `name` | 唯一、非空且首尾无空白的列名 |
| `type` | `string`、`integer`、`number`、`date` |
| `required` | 布尔值；默认 `true` |
| `default` | 仅可选字段允许；必须为非缺失字符串，并通过该字段的类型和边界校验 |
| `min`、`max` | 仅数值类型允许，边界包含端点，且 `min <= max` |
| `choices` | 仅字符串类型允许；非空、无重复、无缺失标记的字符串列表 |

顶层 `dedupe_key` 是非空且不重复的列名列表，未设置时按所有列去重。若去重键包含可空字段，空值也会参与比较；请按数据含义选择键，示例使用必填 `id`。

顶层 `missing_tokens` 默认 `['', 'NA', 'N/A', 'NULL', 'null']`，区分大小写；自定义时必须包含空字符串。如果某列中的 `NA` 是合法业务值，应修改缺失标记。

### 类型约定

- 字符串保留前导零，例如 `id=001` 不会变成 `1`。
- 整数接受 ASCII 数字和可选正负号，`+020` 输出 `20`；`1.0` 不作为整数接受。
- 数值使用 `Decimal`，避免二进制浮点舍入。`001.2300` 输出 `1.23`，负零输出 `0`。不接受千分位、货币符号、科学计数法、NaN 或 Infinity。
- 日期只接受真实存在的 `YYYY-MM-DD` 日期；拒绝 `2026-02-30` 及含歧义的日期写法。
- 配置中的数值边界应为 JSON 数值；需极高精度时优先使用整数业务单位。小数边界会先经过 JSON 的浮点解析，不作为任意精度边界格式使用。

## 4. 编码和严格模式

GB18030 数据必须显式指定：

```console
python -m gamma_clean --input your-data.csv --schema examples/schema.json --encoding gb18030 --output-dir results/gb18030
```

严格模式只要发现非法或重复记录就失败，并且不发布任何输出：

```console
python -m gamma_clean --input examples/dirty.csv --schema examples/schema.json --output-dir results/strict-demo --strict
```

这条命令**预期退出码为 1**，因为样例确实有问题。非严格模式允许剔除问题记录后成功输出，即使全部记录都被剔除，也会输出仅含表头的 CSV。

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功发布结果 |
| `1` | 严格模式发现被剔除记录 |
| `2` | 参数、规则、编码、CSV 结构错误 |
| `3` | 文件读写错误、输入文件不存在、输出路径已存在 |

PowerShell 使用 `$LASTEXITCODE` 查看退出码，Linux/macOS 使用 `echo $?`。报错写入标准错误，成功摘要写入标准输出。

记录号按 CSV 逻辑记录计数，表头为第 1 条；带引号的多行字段仍属于同一条记录。空文件失败；只有合法表头的文件成功输出零条记录。单字段最大长度为 1,000,000 个字符。

## 5. 可复现性

- 在相同运行环境中，同样的原始字节、配置字节、编码、模式及本工具版本，多次运行的三个结果文件应字节一致。
- 不把绝对路径、时间戳或机器名写入 `report.json`，避免这些因素改变结果。
- 输出始终使用 UTF-8、LF 换行和固定的 JSON 键排序。
- 报告记录原始输入和配置的哈希；修改配置空白也会改变配置哈希。
- 幂等性验证对象是 `clean.csv`：再次清洗后 CSV 字节一致。第二次的报告和剔除文件会改变，因为输入已变干净。
- `docs/verification.json` 单独记录实际验证时间与环境；它是实验记录，不属于字节一致性承诺中的清洗输出。

## 6. 安装为命令（可选）

直接使用 `python -m gamma_clean` 无需安装。若需要全局命令，可在虚拟环境中执行：

```console
python -m pip install .
gamma-clean --version
```

打包阶段使用 setuptools，可能需要联网下载构建依赖；它不是程序的运行依赖。

## 7. 项目边界

目前处理单个、逗号分隔、具有表头的 CSV；未实现 Excel、自动编码探测或流式大文件处理。输入、候选记录及审计记录存放在内存，内存消耗随数据量增长；本次没有进行大数据规模的性能验证。

不保证在进程被强制终止或断电时清理临时目录，也不把目录重命名当作断电持久性承诺。避免多个进程向相同输出目录同时发布结果。

题目没有提供可访问的指定目标库，本项目使用 Python 标准库的 `csv`、`json`、`decimal`、`unicodedata`、`hashlib`、`argparse`、`unittest`。这证明了实际集成的能力，不代表已满足任何尚未提供的“指定目标库”要求。

## 8. 数据、许可和提交

源码与合成样例按 [MIT License](LICENSE) 发布；详见 [数据说明](docs/DATA.md)。

代码仓库上传步骤见 [提交说明](docs/SUBMISSION.md)。CI 文件已提供，远端是否通过应以 GitHub Actions 实际结果为准，本地测试通过不等于远端 CI 已运行。
