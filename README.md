# DeepSeek Codex CLI

一个参考 Codex CLI 体验、完全适配 DeepSeek API 的命令行编程代理。它可以在终端里对话、读取和修改项目文件、运行命令、自动调用工具，并用窗口化界面展示任务过程、当前进度、工具日志和模型思考内容。

## 功能特性

- 适配 DeepSeek OpenAI-compatible Chat Completions API。
- 支持 `deepseek-chat` 和 `deepseek-reasoner` 等 DeepSeek 模型。
- 终端窗口式交互界面，显示进度、状态、工具调用和最终回复。
- 支持流式输出模型回复，任务执行时可以看到回复逐步生成。
- 支持多轮对话，能持续理解当前任务上下文。
- 自动工具调用：读文件、写文件、替换文本、列目录、运行 shell 命令。
- 写文件和替换文件前显示 unified diff 预览，并等待批准。
- Git 状态感知、自动创建分支、提交、推送并创建 GitHub PR。
- 会话持久化和历史恢复，支持按名称保存上下文。
- 默认工作区沙箱，防止文件工具越权读写工作区之外的路径。
- 命令白名单/黑名单，支持更细粒度的 shell 权限控制。
- 输入历史、Ctrl+D 退出、Ctrl+L 清屏、可滚动日志和多文件 review 视图。
- 真正的 split-pane 全屏 TUI：左侧日志，右侧思考/回复，底部输入框，并启用鼠标滚动。
- Codex CLI 风格紧凑输出：默认只显示状态和摘要，长工具结果折叠保存，用快捷键或命令展开。
- 按项目保存权限策略，团队项目可以复用同一套安全配置。
- 补丁支持 hunk 级别逐段接受或拒绝，减少“一次全收/全拒”的风险。
- 可以在明确授权后按需检测和安装本机缺失工具，并根据 Windows/macOS/Linux 自动选择可用包管理器。
- 跨平台安装脚本、`--doctor` 环境检查、`--self-update` 自更新，以及 Windows/macOS/Linux 单文件二进制构建 workflow。
- GitHub release notes 自动生成，PyPI/Homebrew/Scoop/winget 发布辅助脚本。
- 默认在执行 shell、写文件、Git 提交或 PR 前询问确认；可用 `--yes` 开启全自动模式。
- 支持单次任务模式，也支持进入交互式会话。
- 使用 Python 标准库完成 API 请求，运行时只依赖 `rich` 负责终端界面。

## 安装

```powershell
git clone https://github.com/hnytgl/deepseek-cli.git
cd deepseek-cli
python -m pip install -e .
```

