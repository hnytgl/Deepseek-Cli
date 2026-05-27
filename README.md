# DeepSeek Codex CLI

A small Codex-style command line coding agent for DeepSeek. It uses DeepSeek's
OpenAI-compatible Chat Completions API, supports automatic tool calling, and can
read files, write files, patch text, list directories, and run shell commands in
the current workspace.

## Install

```powershell
git clone <your-repo-url>
cd "deepseek cli"
python -m pip install -e .
```

Set your API key:

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
```

On bash/zsh:

```bash
export DEEPSEEK_API_KEY="sk-..."
```

## Usage

Interactive mode:

```powershell
deepseek
```

Single task mode:

```powershell
deepseek "scan this repo and add a README"
```

Run in a target workspace:

```powershell
deepseek --cwd C:\path\to\project "fix the failing tests"
```

Automatically approve shell/file tools:

```powershell
deepseek --yes "implement the TODOs"
```

Use another DeepSeek model:

```powershell
deepseek --model deepseek-reasoner "explain this architecture"
```

## Tool Model

The agent exposes these tools to DeepSeek:

- `shell`: run a command in the workspace.
- `read_file`: read a UTF-8 text file.
- `write_file`: write a UTF-8 text file, creating parent directories.
- `replace_in_file`: replace exact text in a file.
- `list_dir`: list a directory.

By default, tools that mutate files or run shell commands ask for confirmation.
Pass `--yes` for fully automatic operation.

## Configuration

Environment variables:

- `DEEPSEEK_API_KEY`: required API key.
- `DEEPSEEK_BASE_URL`: optional, defaults to `https://api.deepseek.com`.
- `DEEPSEEK_MODEL`: optional, defaults to `deepseek-chat`.

CLI options override environment variables.

## Notes

This project intentionally keeps dependencies at zero. It uses Python's standard
library HTTP stack and plain terminal output so it is easy to install on fresh
developer machines.
