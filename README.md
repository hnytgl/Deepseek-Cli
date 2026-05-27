# DeepSeek Codex CLI

一个参考 Codex CLI 体验、完全适配 DeepSeek API 的命令行编程代理。它可以在终端里对话、读取和修改项目文件、运行命令、自动调用工具，并用窗口化界面展示任务过程、当前进度、工具日志和模型思考内容。

## 功能特性

- 适配 DeepSeek OpenAI-compatible Chat Completions API。
- 支持 `deepseek-chat` 和 `deepseek-reasoner` 等 DeepSeek 模型。
- 终端窗口式交互界面，显示进度、状态、工具调用和最终回复。
- 支持多轮对话，能持续理解当前任务上下文。
- 自动工具调用：读文件、写文件、替换文本、列目录、运行 shell 命令。
- 默认在执行 shell 或写文件前询问确认；可用 `--yes` 开启全自动模式。
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

## 交互命令

进入 `deepseek` 后可以使用这些命令：

- `/help`：显示帮助。
- `/clear`：清空当前对话上下文。
- `/exit` 或 `/quit`：退出。

直接输入自然语言任务即可，例如：

```text
帮我检查这个仓库有什么问题，并修复能自动修复的部分
```

## 工具能力

DeepSeek 可以自动调用这些本地工具：

- `shell`：在当前工作区运行命令。
- `read_file`：读取 UTF-8 文本文件。
- `write_file`：写入 UTF-8 文本文件，并自动创建父目录。
- `replace_in_file`：在文件中替换精确文本。
- `list_dir`：列出目录内容。

默认情况下，写文件、替换文件和运行 shell 命令会先询问确认。传入 `--yes` 后会自动批准工具执行，适合你明确希望它连续完成编程任务的场景。

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
```

## 和 Codex CLI 看齐的方向

这个项目当前已经具备 Codex CLI 风格的基础能力：终端 TUI、多轮对话、自动工具调用、本地文件编辑和命令执行。后续可以继续增强：

- 流式输出模型回复。
- 更细的文件 diff 预览和批准流程。
- Git 状态感知、自动分支、提交和 PR 创建。
- 会话持久化和历史恢复。
- 更完整的沙箱策略和权限配置。
