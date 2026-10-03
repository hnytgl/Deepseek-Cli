# DeepSeek Codex CLI

[![CI](https://github.com/hnytgl/Deepseek-Cli/actions/workflows/ci.yml/badge.svg)](https://github.com/hnytgl/Deepseek-Cli/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

对标 OpenAI Codex CLI 体验、完全适配 DeepSeek API 的命令行编程代理。在终端里对话、读取和修改项目文件、运行命令、搜索代码、自动调用工具，并用窗口化界面展示任务过程、当前进度、工具日志和模型思考内容。

**中国人自己的 AI 编程终端** —— 用 DeepSeek 的超低价格获得 Codex CLI 级别的开发体验。

## 更新日志

### v1.0.0（2026-09-26）

**全面对标 Codex CLI 的正式版本：**

- **OS 级沙箱**：Linux bubblewrap 命名空间隔离 / macOS Seatbelt 配置 / Windows 受限进程 + 环境净化，`--sandbox-mode auto|none|strict`
- **MCP 客户端**：支持接入外部 MCP Server（config.toml `[mcp_servers]` 配置），JSON-RPC over stdio，工具自动注册
- **多 Provider**：`--provider deepseek|ollama|lmstudio|openai|openrouter|anthropic`，本地模型无需 API Key
- **Profiles 多配置**：`--profile fast` / `--profile careful`，config.toml `[profiles.NAME]` 一键切换模型+审批+参数
- **并发工具执行**：read_only 工具（search/glob/read_file/git_status）自动 ThreadPool 并发，多文件读取提速 3-5×
- **Web 搜索**：内置 `web_search` 工具（DuckDuckGo，无需 API Key），模型可自主查文档
- **编辑前 Checkpoint + /undo**：每次文件修改前自动 git stash，`/undo` 一键回滚
- **权限记忆**：session 级工具/命令白名单，减少重复确认
- **Shell 补全**：`deepseek --completions bash|zsh|fish`，覆盖全部 flag 和 choices
- **JSON 输出**：`--json` 结构化输出（answer/model/usage/modified_files），CI/CD 管道友好
- **代码搜索**：`search`（ripgrep + Python fallback）+ `glob` 工具，无需开 shell
- **补丁式编辑**：`patch_file`（unified diff），比整文件回传省 10× token
- **配置文件**：`~/.deepseek-cli/config.toml` + 项目级覆盖 + AGENTS.md 项目指令
- **Codex 风格审批**：`suggest` / `auto-edit` / `full-auto` 三档
- **DeepSeek 推理模式**：`--reasoning` + `--thinking-budget`（deepseek-v4-pro）
- **费用统计**：`/cost` 实时 token 用量 + ¥ 估算
- **架构重构**：tools.py 拆分为 registry + helpers + executor；CommandRegistry 三端共享
- **安全加固**：原子写入、CRLF 保留、policy 禁提权、审批死锁修复、api_key repr 隐藏、shell 输出截断

### v0.9.0（2026-09-26）

**对标 Codex CLI 的重大升级：**

- **配置文件**：`~/.deepseek-cli/config.toml` + 项目级覆盖，偏好持久化，不用每次敲 flag
- **AGENTS.md 项目指令**：自动读取项目根目录的 `AGENTS.md` / `DEEPSEEK.md`，注入系统提示词，让模型了解你的代码规范和构建命令
- **Codex 风格审批模式**：`suggest`（只读）/ `auto-edit`（自动改文件，shell 需确认）/ `full-auto`（全自动）
- **DeepSeek 推理模式**：`--reasoning` 切换 deepseek-v4-pro，`--thinking-budget` 控制思考深度
- **代码搜索工具**：`search`（ripgrep + Python fallback）和 `glob`，无需开 shell 即可搜索代码
- **补丁式编辑**：`patch_file` 接受 unified diff，比整文件回传省 10× token
- **费用统计**：`/cost` 命令实时显示 token 用量和估算费用（¥）
- **静默模式**：`-q/--quiet` 适合脚本和 CI 集成
- **上下文管理**：`max_context_chars` 降到 200K，防止长会话撞 API 400

**安全加固：**

- 原子写入（tempfile + os.replace），崩溃不损坏文件
- Windows CRLF 换行符完整保留，不再产生整文件伪 diff
- `replace_in_file` 拒绝空 `old` 参数，防止文件被摧毁
- 项目级 policy.json 只能收紧不能放宽，堵死 clone 恶意仓库即 RCE
- 全屏模式审批死锁修复（event.wait 加超时轮询）
- Rich 交互模式 API 错误不再崩 TUI
- `api_key` 标记 `repr=False`，traceback 不泄密钥
- `git add --` 防参数注入
- shell 输出截断至 16KB，防 OOM 和 token 爆炸
- 会话恢复后确保 system prompt 存在

### v0.8.1

- 初始发布：Codex 风格编程代理，13 个工具，split-pane TUI，会话持久化

## 功能特性

### 核心能力
- 适配 DeepSeek OpenAI-compatible Chat Completions API（`deepseek-flash` / `deepseek-v4-pro`）。
- **代码搜索**：内置 `search`（ripgrep + Python fallback）和 `glob` 工具，无需开 shell 即可搜索代码。
- **补丁式编辑**：`patch_file` 工具接受 unified diff，比整文件回传省 10× token。
- **DeepSeek 推理模式**：`--reasoning` 启用深度思考（deepseek-v4-pro），复杂架构分析和调试更强。
- **AGENTS.md 项目指令**：自动读取项目根目录的 `AGENTS.md`，让模型了解你的代码规范。
- **配置文件**：`~/.deepseek-cli/config.toml` 持久化偏好，不用每次敲 flag。
- **Codex 风格审批模式**：`suggest`（只读）/ `auto-edit`（自动改文件，shell 需确认）/ `full-auto`（全自动）。
- **Token 用量统计**：`/cost` 命令实时显示 token 消耗和估算费用。

### 交互体验
- 终端窗口式交互界面，显示进度、状态、工具调用和最终回复。
- 流式输出模型回复，任务执行时可以看到回复逐步生成。
- 真正的 split-pane 全屏 TUI：上方执行区，下方交互区和输入框，支持鼠标滚动。
- 内置 `default`、`ocean`、`mono`、`high-contrast` 四套 TUI 主题。
- Codex CLI 风格紧凑输出：默认只显示状态和摘要，长工具结果折叠，`F4` 展开。
- 全屏 TUI 中任务后台执行，执行过程中仍可输入 `/status`、`/cancel`、`/review`、`/cost`。

### 安全与控制
- 默认工作区沙箱，防止文件工具越权读写工作区之外的路径。
- 命令白名单/黑名单，细粒度 shell 权限控制。
- 项目级策略**只能收紧不能放宽**，恶意仓库无法通过 policy.json 提权。
- 写文件和替换文件前显示 unified diff 预览并等待批准。
- 原子写入（tempfile + os.replace），崩溃不损坏文件。
- Windows CRLF 换行符完整保留，不再产生整文件伪 diff。
- API Key 标记 `repr=False`，traceback 不泄密钥。

### 工作流
- Git 状态感知、自动创建分支、提交、推送并创建 GitHub PR。
- 会话持久化和历史恢复，支持按名称保存上下文。
- 会话列表、全文搜索和任务回放。
- 跨平台安装脚本、`--doctor` 环境检查、`--self-update` 自更新。
- Quiet 模式（`-q`）适合脚本和 CI 集成。

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

使用 DeepSeek V4 Pro 处理复杂任务：

```powershell
deepseek --model deepseek-v4-pro "分析这个项目的架构并给出改进建议"
```

设置 API 超时和网络重试次数：

```powershell
deepseek --api-timeout 180 --api-retries 5 "分析当前项目"
```

API 请求遇到 HTTP 429、5xx 或临时网络错误时会进行指数退避重试，并优先遵循服务端的 `Retry-After` 响应头。

使用普通文本模式，不启用窗口界面：

```powershell
deepseek --plain
```

使用 split-pane 全屏终端界面：

```powershell
deepseek --fullscreen
```

全屏界面中：

- 上方 `Execution` 是执行区，包含日志、reasoning / 思考内容和模型回复。
- 下方 `Interaction` 会记录用户输入、状态、批准请求和取消请求。
- 最底部 `Input` 是始终可用的输入框。
- 鼠标滚轮会滚动当前聚焦面板，`Tab` 可以切换焦点。
- 默认是紧凑输出，长结果会折叠；按 `F4` 或输入 `/expand` 展开完整日志。
- 执行中也可以继续输入命令：`/status` 查看当前进度，`/cancel` 会在当前模型请求或工具调用返回后尽快停止后续步骤。
- 如果执行中需要批准 shell、写文件或 hunk 修改，直接在输入框里输入 `y` / `n` 或 `/approve` / `/reject`。

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

搜索会话和回放任务：

```powershell
deepseek --sessions
deepseek --sessions "parser"
deepseek --replay-session my-project
```

`--sessions` 会搜索会话名称、工作目录、模型和消息正文。`--replay-session` 会输出适合阅读或重定向保存的完整对话记录，不需要设置 API Key。

会话保存时默认会掩码 API Key、Token、Authorization、Cookie、密码和用户主目录路径。只有在明确需要保存原始内容时才使用 `--save-sensitive`；包含敏感信息的会话文件不应共享或提交到仓库。

选择 TUI 主题：

```powershell
deepseek --theme ocean
deepseek --fullscreen --theme high-contrast
$env:DEEPSEEK_THEME="mono"
deepseek
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
- `/cost`：显示当前会话的 token 用量和估算费用。
- `/clear`：清空当前对话上下文。
- `/sessions [关键词]`：列出或搜索已保存会话。
- `/replay NAME`：把指定会话加载到当前对话，可继续执行后续任务。
- `/logs`：打开可滚动日志视图。
- `/review`：打开当前 Git 多文件 diff review 视图。
- `/status`：查看当前任务是否还在运行以及工具步进度。
- `/cancel`：请求取消当前任务。
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

- `shell`：在当前工作区运行命令（输出自动截断至 16KB，防 OOM）。
- `read_file`：按块分页读取 UTF-8 文本文件，返回 `offset`、`has_more`、`next_offset`。
- `write_file`：写入 UTF-8 文本文件（原子写入，崩溃不损坏）。
- `replace_in_file`：在文件中替换精确文本（拒绝空 `old` 参数）。
- **`patch_file`**：应用 unified diff 补丁，比 write_file 省 10× token。
- `list_dir`：列出目录内容。
- **`search`**：正则搜索文件内容（ripgrep 优先，Python fallback），返回 file:line:content。
- **`glob`**：按 glob 模式查找文件（如 `src/**/*.py`）。
- `apply_file_edits`：一次性提交多文件完整内容编辑，支持 hunk 级审批。
- `check_tool`：检查本机是否存在某个可执行工具。
- `install_tool`：在明确允许后安装缺失工具。
- `git_diff`：显示当前多文件 Git diff。
- `git_status`：查看当前 Git 分支和工作树状态。
- `git_create_branch`：创建并切换到新分支。
- `git_commit`：暂存指定文件并提交。
- `git_create_pr`：推送当前分支并用 GitHub CLI 创建 PR。

默认情况下，写文件和替换文件会先展示 diff 预览；写操作、shell、Git 提交和 PR 创建都会询问确认。传入 `--yes` 后会自动批准工具执行，适合你明确希望它连续完成编程任务的场景。

## 权限和沙箱

审批模式（对标 Codex CLI）：

- `--approval suggest`：只读模式，模型只能读文件和搜索，不能修改任何东西。
- `--approval auto-edit`：自动批准文件编辑，shell 命令仍需确认。**日常推荐**。
- `--approval full-auto` 或 `--yes`：全自动模式，所有工具自动批准（在沙箱内）。
- `--approval read-only`：等同于 suggest（兼容旧写法）。
- `--approval ask`：等同于默认行为（兼容旧写法）。
- `--approval auto`：等同于 full-auto（兼容旧写法）。

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

> **安全说明**：项目级 `.deepseek-cli/policy.json`、`config.toml` 及其中的 profile 只能收紧权限。自动执行权限由命令行参数或用户级配置授权；项目白名单与用户白名单取交集，黑名单累加，项目限制不会被 `--yes` 绕过。`--show-policy` 显示实际生效的同一套权限。

白名单优先约束可执行命令集合，黑名单用于拦截明确不希望模型执行的命令。复合命令中的每一段都会检查，例如 `python --version && git status` 会同时检查 `python` 和 `git`。命令名按可执行文件名识别，并兼容 Windows 的 `.exe`、`.cmd`、`.bat`、`.com` 后缀。

项目策略保存位置：

```text
.deepseek-cli/policy.json
```

再次在该项目运行 `deepseek` 时会自动加载这个策略。命令行参数设置授权上限，项目策略可进一步收紧。

## 补丁编辑和多文件 Review

DeepSeek 可以使用 `apply_file_edits` 一次提交多文件修改。CLI 会逐个展示每个 hunk 的 unified diff，你可以按 hunk 接受、拒绝，或者选择 `edit` 打开内置行级 diff UI。行级 UI 会把旧行和新行并排显示，你可以选择保留全部新行、拒绝该 hunk、只保留指定新行，或者直接输入替换文本，确认后才会真正写入。你也可以随时在交互模式中输入：

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

### 配置文件

支持 `~/.deepseek-cli/config.toml`（用户级）和 `.deepseek-cli/config.toml`（项目级）：

```toml
# ~/.deepseek-cli/config.toml
model = "deepseek-flash"
approval = "auto-edit"
theme = "ocean"
sandbox = "workspace"
max_steps = 64
temperature = 0.2

[reasoning]
enabled = false
model = "deepseek-v4-pro"
thinking_budget = 4096

[shell]
allow = ["git", "npm", "python", "pytest", "ruff"]
deny = ["rm", "sudo", "format"]
```

普通偏好的优先级：CLI 参数 > 环境变量 > 项目配置 > 用户配置 > 默认值。Profile 在对应文件层级内生效，环境变量和显式 CLI 参数仍优先。权限设置遵循上述“只收紧”规则；要默认启用 `auto-edit`，请放在用户级配置或显式传入 CLI 参数。

`max_steps`、`max_context_chars`、`temperature`、`stream`、`quiet`、`theme`、`layout`、`expanded_output` 以及 `[reasoning].thinking_budget` 均在未提供对应 CLI 参数时生效。配置解析错误会明确报错；Python 3.10 安装包自动包含 `tomli`。

### AGENTS.md 项目指令

在工作区目录放置项目指令，按 `AGENTS.md`、`.deepseek-cli/AGENTS.md`、`DEEPSEEK.md` 顺序读取首个非空且可 UTF-8 解码的文件，最多 8192 个字符。CLI 启动、恢复会话及 `/replay` 时注入当前工作区指令，替换旧会话的系统提示词；从子目录启动时可通过 `--cwd` 指定根目录：

```markdown
# AGENTS.md

## 代码规范
- 使用 Python 3.10+ 类型标注
- 测试用 pytest，不用 unittest
- 提交信息用英文，遵循 Conventional Commits

## 构建命令
- 安装：`pip install -e ".[dev]"`
- 测试：`pytest tests/ -q`
- Lint：`ruff check src/ tests/`

## 架构说明
- src/deepseek_cli/agent.py：代理循环
- src/deepseek_cli/tools.py：工具实现
- src/deepseek_cli/ui.py：TUI 界面
```

### 环境变量

- `DEEPSEEK_API_KEY`：必填，DeepSeek API Key。
- `DEEPSEEK_BASE_URL`：可选，默认 `https://api.deepseek.com`。
- `DEEPSEEK_MODEL`：可选，默认 `deepseek-v4-flash`。
- `DEEPSEEK_THEME`：可选，TUI 主题。

### DeepSeek 推理模式

复杂任务（架构分析、疑难 bug、多文件重构）可启用推理模式：

```bash
# 使用 deepseek-v4-pro 模型，带思考过程
deepseek --reasoning "分析这个项目的架构瓶颈并给出重构方案"

# 自定义思考预算
deepseek --reasoning --thinking-budget 8192 "调试这个并发死锁问题"
```

推理模式会显示模型的思考过程（reasoning_content），帮助你理解它的分析逻辑。

显式 `--model` 优先于配置和 `--reasoning` 的自动模型选择；预算从 CLI 或 `[reasoning].thinking_budget` 读取。目标服务是否接受推理预算参数仍需以所用模型/API 的兼容性验证为准。

### 费用统计

Rich、全屏和 `--plain` 交互模式中输入 `/cost` 查看当前进程的 token 用量，不产生 API 请求。流式请求会请求返回 usage，统计包括工具往返中的模型请求：

```
┌ usage & cost ─────────────────────┐
│ Requests: 12                      │
│ Prompt tokens: 45,230             │
│ Completion tokens: 8,112          │
│ Total tokens: 53,342              │
│ Estimated cost: ¥0.0615           │
│ (deepseek-flash)                  │
└───────────────────────────────────┘
```

费用使用内置近似系数：flash 输入 ¥1/百万 token，输出 ¥2/百万 token；v4-pro（推理）输入 ¥4，输出 ¥16，不等于实际账单。`/clear` 只清上下文，保留当前进程的累计统计；恢复保存会话不恢复历史费用统计。

### API 稳定性参数

- `--api-timeout SECONDS`：单次 API 请求超时，默认 120 秒。
- `--api-retries COUNT`：HTTP 429、5xx 和网络错误的重试次数，默认 3 次。

## 本地验证

```powershell
python -m pip install -e ".[dev]"
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
- 单文件二进制：release 时通过 PyInstaller 构建 `deepseek-windows-x64.zip`、`deepseek-macos-x64.zip`、`deepseek-linux-x64.zip`，并为每个压缩包附带 `.sha256` 校验文件。

真正发布到这些生态需要对应账号、release 产物和 SHA256 校验值。当前模板中带有 `REPLACE_WITH_*_SHA256` 占位符，发布 release 后替换即可提交到对应 registry。

自动生成并校验 SHA256：

```powershell
python scripts/update_release_hashes.py `
  --version 1.0.0 `
  --homebrew-tar .\dist\deepseek-cli-v1.0.0.tar.gz `
  --scoop-zip .\dist\deepseek-cli-v1.0.0.zip `
  --winget-windows-zip .\dist\deepseek-windows-x64.zip `
  --check
```

创建带自动 release notes 的 GitHub release：

```powershell
python scripts/create_release.py 1.0.0 --draft
```

发布到真实 registry 的辅助入口：

```powershell
python scripts/publish_registries.py --pypi
python scripts/publish_registries.py --homebrew-tap C:\path\to\homebrew-tap
python scripts/publish_registries.py --scoop-bucket C:\path\to\scoop-bucket
python scripts/publish_registries.py --winget-pkgs C:\path\to\winget-pkgs
```

这些命令会执行真实上传或复制 manifest 到对应 registry 仓库。PyPI 需要已配置凭据或 Trusted Publishing。

复制 manifest 后自动创建 registry PR：

```powershell
python scripts/publish_registries.py `
  --homebrew-tap C:\path\to\homebrew-tap `
  --scoop-bucket C:\path\to\scoop-bucket `
  --winget-pkgs C:\path\to\winget-pkgs `
  --version 1.0.0 `
  --open-pr
```

检查 PyPI/Homebrew/Scoop/winget 是否已经能检索到指定版本：

```powershell
python scripts/publish_registries.py --check-status --version 1.0.0
```

## 和 Codex CLI 看齐的方向

这个项目当前已经具备 Codex CLI 风格的基础能力：split-pane 全屏 TUI、可选主题、紧凑输出、长内容折叠展开、多轮对话、会话搜索与任务回放、流式输出、自动工具调用、本地文件编辑、命令执行、hunk 级 diff 审批、内置行级 diff UI、Git/PR 工作流、权限沙箱、可滚动日志、多文件 review、命令 allow/deny 策略、项目策略、按需安装工具、跨平台安装检查、单文件二进制构建、SHA256 模板回填、release notes 生成、registry PR 自动创建和 registry 发布状态检查。

## 支持与定制

社区问题和功能建议请通过 GitHub Issues 提交。私有部署、模型或内部
API 集成、权限策略定制、打包发布和约定响应时间的维护服务，请参阅
[SUPPORT.md](SUPPORT.md)。

安全问题请按照 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue
中披露凭据或可直接复现的高风险细节。
