"""PR #8 acceptance regressions, with fake API responses and temporary projects."""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deepseek_cli.agent import AgentConfig, DeepSeekAgent, build_system_prompt
from deepseek_cli.api import DeepSeekClient
from deepseek_cli.cli import build_parser, create_agent, main, run_interactive
from deepseek_cli.config import ConfigError, _load_agents_md, load_config
from deepseek_cli.policy import PermissionConfig, PolicyViolation
from deepseek_cli.session import SessionStore
from deepseek_cli.tools import ToolExecutor


@pytest.fixture
def project(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    directory = workspace / ".deepseek-cli"
    directory.mkdir()
    user = tmp_path / "user.toml"
    monkeypatch.setattr("deepseek_cli.config.user_config_path", lambda: user)
    for name in ("DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL", "DEEPSEEK_THEME", "DEEPSEEK_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "acceptance-fake-key")
    monkeypatch.setattr(SessionStore, "default", classmethod(lambda cls: cls(tmp_path / "sessions")))
    return SimpleNamespace(cwd=workspace, config=directory / "config.toml", user=user, directory=directory)


def make_agent(project, *flags):
    return create_agent(build_parser().parse_args(["--cwd", str(project.cwd), "--sandbox-mode", "none", *flags]))


FILE_EDITS = [
    ("write_file", {"path": "sample.txt", "content": "after\n"}),
    ("replace_in_file", {"path": "sample.txt", "old": "before", "new": "after"}),
    ("patch_file", {"path": "sample.txt", "patch": "--- a/sample.txt\n+++ b/sample.txt\n@@ -1 +1 @@\n-before\n+after\n"}),
    ("apply_file_edits", {"files": [{"path": "sample.txt", "content": "after\n"}]}),
]


@pytest.mark.parametrize("name,arguments", FILE_EDITS)
def test_auto_edit_approves_all_file_edit_paths(project, name, arguments):
    path = project.cwd / "sample.txt"
    path.write_text("before\n", encoding="utf-8")
    agent = make_agent(project, "--approval", "auto-edit")
    def unexpected(*args):
        pytest.fail("auto-edit requested approval for a file change")
    agent.tools.ask = unexpected
    agent.tools.approve_diff = unexpected
    agent.tools.approve_file_edits = unexpected
    agent.tools.approve_hunks = unexpected
    result = agent.tools.run(name, arguments)
    assert result.ok, result.output
    assert path.read_text(encoding="utf-8") == "after\n"
    assert path in agent.tools.modified_files


@pytest.mark.parametrize("approved", [False, True])
def test_auto_edit_shell_waits_for_approval(project, monkeypatch, approved):
    agent = make_agent(project, "--approval", "auto-edit")
    approvals, executions = [], []
    agent.tools.ask = lambda prompt: approvals.append(prompt) or approved
    def run(command, **kwargs):
        executions.append(command)
        return subprocess.CompletedProcess(command, 0, "marker", "")
    monkeypatch.setattr("deepseek_cli.tools.subprocess.run", run)
    result = agent.tools.run("shell", {"command": "echo marker"})
    assert len(approvals) == 1
    assert result.ok is approved
    assert len(executions) == int(approved)


@pytest.mark.parametrize("flags,expected", [
    (["--approval", "full-auto"], "auto"), (["--approval", "auto"], "auto"),
    (["--yes"], "auto"), (["--approval", "suggest"], "read-only"),
    (["--approval", "read-only"], "read-only"), (["--approval", "ask"], "ask"),
    (["--yes", "--approval", "suggest"], "read-only"),
])
def test_approval_aliases_and_conflicting_yes(project, flags, expected):
    agent = make_agent(project, *flags)
    assert agent.tools.policy.approval == expected
    assert agent.tools.auto_approve is (expected == "auto")
    if expected == "read-only":
        assert not agent.tools.run("write_file", {"path": "forbidden.txt", "content": "bad"}).ok
        assert not (project.cwd / "forbidden.txt").exists()


def test_project_config_and_profile_cannot_grant_permissions(project):
    project.config.write_text('approval="full-auto"\nsandbox="unrestricted"\nactive_profile="unsafe"\n[profiles.unsafe]\napproval="full-auto"\nsandbox="unrestricted"\n', encoding="utf-8")
    agent = make_agent(project)
    assert agent.tools.policy.approval == "ask"
    assert not agent.tools.auto_approve
    assert agent.tools.policy.sandbox == "workspace"
    outside = project.cwd.parent / "outside.txt"
    assert not agent.tools.run("write_file", {"path": str(outside), "content": "bad"}).ok
    assert not outside.exists()


def test_project_restrictions_apply_even_to_yes(project):
    (project.directory / "policy.json").write_text(json.dumps({"approval": "read-only", "sandbox": "workspace", "shell": False}), encoding="utf-8")
    agent = make_agent(project, "--yes", "--sandbox", "unrestricted")
    assert agent.tools.policy.read_only
    assert not agent.tools.auto_approve
    assert not agent.tools.auto_edit
    assert not agent.tools.run("shell", {"command": "echo denied"}).ok


def test_project_cannot_select_a_privileged_user_profile(project):
    project.user.write_text('[profiles.privileged]\napproval="full-auto"\nsandbox="unrestricted"\n', encoding="utf-8")
    project.config.write_text('active_profile="privileged"', encoding="utf-8")
    agent = make_agent(project)
    assert agent.tools.policy.approval == "ask"
    assert agent.tools.policy.sandbox == "workspace"
    assert make_agent(project, "--profile", "privileged").tools.auto_approve


def test_user_auto_edit_is_allowed_but_project_ask_restricts(project):
    project.user.write_text('approval="auto-edit"\n', encoding="utf-8")
    assert make_agent(project).tools.auto_edit
    project.config.write_text('approval="ask"\n', encoding="utf-8")
    assert not make_agent(project).tools.auto_edit


def test_command_constraints_intersect_and_denies_accumulate(project):
    project.user.write_text('[shell]\nallow=["git", "python.exe"]\ndeny=["sudo"]\n', encoding="utf-8")
    project.config.write_text('[shell]\nallow=["PYTHON", "npm"]\ndeny=["curl"]\n', encoding="utf-8")
    policy = make_agent(project).tools.policy
    policy.check_command("python --version")
    for command in ("git status", "npm --version", "sudo true", "curl example.invalid"):
        with pytest.raises(PolicyViolation):
            policy.check_command(command)
    assert set(policy.deny_commands) == {"sudo", "curl"}
    project.config.write_text('[shell]\nallow=["npm"]\n', encoding="utf-8")
    assert not make_agent(project).tools.policy.shell


def test_show_policy_matches_runtime_without_api_key(project, monkeypatch, capsys):
    project.user.write_text('approval="auto-edit"\n[shell]\nallow=["python"]\n', encoding="utf-8")
    expected = make_agent(project).tools.policy.to_dict()
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert main(["--cwd", str(project.cwd), "--show-policy"]) == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_model_precedence_and_profile_environment_override(project, monkeypatch):
    project.user.write_text('model="user"\n[profiles.fast]\nmodel="user-profile"\n', encoding="utf-8")
    assert make_agent(project).client.model == "user"
    project.config.write_text('model="project"\n[profiles.fast]\nmodel="project-profile"\n', encoding="utf-8")
    assert make_agent(project).client.model == "project"
    assert make_agent(project, "--profile", "fast").client.model == "project-profile"
    monkeypatch.setenv("DEEPSEEK_MODEL", "env")
    assert make_agent(project, "--profile", "fast").client.model == "env"
    assert make_agent(project, "--profile", "fast", "--model", "cli").client.model == "cli"


def test_persisted_runtime_and_ui_preferences(project):
    project.config.write_text('max_steps=17\nmax_context_chars=12345\ntemperature=0.0\nstream=false\nquiet=true\ntheme="ocean"\nlayout="stacked"\nexpanded_output=true\n[reasoning]\nthinking_budget=1024\n', encoding="utf-8")
    args = build_parser().parse_args(["--cwd", str(project.cwd), "--sandbox-mode", "none"])
    agent = create_agent(args)
    assert (agent.config.max_steps, agent.config.max_context_chars, agent.config.temperature, agent.config.stream, agent.config.thinking_budget) == (17, 12345, 0.0, False, 1024)
    assert agent.config.quiet
    assert (args.theme, args.layout, args.expanded_output) == ("ocean", "stacked", True)
    overridden = make_agent(project, "--max-steps", "19", "--temperature", "0.3", "--thinking-budget", "8192")
    assert (overridden.config.max_steps, overridden.config.temperature, overridden.config.thinking_budget) == (19, 0.3, 8192)


def test_reasoning_does_not_override_explicit_cli_model(project, monkeypatch):
    project.config.write_text('[reasoning]\nenabled=true\nmodel="configured-reasoner"\n', encoding="utf-8")
    assert make_agent(project).client.model == "configured-reasoner"
    assert make_agent(project, "--model", "explicit-model").client.model == "explicit-model"
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    assert make_agent(project).client.model == "env-model"
    assert make_agent(project, "--reasoning").client.model == "configured-reasoner"


@pytest.mark.parametrize("text", ['model = "unterminated', 'theme="dark"', 'max_steps=0', '[reasoning]\nthinking_budget=-1'])
def test_invalid_config_is_reported_before_network(project, text, capsys):
    project.config.write_text(text, encoding="utf-8")
    assert main(["--cwd", str(project.cwd), "--plain", "hello"]) == 2
    assert "Error:" in capsys.readouterr().err


def test_missing_toml_parser_does_not_silently_ignore_config(project, monkeypatch):
    project.config.write_text('model="configured"', encoding="utf-8")
    monkeypatch.setattr("deepseek_cli.config.tomllib", None)
    with pytest.raises(ConfigError, match="TOML support"):
        load_config(project.cwd)


def test_agents_priority_character_limit_and_empty_fallback(project):
    root = project.cwd / "AGENTS.md"
    nested = project.directory / "AGENTS.md"
    fallback = project.cwd / "DEEPSEEK.md"
    root.write_text("石" * 9000, encoding="utf-8")
    nested.write_text("NESTED", encoding="utf-8")
    fallback.write_text("FALLBACK", encoding="utf-8")
    assert _load_agents_md(project.cwd) == "石" * 8192
    root.write_text("", encoding="utf-8")
    assert _load_agents_md(project.cwd) == "NESTED"
    nested.unlink()
    assert _load_agents_md(project.cwd) == "FALLBACK"


def test_session_resume_refreshes_project_rules_and_removes_old_system(project):
    store = SessionStore.default()
    store.save("resume", [{"role": "system", "content": "OLD_RULE"}, {"role": "user", "content": "history"}], cwd=project.cwd, model="test")
    rules = project.cwd / "AGENTS.md"
    rules.write_text("NEW_RULE", encoding="utf-8")
    agent = make_agent(project, "--session", "resume")
    assert "NEW_RULE" in agent.messages[0]["content"]
    assert "OLD_RULE" not in agent.messages[0]["content"]
    rules.unlink()
    agent.restore_messages(store.load("resume"))
    assert agent.messages[0]["content"] == build_system_prompt()
    assert agent.messages[-1]["content"] == "history"


def test_plain_cost_and_replay_do_not_call_model(project, monkeypatch, capsys):
    agent = make_agent(project)
    (project.cwd / "AGENTS.md").write_text("CURRENT_RULE", encoding="utf-8")
    SessionStore.default().save("replay", [{"role": "system", "content": "STALE_RULE"}], cwd=project.cwd, model="test")
    prompts = iter(["/replay replay", "/cost", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(prompts))
    monkeypatch.setattr(agent, "run_turn", lambda prompt: pytest.fail("Local command called the API"))
    assert run_interactive(agent) == 0
    assert "Requests: 0" in capsys.readouterr().out
    assert "CURRENT_RULE" in agent.messages[0]["content"]
    assert "STALE_RULE" not in agent.messages[0]["content"]


@pytest.mark.parametrize("name,arguments", FILE_EDITS)
def test_all_edit_paths_preserve_crlf(project, name, arguments):
    path = project.cwd / "sample.txt"
    path.write_bytes(b"before\r\n")
    result = ToolExecutor(project.cwd, auto_approve=True).run(name, arguments)
    assert result.ok, result.output
    assert path.read_bytes() == b"after\r\n"


def test_invalid_patch_does_not_write_or_request_approval(project):
    path = project.cwd / "sample.txt"
    path.write_bytes(b"before\r\n")
    executor = ToolExecutor(project.cwd, ask=lambda prompt: pytest.fail("Invalid patch requested approval"))
    for patch in ("@@ -1,2 +1 @@\n-before\n+after\n", "@@ -1 +1 @@\n-wrong\n+after\n"):
        assert not executor.run("patch_file", {"path": "sample.txt", "patch": patch}).ok
        assert path.read_bytes() == b"before\r\n"


def test_patch_insert_at_start_uses_zero_count_position(project):
    path = project.cwd / "sample.txt"
    path.write_text("last\n", encoding="utf-8")
    result = ToolExecutor(project.cwd, auto_approve=True).run("patch_file", {"path": "sample.txt", "patch": "@@ -0,0 +1 @@\n+first\n"})
    assert result.ok, result.output
    assert path.read_text(encoding="utf-8") == "first\nlast\n"


def test_usage_stream_snapshot_counted_once_and_nonstream_accumulates(project):
    class Fake:
        model = "deepseek-v4-pro"
        def chat_stream(self, payload):
            assert payload["thinking"]["budget_tokens"] == 1024
            yield {"choices": [{"delta": {"reasoning_content": "thinking", "content": "answer"}}]}
            for _ in range(2):
                yield {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}
        def chat(self, payload):
            return {"choices": [{"message": {"content": "second"}}], "usage": {"prompt_tokens": 500, "completion_tokens": 50}}
    agent = DeepSeekAgent(client=Fake(), tools=ToolExecutor(project.cwd), config=AgentConfig(cwd=project.cwd, thinking_budget=1024))
    assert agent.run_turn("first") == "answer"
    assert agent.messages[-1]["reasoning_content"] == "thinking"
    assert (agent.total_requests, agent.total_prompt_tokens, agent.total_completion_tokens) == (1, 1000, 100)
    assert "¥0.0056" in agent.get_usage_summary()
    agent.config.stream = False
    agent.run_turn("second")
    assert (agent.total_requests, agent.total_prompt_tokens, agent.total_completion_tokens) == (2, 1500, 150)


def test_streaming_client_requests_usage_only_chunk(monkeypatch):
    requests = []
    def open_request(request, **kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(b'data: {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}\n\ndata: [DONE]\n')
    monkeypatch.setattr("deepseek_cli.api.urllib.request.urlopen", open_request)
    events = list(DeepSeekClient("fake-key").chat_stream({"messages": []}))
    assert requests[0]["stream_options"]["include_usage"] is True
    assert events[0]["usage"]["prompt_tokens"] == 2


def test_json_output_remains_parseable_when_tools_execute(project, monkeypatch, capsys):
    (project.cwd / "sample.txt").write_text("value", encoding="utf-8")
    responses = iter([
        {"choices": [{"message": {"tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"sample.txt"}'}}]}}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}},
        {"choices": [{"message": {"content": "done"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
    ])
    monkeypatch.setattr(DeepSeekClient, "chat", lambda self, payload: next(responses))
    assert main(["--cwd", str(project.cwd), "--sandbox-mode", "none", "--no-stream", "--json", "read sample"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["answer"] == "done"
    assert output["usage"] == {"prompt_tokens": 5, "completion_tokens": 2, "total_requests": 2}


def test_api_key_is_hidden_in_client_and_config_repr(project):
    assert "fake-secret-marker" not in repr(DeepSeekClient("fake-secret-marker"))
    project.user.write_text('api_key="fake-secret-marker"', encoding="utf-8")
    assert "fake-secret-marker" not in repr(load_config(project.cwd))
