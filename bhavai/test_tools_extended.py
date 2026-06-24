import pytest
import subprocess
from pathlib import Path

import bhavai.tools as tools_mod
import bhavai.tools_extended as ext_mod
import bhavai.config as config_mod
from bhavai.tools_extended import (
    search_code,
    find_files,
    get_outline,
    list_todos,
    get_diff,
    check_dependencies,
    rename_path,
    fetch_url,
)


@pytest.fixture(autouse=True)
def mock_cwd(tmp_path, monkeypatch):
    """Same pattern as test_tools.py — sandbox every test to a tmp_path CWD."""
    resolved_tmp = tmp_path.resolve()
    monkeypatch.setattr(tools_mod, "CWD", resolved_tmp)
    monkeypatch.setattr(ext_mod, "CWD", resolved_tmp)
    monkeypatch.setattr(config_mod, "CWD", resolved_tmp)
    return resolved_tmp


def _git_init(cwd: Path):
    subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=cwd, check=True)


# ─────────────────────────────────────────────────────────────────────────────
# search_code
# ─────────────────────────────────────────────────────────────────────────────

def test_search_code_literal(mock_cwd):
    (mock_cwd / "a.py").write_text("def foo():\n    return user_id\n")
    result = search_code("user_id", ".")
    assert "a.py:2" in result
    assert "user_id" in result


def test_search_code_regex(mock_cwd):
    (mock_cwd / "a.py").write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")
    result = search_code(r"def \w+\(", ".", regex=True)
    assert "foo" in result and "bar" in result


def test_search_code_no_matches(mock_cwd):
    (mock_cwd / "a.py").write_text("nothing here\n")
    result = search_code("zzz_not_present", ".")
    assert "No matches" in result


def test_search_code_never_leaks_env(mock_cwd):
    (mock_cwd / ".env").write_text("SECRET_KEY=hunter2\n")
    (mock_cwd / "a.py").write_text("# nothing\n")
    result = search_code("hunter2", ".")
    assert "No matches" in result


def test_search_code_invalid_regex(mock_cwd):
    (mock_cwd / "a.py").write_text("hello\n")
    result = search_code("(unclosed[", ".", regex=True)
    assert "invalid regex" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# find_files
# ─────────────────────────────────────────────────────────────────────────────

def test_find_files_glob(mock_cwd):
    (mock_cwd / "test_foo.py").write_text("x")
    (mock_cwd / "bar.py").write_text("x")
    (mock_cwd / "readme.md").write_text("x")
    result = find_files("test_*.py")
    assert "test_foo.py" in result
    assert "bar.py" not in result


def test_find_files_excludes_env(mock_cwd):
    (mock_cwd / ".env").write_text("SECRET=1")
    result = find_files("*")
    assert ".env" not in result


def test_find_files_no_match(mock_cwd):
    (mock_cwd / "a.py").write_text("x")
    result = find_files("*.nonexistent_ext")
    assert "No files matching" in result


# ─────────────────────────────────────────────────────────────────────────────
# get_outline
# ─────────────────────────────────────────────────────────────────────────────

def test_get_outline_python(mock_cwd):
    (mock_cwd / "a.py").write_text(
        "class Foo:\n"
        "    def method_a(self):\n"
        "        pass\n"
        "\n"
        "def standalone():\n"
        "    pass\n"
    )
    result = get_outline("a.py")
    assert "class Foo" in result
    assert "def method_a(self)" in result
    assert "def standalone()" in result


def test_get_outline_syntax_error(mock_cwd):
    (mock_cwd / "broken.py").write_text("def foo(:\n  pass\n")
    result = get_outline("broken.py")
    assert "syntax error" in result.lower()


def test_get_outline_denies_env(mock_cwd):
    (mock_cwd / ".env").write_text("SECRET=1")
    result = get_outline(".env")
    assert "Access Denied" in result


def test_get_outline_nonexistent(mock_cwd):
    result = get_outline("ghost.py")
    assert "does not exist" in result


# ─────────────────────────────────────────────────────────────────────────────
# list_todos
# ─────────────────────────────────────────────────────────────────────────────

def test_list_todos_finds_markers(mock_cwd):
    (mock_cwd / "a.py").write_text(
        "# TODO: fix this later\n"
        "x = 1\n"
        "# FIXME: broken on windows\n"
    )
    result = list_todos(".")
    assert "[TODO]" in result
    assert "fix this later" in result
    assert "[FIXME]" in result


def test_list_todos_clean_project(mock_cwd):
    (mock_cwd / "a.py").write_text("x = 1\n")
    result = list_todos(".")
    assert "Clean" in result


