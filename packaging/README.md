# 发布说明

这里放的是发布到不同生态的模板和工作流。

- PyPI：`.github/workflows/publish.yml` 使用 PyPI Trusted Publishing。需要在 PyPI 项目中绑定 GitHub 仓库环境 `pypi`。
- Homebrew：`packaging/homebrew/deepseek-codex-cli.rb`，发布 tag 后替换 tarball SHA256，再提交到自己的 tap 或 Homebrew core 审核。
- Scoop：`packaging/scoop/deepseek-codex-cli.json`，发布 zip 后替换 SHA256，再提交到 bucket。
- winget：`packaging/winget/*.yaml` 是 manifest 模板。需要先构建 Windows zip 或 exe，再替换下载地址和 SHA256，提交到 winget-pkgs。

当前项目可以先通过 pip 或 GitHub 源安装：

```powershell
python -m pip install --upgrade git+https://github.com/hnytgl/deepseek-cli.git
```