设置 DeepSeek API Key：

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
```

如果使用 bash 或 zsh：

```bash
export DEEPSEEK_API_KEY="sk-..."
```

## 基本使用

进入交互式窗口：

```powershell
deepseek
```

执行单次任务：

```powershell
deepseek "阅读这个项目并补充中文 README"
```

指定工作目录：

```powershell
deepseek --cwd C:\path\to\project "修复测试失败的问题"
```

开启全自动工具执行：

```powershell
deepseek --yes "实现 TODO 并运行测试"
```

使用 DeepSeek Reasoner：

```powershell
deepseek --model deepseek-reasoner "分析这个项目的架构并给出改进建议"
```

使用普通文本模式，不启用窗口界面：

```powershell
deepseek --plain
```

使用 split-pane 全屏终端界面：

```powershell
deepseek --fullscreen
```

全屏界面中：

- 左侧是可滚动日志。
- 右侧上方是 reasoning / 思考内容。
- 右侧下方是模型回复。
- 底部是输入框。
- 鼠标滚轮会滚动当前聚焦面板，`Tab` 可以切换焦点。
- 默认是紧凑输出，长结果会折叠；按 `F4` 或输入 `/expand` 展开完整日志。

切换布局：

```powershell
deepseek --fullscreen --layout balanced
deepseek --fullscreen --layout logs-right
deepseek --fullscreen --layout stacked
```

默认展开完整输出：

```powershell
deepseek --expanded-output
```

保存并恢复会话：

```powershell
deepseek --session my-project
deepseek --session my-project --resume
deepseek --resume
```

开启只读审查模式：

```powershell
deepseek --approval read-only "检查这个仓库的问题，不要修改文件"
```

关闭 shell 工具：

```powershell
deepseek --no-shell "只阅读文件并给出建议"
```

只允许指定命令：

```powershell
deepseek --allow-command python --allow-command git
```

阻止高风险命令：

```powershell
deepseek --deny-command rm --deny-command del --deny-command powershell
```

允许 DeepSeek 在需要时安装本机工具：

```powershell
deepseek --allow-install-tools "如果缺少测试工具，请先安装再运行测试"
```

`install_tool` 可以只传逻辑工具名，例如 `ripgrep`、`jq`、`git`、`gh`、`node`。CLI 会自动识别当前系统和可用包管理器：

- Windows：优先 `winget`，再尝试 `scoop`、`choco`、`npm`、`pip`。
- macOS：优先 `brew`，再尝试 `npm`、`pip`。
- Linux：优先 `apt`、`dnf`、`pacman`、`zypper`，再尝试 `brew`、`npm`、`pip`。

也可以手动指定：

```text
install_tool(name="ripgrep", manager="winget")
install_tool(manager="pip", package="ruff")
```

保存当前项目权限策略：

```powershell
deepseek --approval ask --sandbox workspace --deny-command rm --save-policy --show-policy
```

允许访问工作区之外的路径：

```powershell
deepseek --sandbox unrestricted
```

## 交互命令

进入 `deepseek` 后可以使用这些命令：

- `/help`：显示帮助。
- `/clear`：清空当前对话上下文。
- `/logs`：打开可滚动日志视图。
- `/review`：打开当前 Git 多文件 diff review 视图。
- `/compact`：切回紧凑输出模式。
- `/expand`：展开完整工具输出。
- `/exit` 或 `/quit`：退出。

快捷键：

- `Ctrl+D`：退出。
- `Ctrl+L`：清屏。
- `↑` / `↓`：浏览输入历史。
- `F4`：全屏模式下切换紧凑/展开日志。

直接输入自然语言任务即可，例如：

```text
帮我检查这个仓库有什么问题，并修复能自动修复的部分
```

## 工具能力

DeepSeek 可以自动调用这些本地工具：

- `shell`：在当前工作区运行命令。
- `read_file`：分页读取 UTF-8 文本文件，返回 `offset`、`end_offset`、`total_chars`、`has_more` 和 `next_offset`，避免大文件截断后反复读取同一段。
- `write_file`：写入 UTF-8 文本文件，并自动创建父目录。
- `replace_in_file`：在文件中替换精确文本。
- `list_dir`：列出目录内容。
- `apply_file_edits`：一次性提交多文件完整内容编辑，并显示合并 diff 审批。
- `check_tool`：检查本机是否存在某个可执行工具。
- `install_tool`：在明确允许后安装缺失工具；默认会按操作系统自动选择 `winget`、`scoop`、`choco`、`brew`、`apt`、`dnf`、`pacman`、`zypper`、`npm` 或 `pip`。
- `git_diff`：显示当前多文件 Git diff，供 review。
- `git_status`：查看当前 Git 分支和工作树状态。
- `git_create_branch`：创建并切换到新分支。
- `git_commit`：暂存指定文件并提交。
- `git_create_pr`：推送当前分支并用 GitHub CLI 创建 PR。

默认情况下，写文件和替换文件会先展示 diff 预览；写操作、shell、Git 提交和 PR 创建都会询问确认。传入 `--yes` 后会自动批准工具执行，适合你明确希望它连续完成编程任务的场景。

## 权限和沙箱

审批模式：

- `--approval ask`：默认模式，危险操作前询问确认。
- `--approval auto` 或 `--yes`：自动批准工具执行。
- `--approval read-only`：禁用写文件、shell、Git 提交和 PR 等变更操作。

沙箱模式：

- `--sandbox workspace`：默认模式，文件工具只能访问当前工作区。
- `--sandbox unrestricted`：允许访问任意本机路径。

Shell 控制：

- `--no-shell`：禁用 shell 和依赖 shell 的 PR 工具。
- `--allow-command name`：只允许指定 shell 命令，可重复传入。
- `--deny-command name`：阻止指定 shell 命令，可重复传入。
- `--allow-install-tools`：允许 `install_tool` 安装缺失工具。
- `--save-policy`：把当前有效权限策略保存到项目。
- `--show-policy`：打印当前有效权限策略。

白名单优先约束可执行命令集合，黑名单用于拦截明确不希望模型执行的命令。命令名按可执行文件名识别，例如 `python -m pytest` 的命令名是 `python`。

项目策略保存位置：

```text
.deepseek-cli/policy.json
```

再次在该项目运行 `deepseek` 时会自动加载这个策略。命令行参数会覆盖项目策略。

## 补丁编辑和多文件 Review

DeepSeek 可以使用 `apply_file_edits` 一次提交多文件修改。CLI 会逐个展示每个 hunk 的 unified diff，你可以按 hunk 接受、拒绝，或者选择 `edit` 调用本机编辑器对该 hunk 的新内容做行级编辑，确认后才会真正写入。你也可以随时在交互模式中输入：

```text
/review
```

来查看当前工作区的多文件 Git diff；输入：

```text
/logs
```

可以打开可滚动的任务日志视图。

## Git 和 PR 工作流

DeepSeek 可以通过工具完成常见 Git 操作：

```text
帮我创建 codex/add-tests 分支，修复测试后提交，并打开一个 draft PR
```

PR 创建依赖本机已安装并登录的 GitHub CLI：

```powershell
gh auth status
```

如果当前网络或远端权限不允许 push/PR，工具会把失败输出返回给模型，模型可以继续解释或选择备用方案。

## 会话持久化

使用 `--session` 后，每轮对话结束都会保存到：

```text
~/.deepseek-cli/sessions/
```

恢复方式：

- `--session name --resume`：恢复指定会话。
- `--resume`：恢复最近更新的会话。

## 配置项

环境变量：

- `DEEPSEEK_API_KEY`：必填，DeepSeek API Key。
- `DEEPSEEK_BASE_URL`：可选，默认 `https://api.deepseek.com`。
- `DEEPSEEK_MODEL`：可选，默认 `deepseek-chat`。