# ─────────────────────────────────────────────────────────────────────────────
# get_diff
# ─────────────────────────────────────────────────────────────────────────────

def test_get_diff_shows_changes(mock_cwd):
    _git_init(mock_cwd)
    (mock_cwd / "a.py").write_text("line1\n")
    subprocess.run(["git", "add", "."], cwd=mock_cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=mock_cwd, check=True)

    (mock_cwd / "a.py").write_text("line1\nline2\n")
    result = get_diff("a.py")
    assert "line2" in result


def test_get_diff_no_changes(mock_cwd):
    _git_init(mock_cwd)
    (mock_cwd / "a.py").write_text("line1\n")
    subprocess.run(["git", "add", "."], cwd=mock_cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=mock_cwd, check=True)

    result = get_diff("a.py")
    assert "No uncommitted changes" in result


def test_get_diff_denies_env(mock_cwd):
    _git_init(mock_cwd)
    (mock_cwd / ".env").write_text("SECRET=1")
    result = get_diff(".env")
    assert "Access Denied" in result


# ─────────────────────────────────────────────────────────────────────────────
# check_dependencies
# ─────────────────────────────────────────────────────────────────────────────

def test_check_dependencies_requirements_txt(mock_cwd):
    (mock_cwd / "requirements.txt").write_text(
        "requests>=2.0\nthis-package-does-not-exist-xyz\n"
    )
    result = check_dependencies(".")
    assert "requests" in result
    assert "this-package-does-not-exist-xyz" in result
    assert "Missing" in result
    assert "pip install" in result


def test_check_dependencies_nothing_found(mock_cwd):
    result = check_dependencies(".")
    assert "No requirements.txt" in result


def test_check_dependencies_package_json(mock_cwd):
    (mock_cwd / "package.json").write_text(
        '{"dependencies": {"left-pad": "1.0.0"}}'
    )
    result = check_dependencies(".")
    assert "left-pad" in result
    assert "Missing" in result or "node_modules" in result


# ─────────────────────────────────────────────────────────────────────────────
# rename_path
# ─────────────────────────────────────────────────────────────────────────────

def test_rename_path_moves_file(mock_cwd):
    _git_init(mock_cwd)
    (mock_cwd / "old.txt").write_text("content")
    result = rename_path("old.txt", "new.txt")
    assert "Moved" in result
    assert not (mock_cwd / "old.txt").exists()
    assert (mock_cwd / "new.txt").exists()
    assert (mock_cwd / "new.txt").read_text() == "content"


def test_rename_path_refuses_overwrite(mock_cwd):
    (mock_cwd / "a.txt").write_text("a")
    (mock_cwd / "b.txt").write_text("b")
    result = rename_path("a.txt", "b.txt")
    assert "already exists" in result
    # Source must NOT have been touched — zero-deletion guarantee
    assert (mock_cwd / "a.txt").exists()
    assert (mock_cwd / "a.txt").read_text() == "a"


def test_rename_path_missing_source(mock_cwd):
    result = rename_path("ghost.txt", "dest.txt")
    assert "does not exist" in result


def test_rename_path_denies_env(mock_cwd):
    (mock_cwd / ".env").write_text("SECRET=1")
    result = rename_path(".env", "leaked.txt")
    assert "Access Denied" in result
    assert (mock_cwd / ".env").exists()  # never moved


def test_rename_path_creates_parent_dirs(mock_cwd):
    (mock_cwd / "a.txt").write_text("content")
    result = rename_path("a.txt", "nested/deep/a.txt")
    assert "Moved" in result
    assert (mock_cwd / "nested" / "deep" / "a.txt").exists()


# ─────────────────────────────────────────────────────────────────────────────
# fetch_url
# ─────────────────────────────────────────────────────────────────────────────

def test_fetch_url_rejects_non_http_scheme():
    result = fetch_url("ftp://example.com/file")
    assert "only http://" in result.lower()


def test_fetch_url_rejects_file_scheme():
    result = fetch_url("file:///etc/passwd")
    assert "only http://" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox enforcement across all new tools (shared validate_path contract)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("call", [
    lambda: search_code("x", "/etc"),
    lambda: find_files("*", "/etc"),
    lambda: get_outline("/etc/passwd"),
    lambda: list_todos("/etc"),
    lambda: rename_path("/etc/passwd", "stolen.txt"),
])
def test_new_tools_reject_path_traversal(mock_cwd, call):
    with pytest.raises(ValueError):
        call()