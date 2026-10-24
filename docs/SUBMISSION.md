# 提交说明

## 交付材料

本目录就是可独立提交的项目，不需要把源码再压成单个文件上传仓库。仓库应包含 README、源码、测试、样例、规则、文档、实测证据、许可和 CI 配置。

`results/`、虚拟环境、Python 缓存和 Git 内部数据不应作为项目内容上传。没有包含私有业务数据或访问令牌。

## 提交前本地验证

在项目根目录执行：

```console
python -m unittest discover -s tests -v
python scripts/verify.py
```

需要查看实际产物时，选择一个未存在的目录：

```console
python -m gamma_clean --input examples/dirty.csv --schema examples/schema.json --output-dir results/submission-check
```

## GitHub 仓库

建议仓库名 `gamma-clean-pipeline`。公开仓库方便评审直接访问；私有仓库需按平台方式授予评审访问权限。

如果本地项目尚未初始化 Git：

```console
git init -b main
git add .
git commit -m "Implement reproducible CSV cleaning pipeline"
```

如果本地已包含初始提交，则跳过以上步骤。可通过 `git status` 和 `git log -1 --oneline` 检查。

在自己的 GitHub 账号创建空仓库，不预先生成 README。将下面地址中的 `YOUR_ACCOUNT` 替换为自己的用户名；该地址是模板，不是已创建仓库：

```console
git remote add origin https://github.com/YOUR_ACCOUNT/gamma-clean-pipeline.git
git push -u origin main
```

如果已配置 origin，则先用 `git remote -v` 确认地址，避免重复添加。上传成功后复制实际仓库 URL，并记录所提交 commit：

```console
git rev-parse HEAD
```

没有指定上游仓库时，不需要为了形式额外创建 PR。仓库上传与远端 CI 的结果要实际检查，不能把本地有文件当作上传成功。

## 可用于提交页的说明

项目实现基于显式 JSON 规则的 Python CSV 命令行清洗，覆盖严格编码读取、缺失值、重复记录、非法值及失败退出行为。提供合成输入、独立预期输出、31 项测试、实际 CLI 复现证据、数据来源与许可说明、实现报告及环境说明。样例输入 11 条，输出 4 条，剔除 6 条非法记录和 1 条重复记录；重复运行产物字节一致，干净 CSV 再次清洗保持一致。

提交时另附实际仓库链接、commit 和 GitHub Actions 结果，不使用占位地址。

## 仍需核对的原题信息

- 完整题目和讨论页是否有补充业务规则。
- “目标库集成”是否指某个指定第三方库。当前只确认了标准库实现。
- 平台是否要求特定分支、表单格式、PR 或额外报告附件。

用户目前确认未指定提交仓库，因此可以准备上传自己的 GitHub 新项目；其他未提供的规则不能视为已验收。