命令行参数会覆盖环境变量。

## 本地验证

```powershell
python -m compileall src tests
python -m pytest
deepseek --help
deepseek --version
deepseek --doctor
```

## 安装和更新

Windows PowerShell：

```powershell
.\scripts\install.ps1
```

macOS / Linux：

```bash
sh scripts/install.sh
```

自更新：

```powershell
deepseek --self-update
```

也可以指定来源：

```powershell
deepseek --self-update "git+https://github.com/hnytgl/deepseek-cli.git"
```

## 发布到生态

仓库已包含发布准备文件：

- PyPI：`.github/workflows/publish.yml`，使用 PyPI Trusted Publishing。
- Homebrew：`packaging/homebrew/deepseek-codex-cli.rb`。
- Scoop：`packaging/scoop/deepseek-codex-cli.json`。
- winget：`packaging/winget/*.yaml`。
- 单文件二进制：release 时通过 PyInstaller 构建 `deepseek-windows-x64.zip`、`deepseek-macos-x64.zip`、`deepseek-linux-x64.zip`。

真正发布到这些生态需要对应账号、release 产物和 SHA256 校验值。当前模板中带有 `REPLACE_WITH_*_SHA256` 占位符，发布 release 后替换即可提交到对应 registry。

自动生成并校验 SHA256：

```powershell
python scripts/update_release_hashes.py `
  --version 0.5.0 `
  --homebrew-tar .\dist\deepseek-cli-v0.5.0.tar.gz `
  --scoop-zip .\dist\deepseek-cli-v0.5.0.zip `
  --winget-windows-zip .\dist\deepseek-windows-x64.zip `
  --check
```

创建带自动 release notes 的 GitHub release：

```powershell
python scripts/create_release.py 0.6.0 --draft
```

发布到真实 registry 的辅助入口：

```powershell
python scripts/publish_registries.py --pypi
python scripts/publish_registries.py --homebrew-tap C:\path\to\homebrew-tap
python scripts/publish_registries.py --scoop-bucket C:\path\to\scoop-bucket
python scripts/publish_registries.py --winget-pkgs C:\path\to\winget-pkgs
```

这些命令会执行真实上传或复制 manifest 到对应 registry 仓库。PyPI 需要已配置凭据或 Trusted Publishing；Homebrew/Scoop/winget 仍需要向对应仓库提交 PR 并通过审核。

## 和 Codex CLI 看齐的方向

这个项目当前已经具备 Codex CLI 风格的基础能力：split-pane 全屏 TUI、紧凑输出、长内容折叠展开、多轮对话、流式输出、自动工具调用、本地文件编辑、命令执行、hunk 级 diff 审批、hunk 行级编辑、Git/PR 工作流、会话恢复、权限沙箱、可滚动日志、多文件 review、命令 allow/deny 策略、项目策略、按需安装工具、跨平台安装检查、单文件二进制构建、SHA256 模板回填和 release notes 生成。后续可以继续增强：

- 行级 diff UI 而不是外部编辑器。
- 自动提交 Homebrew/Scoop/winget PR。
- 自动检查 registry 发布状态。
