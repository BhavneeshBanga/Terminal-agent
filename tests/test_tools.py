import pytest
from pathlib import Path
import bhavai.tools
import bhavai.config
from bhavai.tools import (
    validate_path,
    validate_command,
    list_folder,
    read_file,
    write_file,
    update_file,
    run_command
)

@pytest.fixture(autouse=True)
def mock_cwd(tmp_path, monkeypatch):
    """
    Automatically mock CWD globally in config and tools.
    This guarantees tests never read/write to the host workspace folder directly.
    """
    resolved_tmp = tmp_path.resolve()
    monkeypatch.setattr(bhavai.tools, "CWD", resolved_tmp)
    monkeypatch.setattr(bhavai.config, "CWD", resolved_tmp)
    return resolved_tmp

def test_sandbox_validation_within_cwd(mock_cwd):
    """Verifies that paths resolved within CWD are valid."""
    path = validate_path("test.txt")
    assert path == mock_cwd / "test.txt"
    
    subfolder_path = validate_path("sub/folder/file.py")
    assert subfolder_path == mock_cwd / "sub" / "folder" / "file.py"

def test_sandbox_validation_outside_cwd():
    """Verifies that path resolution outside CWD triggers ValueError."""
    # Attempting to climb out using parent segments
    with pytest.raises(ValueError) as exc:
        validate_path("../outside.txt")
    assert "is outside the sandboxed working directory" in str(exc.value)
    
    # Attempting to access root or other system directories
    with pytest.raises(ValueError):
        validate_path("/etc/passwd")

def test_command_blocklist_validation():
    """Verifies that dangerous commands are detected and raise ValueError."""
    # Strict matching
    with pytest.raises(ValueError):
        validate_command("rm -rf .")
    with pytest.raises(ValueError):
        validate_command("shutil.rmtree('foo')")
    with pytest.raises(ValueError):
        validate_command("del file.txt")
    with pytest.raises(ValueError):
        validate_command("drop table users;")
        
    # Safe commands should pass
    validate_command("git status")
    validate_command("ls -la")
    validate_command("cat pyproject.toml")
    
    # Word boundary validation (do not block words that contain prefixes)
    validate_command("echo formatting code") # format is inside formatting

def test_write_and_read_file(mock_cwd):
    """Tests writing file content and reading it back."""
    write_result = write_file("docs/api.md", "# API Documentation")
    assert "Success" in write_result
    assert (mock_cwd / "docs" / "api.md").exists()
    
    read_result = read_file("docs/api.md")
    assert read_result == "# API Documentation"

def test_read_non_existent_file():
    """Tests handling of reading non-existent files."""
    result = read_file("missing_file.txt")
    assert "does not exist" in result

def test_update_file(mock_cwd):
    """Tests update_file append and overwrite modes."""
    # Initial write
    write_file("test.txt", "line 1\n")
    
    # Append content
    append_result = update_file("test.txt", "line 2\n", mode="append")
    assert "Success" in append_result
    
    # Read back to verify append
    content = read_file("test.txt")
    assert content == "line 1\nline 2\n"
    
    # Overwrite content
    overwrite_result = update_file("test.txt", "new line\n", mode="overwrite")
    assert "Success" in overwrite_result
    
    # Read back to verify overwrite
    content = read_file("test.txt")
    assert content == "new line\n"

def test_list_folder(mock_cwd):
    """Tests retrieving folder directory listings."""
    # Write some files
    write_file("a.txt", "file a")
    write_file("folder_b/c.txt", "file c")
    
    tree = list_folder(".")
    assert "a.txt" in tree
    assert "folder_b/" in tree
    assert "c.txt" in tree

def test_run_command_safe(mock_cwd):
    """Tests executing safe shell commands."""
    # Write a test file
    write_file("test.txt", "testing commands")
    
    # Execute a simple echo command (cross platform check if possible, or simple echo)
    result = run_command("echo Hello World")
    assert "Hello World" in result
    
    # Attempting to run a blocked command via run_command
    blocked_result = run_command("rm -rf test.txt")
    assert "Security Violation" in blocked_result

def test_run_command_timeout(mock_cwd):
    """Tests executing a command that exceeds the timeout limit and checks captured partial output."""
    import sys
    python_exe = sys.executable
    # Python script that prints unbuffered and then sleeps longer than our 10-second timeout
    cmd = f'"{python_exe}" -u -c "import time; print(\'Started\'); time.sleep(20); print(\'Finished\')"'
    
    result = run_command(cmd)
    
    assert "timed out (10s limit)" in result
    assert "Stdout before timeout:" in result
    assert "Started" in result
    assert "Finished" not in result

def test_clean_json_text():
    from bhavai.agent import clean_json_text, parse_llm_json
    
    # Test stripping think tags
    raw_input_1 = (
        "<think>I need to run the final answer tool.</think>\n"
        "{\n"
        '  "thought": "Ready to respond",\n'
        '  "tool_name": "final_answer",\n'
        '  "tool_args": {"answer": "Task done"}\n'
        "}"
    )
    cleaned_1 = clean_json_text(raw_input_1)
    assert "<think>" not in cleaned_1
    assert "Ready to respond" in cleaned_1
    
    parsed_1 = parse_llm_json(raw_input_1)
    assert parsed_1["thought"] == "Ready to respond"
    assert parsed_1["tool_name"] == "final_answer"
    
    # Test escaping raw newlines inside string literals
    raw_input_2 = (
        "{\n"
        '  "thought": "Update HTML",\n'
        '  "tool_name": "update_file",\n'
        '  "tool_args": {\n'
        '    "path": "templates/index.html",\n'
        '    "content": "<!DOCTYPE html>\n'
        '<html lang=\\"en\\">\n'
        '<head>\n'
        '  <title>Title</title>\n'
        '</head>\n'
        '</html>"\n'
        "  }\n"
        "}"
    )
    parsed_2 = parse_llm_json(raw_input_2)
    assert parsed_2["tool_args"]["path"] == "templates/index.html"
    assert "<!DOCTYPE html>\n<html lang=\"en\">\n<head>" in parsed_2["tool_args"]["content"]

def test_git_initialization(mock_cwd):
    """Tests that git is automatically initialized when reading or writing files."""
    # Ensure CWD starts with no git repo and no gitignore
    assert not (mock_cwd / ".git").exists()
    assert not (mock_cwd / ".gitignore").exists()
    
    # Run a write_file tool
    write_result = write_file("test_git.txt", "git test content")
    assert "Success" in write_result
    
    # Assert git repo and gitignore are created
    assert (mock_cwd / ".git").exists()
    assert (mock_cwd / ".gitignore").exists()
    
    # Check git status or log to confirm initial commit was made
    import subprocess
    res = subprocess.run(["git", "log", "--oneline"], cwd=mock_cwd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Initial commit" in res.stdout




