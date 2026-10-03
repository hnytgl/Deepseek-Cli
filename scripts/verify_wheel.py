"""Install the built wheel in a clean venv and validate its runtime dependencies."""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tempfile
import venv


PROBE = r'''
import pathlib
import tempfile
from unittest.mock import patch
from deepseek_cli import config
from deepseek_cli.cli import build_parser, create_agent

with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    (root / '.deepseek-cli').mkdir()
    (root / '.deepseek-cli' / 'config.toml').write_text(
        'model="wheel-model"\nmax_steps=17\nstream=false\n[reasoning]\nthinking_budget=1024\n', encoding='utf-8')
    (root / 'AGENTS.md').write_text('WHEEL_PROJECT_RULE', encoding='utf-8')
    with patch.object(config, 'user_config_path', return_value=root / 'no-user.toml'), patch.dict(
        'os.environ', {'DEEPSEEK_API_KEY': 'wheel-fake-key'}, clear=True
    ):
        args = build_parser().parse_args(['--cwd', str(root), '--sandbox-mode', 'none', '--approval', 'auto-edit'])
        agent = create_agent(args)
    assert agent.client.model == 'wheel-model'
    assert agent.config.max_steps == 17
    assert not agent.config.stream
    assert agent.config.thinking_budget == 1024
    assert 'WHEEL_PROJECT_RULE' in agent.messages[0]['content']
    def reject(*args):
        raise AssertionError('auto-edit requested file approval')
    agent.tools.approve_hunks = reject
    result = agent.tools.run('apply_file_edits', {'files': [{'path': 'created.txt', 'content': 'wheel\n'}]})
    assert result.ok, result.output
    assert (root / 'created.txt').read_text(encoding='utf-8') == 'wheel\n'
print('Clean wheel acceptance passed')
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doctor", action="store_true", help="Also require git and gh on the CI runner.")
    args = parser.parse_args()
    wheels = list(pathlib.Path("dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected exactly one wheel in dist; remove stale builds first.")
    wheel = wheels[0].resolve()
    with tempfile.TemporaryDirectory(prefix="deepseek-wheel-") as directory:
        root = pathlib.Path(directory)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], cwd=root, check=True)
        subprocess.run([str(python), "-I", "-c", PROBE], cwd=root, check=True)
        for command in ("--help", "--version", *( ("--doctor",) if args.doctor else () )):
            subprocess.run([str(python), "-I", "-m", "deepseek_cli", command], cwd=root, check=True)


if __name__ == "__main__":
    main()
