from __future__ import annotations

from pathlib import Path

from deepseek_cli import dbweakcheck


def test_read_word_file_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    word_file = tmp_path / "words.txt"
    word_file.write_text("\n# comment\nadmin\n\nroot\n", encoding="utf-8")

    assert dbweakcheck.read_word_file(word_file) == ["admin", "root"]


def test_collect_attempts_supports_single_and_dictionary_values(tmp_path: Path) -> None:
    password_file = tmp_path / "passwords.txt"
    password_file.write_text("admin123\nadmin123\nroot\n", encoding="utf-8")
    parser = dbweakcheck.build_parser()
    args = parser.parse_args(
        [
            "--authorize",
            "--db",
            "mysql",
            "--host",
            "127.0.0.1",
            "--user",
            "root",
            "--password",
            "toor",
            "--password-file",
            str(password_file),
            "--empty-password",
        ]
    )

    attempts = dbweakcheck.collect_attempts(args)

    assert attempts == [
        dbweakcheck.CredentialAttempt("root", ""),
        dbweakcheck.CredentialAttempt("root", "toor"),
        dbweakcheck.CredentialAttempt("root", "admin123"),
        dbweakcheck.CredentialAttempt("root", "root"),
    ]


def test_main_requires_authorization(capsys) -> None:
    code = dbweakcheck.main(["--db", "mysql", "--host", "127.0.0.1", "--user", "root", "--password", "root"])

    captured = capsys.readouterr()
    assert code == 2
    assert "--authorize is required" in captured.err


def test_dry_run_does_not_call_checker(capsys) -> None:
    def checker(target: dbweakcheck.TargetConfig, username: str, password: str) -> tuple[bool, str]:
        raise AssertionError("checker should not be called during dry run")

    code = dbweakcheck.main(
        [
            "--authorize",
            "--db",
            "redis",
            "--host",
            "127.0.0.1",
            "--user",
            "default",
            "--password",
            "redis",
            "--dry-run",
        ],
        checkers={"redis": checker},
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "Planned 1 attempt(s)" in captured.out


def test_found_password_is_masked_by_default(capsys) -> None:
    def checker(target: dbweakcheck.TargetConfig, username: str, password: str) -> tuple[bool, str]:
        return password == "secret", "login accepted"

    code = dbweakcheck.main(
        [
            "--authorize",
            "--db",
            "postgresql",
            "--host",
            "db.internal",
            "--user",
            "postgres",
            "--password",
            "secret",
            "--fail-on-found",
        ],
        checkers={"postgresql": checker},
    )

    captured = capsys.readouterr()
    assert code == 3
    assert "s****t" in captured.out
    assert "password='secret'" not in captured.out


def test_reveal_password_prints_raw_password(capsys) -> None:
    def checker(target: dbweakcheck.TargetConfig, username: str, password: str) -> tuple[bool, str]:
        return True, "login accepted"

    code = dbweakcheck.main(
        [
            "--authorize",
            "--db",
            "mysql",
            "--host",
            "localhost",
            "--user",
            "root",
            "--password",
            "root",
            "--reveal-password",
        ],
        checkers={"mysql": checker},
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "password='root'" in captured.out
