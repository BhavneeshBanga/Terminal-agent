"""
tools_extended.py — Additional real-world tools for the BhavAI agent.

Why this exists as a separate file (not bolted onto tools.py)
---------------------------------------------------------------
tools.py owns the core file-write primitives (write_file, append_chunk,
run_command) and the security plumbing (validate_path, validate_command,
git init/staging). Those are the load-bearing walls — touching that file
for every new tool risks breaking the 4096-token chunking story.

This file owns *read-oriented* and *navigation* tools: the things a real
developer or student actually reaches for once they've handed a codebase
to an agent — "find where X is defined", "what changed", "what's left
to do", "is this dependency even installed". None of these write files,
so the blast radius of a bug here is zero risk to the user's code.

All tools below reuse tools.py's validate_path / CWD / git plumbing so
the sandbox and zero-deletion guarantees apply identically here.

New tools in this file
-----------------------
  search_code          — regex/text search across the project (grep-like)
  find_files           — glob-based filename search
  get_outline           — extract function/class signatures from a file
  list_todos            — scan for TODO / FIXME / HACK / XXX markers
  get_diff               — show git diff for a file or the whole workspace
  check_dependencies    — parse requirements.txt / pyproject.toml /
                           package.json and report installed vs missing
  rename_path            — safe move/rename (never deletes the source
                           if the destination write fails)
  fetch_url              — fetch real documentation / API reference pages
                           so the agent answers from ground truth instead
                           of guessing API signatures from memory
"""

import ast
import fnmatch
import json
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

from bhavai.config import logger, CWD
from bhavai.context import is_env_file, parse_gitignore, should_ignore
from bhavai.tools import validate_path, _git_stage, ensure_git_initialized


# ─────────────────────────────────────────────────────────────────────────────
# Shared helper: walk the project respecting the same ignore rules as the
# folder tree (so search/find never touches .git, node_modules, .env, etc.)
# ─────────────────────────────────────────────────────────────────────────────

def _iter_project_files(root: Path):
    """Yields every non-ignored, non-secret file under root."""
    gitignore_patterns = parse_gitignore(root)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if should_ignore(p, root, gitignore_patterns):
            continue
        if is_env_file(p):
            continue
        yield p


def _read_text_safe(path: Path, max_bytes: int = 2_000_000) -> str | None:
    """Reads a file as UTF-8 text, returns None for binaries or oversized files."""
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Tool: search_code  — the single most-requested missing capability.
# Lets the agent (and effectively the user) ask "where is X used/defined?"
# instead of reading every file one by one to find out.
# ─────────────────────────────────────────────────────────────────────────────

def search_code(query: str, path: str = ".", regex: bool = False,
                 case_sensitive: bool = False, max_results: int = 100) -> str:
    """
    Searches file contents under `path` for `query`.

    Parameters
    ----------
    query          : Text to search for. Treated literally unless regex=True.
    path           : Directory (relative to CWD) to search within. Default '.'.
    regex          : If true, `query` is compiled as a Python regex.
    case_sensitive : Default False — most code searches are easier case-insensitive.
    max_results    : Caps the number of matching lines returned (default 100)
                     so one search can't blow the LLM's context window.

    Returns
    -------
    "path/to/file.py:42: matched line content" — one per match, grep-style.
    """
    logger.info("search_code(query=%r, path=%r, regex=%s)", query, path, regex)
    root = validate_path(path)
    if not root.exists():
        return f"Error: '{path}' does not exist."

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags) if regex else re.compile(re.escape(query), flags)
    except re.error as exc:
        return f"Error: invalid regex '{query}': {exc}"

    search_root = root if root.is_dir() else root.parent
    files = [root] if root.is_file() else list(_iter_project_files(root))

    matches = []
    for f in files:
        text = _read_text_safe(f)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                rel = f.relative_to(CWD)
                matches.append(f"{rel}:{lineno}: {line.strip()}")
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    if not matches:
        return f"No matches for '{query}' under '{path}'."

    header = f"Found {len(matches)} match(es) for '{query}'"
    if len(matches) >= max_results:
        header += f" (showing first {max_results} — narrow your search for more)"
    return header + ":\n" + "\n".join(matches)


# ─────────────────────────────────────────────────────────────────────────────
# Tool: find_files — "where is the config file?" without reading the whole tree
# ─────────────────────────────────────────────────────────────────────────────

def find_files(pattern: str, path: str = ".") -> str:
    """
    Finds files whose name matches a glob pattern (e.g. '*.py', 'test_*.py',
    '**/settings.json') under `path`, respecting .gitignore and secrets rules.
    """
    logger.info("find_files(pattern=%r, path=%r)", pattern, path)
    root = validate_path(path)
    if not root.exists() or not root.is_dir():
        return f"Error: '{path}' is not a valid directory."

    results = []
    for f in _iter_project_files(root):
        rel = f.relative_to(CWD)
        if fnmatch.fnmatch(f.name, pattern) or fnmatch.fnmatch(str(rel), pattern):
            results.append(str(rel))

    if not results:
        return f"No files matching '{pattern}' under '{path}'."
    results.sort()
    return f"Found {len(results)} file(s):\n" + "\n".join(results)


# ─────────────────────────────────────────────────────────────────────────────
# Tool: get_outline — fast code navigation: signatures without full content
# ─────────────────────────────────────────────────────────────────────────────

def get_outline(path: str) -> str:
    """
    Returns the structural outline of a file: classes, functions, and their
    line numbers, without returning full source.

    For .py files this uses the `ast` module for an exact outline.
    For other text files it falls back to a heuristic regex scan for common
    function/class declaration patterns (JS/TS, Java, C/C++, Go, Rust).

    Use this before read_file when you only need to know WHAT is in a file
    and WHERE, not the full implementation — saves tokens.
    """
    logger.info("get_outline('%s')", path)
    resolved = validate_path(path)
    if is_env_file(resolved):
        return f"Access Denied: '{path}' is an environment/secrets file."
    if not resolved.exists():
        return f"Error: '{path}' does not exist."
    if not resolved.is_file():
        return f"Error: '{path}' is a directory."

    text = _read_text_safe(resolved)
    if text is None:
        return f"Error: '{path}' is not a readable text file (binary or too large)."

    if resolved.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return f"Error: '{path}' has a syntax error and can't be parsed: {exc}"

        lines = []

        def _walk(node, indent=""):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    bases = ", ".join(ast.dump(b, annotate_fields=False)[:30] for b in child.bases) or ""
                    lines.append(f"{indent}class {child.name}  (line {child.lineno})")
                    _walk(child, indent + "    ")
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                    args = ", ".join(a.arg for a in child.args.args)
                    lines.append(f"{indent}{prefix} {child.name}({args})  (line {child.lineno})")

        _walk(tree)
        if not lines:
            return f"'{path}' has no top-level classes or functions."
        return f"Outline of '{path}':\n" + "\n".join(lines)

    # Heuristic fallback for non-Python text files
    patterns = [
        r"^\s*(export\s+)?(async\s+)?function\s+(\w+)",          # JS/TS
        r"^\s*(export\s+)?class\s+(\w+)",                         # JS/TS/Java
        r"^\s*(public|private|protected|static)?\s*\w+\s+(\w+)\s*\(",  # Java/C#
        r"^\s*func\s+(\w+)",                                       # Go
        r"^\s*fn\s+(\w+)",                                         # Rust
        r"^\s*(\w+)\s*:\s*function",                               # JS object method
    ]
    compiled = [re.compile(p) for p in patterns]
    lines = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat in compiled:
            if pat.search(line):
                lines.append(f"  line {lineno}: {line.strip()}")
                break

    if not lines:
        return f"No recognizable function/class declarations found in '{path}' (or unsupported language)."
    return f"Outline of '{path}' (heuristic scan):\n" + "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Tool: list_todos — every dev/student inheriting a codebase asks this first
# ─────────────────────────────────────────────────────────────────────────────

_TODO_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b[:\s]*(.*)", re.IGNORECASE)

def list_todos(path: str = ".") -> str:
    """
    Scans the project for TODO / FIXME / HACK / XXX / BUG comments.
    Returns file, line number, marker type, and the note text.
    """
    logger.info("list_todos(path='%s')", path)
    root = validate_path(path)
    if not root.exists():
        return f"Error: '{path}' does not exist."

    files = [root] if root.is_file() else list(_iter_project_files(root))
    found = []
    for f in files:
        text = _read_text_safe(f)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = _TODO_PATTERN.search(line)
            if m:
                rel = f.relative_to(CWD)
                marker, note = m.group(1).upper(), m.group(2).strip()
                found.append(f"[{marker}] {rel}:{lineno} — {note}" if note else f"[{marker}] {rel}:{lineno}")

    if not found:
        return f"No TODO/FIXME/HACK/XXX/BUG markers found under '{path}'. Clean!"
    return f"Found {len(found)} marker(s):\n" + "\n".join(found)


# ─────────────────────────────────────────────────────────────────────────────
# Tool: get_diff — surfaces the git tracking that tools.py already maintains
# ─────────────────────────────────────────────────────────────────────────────

def get_diff(path: str = "") -> str:
    """
    Shows `git diff HEAD` for a specific file, or for the whole workspace
    if path is omitted. Lets the user/agent see exactly what BhavAI has
    changed before deciding whether to keep it.
    """
    logger.info("get_diff(path='%s')", path)
    ensure_git_initialized()

    cmd = ["git", "diff", "HEAD", "--"]
    if path:
        resolved = validate_path(path)
        if is_env_file(resolved):
            return f"Access Denied: '{path}' is an environment/secrets file."
        cmd.append(str(resolved))

    try:
        proc = subprocess.run(cmd, cwd=CWD, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "Error: git diff timed out."
    except Exception as exc:
        return f"Error running git diff: {exc}"

    if proc.returncode != 0:
        return f"Error: git diff failed: {proc.stderr.strip()}"
    if not proc.stdout.strip():
        target = f"'{path}'" if path else "the workspace"
        return f"No uncommitted changes in {target}."
    return proc.stdout


# ─────────────────────────────────────────────────────────────────────────────
# Tool: check_dependencies — real onboarding pain: "will this even run?"
# ─────────────────────────────────────────────────────────────────────────────

def _parse_requirements_txt(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifiers / extras: "requests[socks]>=2.0" → "requests"
        name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def _parse_pyproject_toml(text: str) -> list[str]:
    names = []
    # Lightweight extraction without a TOML dependency: look for the
    # [tool.poetry.dependencies] / [project] dependencies arrays/tables.
    dep_array = re.search(r'dependencies\s*=\s*\[(.*?)\]', text, re.DOTALL)
    if dep_array:
        for entry in re.findall(r'["\']([^"\']+)["\']', dep_array.group(1)):
            name = re.split(r"[<>=!~\[; ]", entry, maxsplit=1)[0].strip()
            if name:
                names.append(name)
    # Poetry-style table: name = "version"
    poetry_block = re.search(r'\[tool\.poetry\.dependencies\](.*?)(\n\[|\Z)', text, re.DOTALL)
    if poetry_block:
        for line in poetry_block.group(1).splitlines():
            m = re.match(r'\s*([A-Za-z0-9_.-]+)\s*=', line)
            if m and m.group(1).lower() != "python":
                names.append(m.group(1))
    return names


def _parse_package_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    names = []
    for key in ("dependencies", "devDependencies"):
        names.extend((data.get(key) or {}).keys())
    return names


def check_dependencies(path: str = ".") -> str:
    """
    Finds requirements.txt, pyproject.toml, and/or package.json under `path`
    and reports which declared dependencies are actually importable/installed
    in the current environment. Surfaces "missing dependency" issues before
    the user hits an ImportError or 'module not found' mid-task.

    Python packages are checked via importlib; Node packages are checked by
    looking for a matching folder under node_modules/.
    """
    logger.info("check_dependencies(path='%s')", path)
    root = validate_path(path)
    if not root.exists() or not root.is_dir():
        return f"Error: '{path}' is not a valid directory."

    reports = []

    req_file = root / "requirements.txt"
    if req_file.exists():
        text = _read_text_safe(req_file) or ""
        pkgs = _parse_requirements_txt(text)
        reports.append(_check_python_packages(pkgs, "requirements.txt"))

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = _read_text_safe(pyproject) or ""
        pkgs = _parse_pyproject_toml(text)
        if pkgs:
            reports.append(_check_python_packages(pkgs, "pyproject.toml"))

    package_json = root / "package.json"
    if package_json.exists():
        text = _read_text_safe(package_json) or ""
        pkgs = _parse_package_json(text)
        if pkgs:
            reports.append(_check_node_packages(pkgs, root))

    if not reports:
        return (f"No requirements.txt, pyproject.toml, or package.json found under '{path}'. "
                f"Nothing to check.")
    return "\n\n".join(reports)


def _check_python_packages(pkgs: list[str], source: str) -> str:
    import importlib.util
    # Common PyPI-name → import-name mismatches
    import_name_overrides = {
        "pillow": "PIL", "pyyaml": "yaml", "beautifulsoup4": "bs4",
        "python-dotenv": "dotenv", "scikit-learn": "sklearn",
        "opencv-python": "cv2",
    }
    installed, missing = [], []
    for pkg in pkgs:
        import_name = import_name_overrides.get(pkg.lower(), pkg.replace("-", "_"))
        spec = importlib.util.find_spec(import_name)
        (installed if spec else missing).append(pkg)

    lines = [f"From {source} ({len(pkgs)} package(s)):"]
    if installed:
        lines.append(f"  ✓ Installed: {', '.join(installed)}")
    if missing:
        lines.append(f"  ✗ Missing:   {', '.join(missing)}")
        lines.append(f"    → pip install {' '.join(missing)}")
    return "\n".join(lines)


def _check_node_packages(pkgs: list[str], root: Path) -> str:
    node_modules = root / "node_modules"
    installed, missing = [], []
    for pkg in pkgs:
        if (node_modules / pkg).exists():
            installed.append(pkg)
        else:
            missing.append(pkg)

    lines = [f"From package.json ({len(pkgs)} package(s)):"]
    if installed:
        lines.append(f"  ✓ Installed: {', '.join(installed)}")
    if missing:
        lines.append(f"  ✗ Missing:   {', '.join(missing)}")
        lines.append(f"    → npm install {' '.join(missing)}")
    if not node_modules.exists():
        lines.append("  ⚠ node_modules/ not found at all — run `npm install` first.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Tool: rename_path — reorganize without ever deleting the original
# ─────────────────────────────────────────────────────────────────────────────

def rename_path(source: str, destination: str) -> str:
    """
    Moves/renames a file or folder from `source` to `destination`,
    both sandboxed inside CWD.

    Safety guarantees (zero-deletion policy compliance)
    ----------------------------------------------------
    • Refuses to overwrite an existing destination (no silent data loss).
    • If anything goes wrong mid-move, the source is left untouched —
      this NEVER deletes source content; it only relocates it.
    • Destination's parent directories are created automatically.
    """
    logger.info("rename_path('%s' -> '%s')", source, destination)
    ensure_git_initialized()

    src = validate_path(source)
    dst = validate_path(destination)

    if is_env_file(src) or is_env_file(dst):
        return "Access Denied: refusing to move environment/secrets files."
    if not src.exists():
        return f"Error: source '{source}' does not exist."
    if dst.exists():
        return (f"Error: destination '{destination}' already exists. "
                f"Refusing to overwrite — choose a different name or move it first.")

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        _git_stage(dst)
        return f"✓ Moved '{source}' → '{destination}'. Run `git diff HEAD` to review."
    except Exception as exc:
        logger.error("rename_path('%s' -> '%s'): %s", source, destination, exc)
        return f"Error moving '{source}' to '{destination}': {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool: fetch_url — ground the agent in real documentation instead of
# letting it guess API signatures, error messages, or library usage from
# (possibly stale) training data. High value for students learning new
# libraries and developers debugging unfamiliar errors.
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_URL_SCHEMES = ("http://", "https://")
_MAX_FETCH_BYTES = 300_000

def fetch_url(url: str, max_chars: int = 8000) -> str:
    """
    Fetches a web page or API endpoint and returns its text content
    (HTML tags stripped) for the agent to read.

    Use this to look up real documentation, error message explanations,
    Stack Overflow answers, or library API references instead of
    guessing — especially for libraries that may have changed since
    the model's training data.

    Truncates output to max_chars (default 8000) to protect the
    4096-token output budget on the NEXT call where the agent
    summarizes what it read.
    """
    logger.info("fetch_url('%s')", url)
    if not url.lower().startswith(_ALLOWED_URL_SCHEMES):
        return "Error: only http:// and https:// URLs are supported."

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "BhavAI-Agent/1.0 (+terminal coding assistant)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(_MAX_FETCH_BYTES)
    except urllib.error.HTTPError as exc:
        return f"Error: HTTP {exc.code} fetching '{url}'."
    except urllib.error.URLError as exc:
        return f"Error: could not reach '{url}': {exc.reason}"
    except Exception as exc:
        return f"Error fetching '{url}': {exc}"

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return f"Error: '{url}' did not return decodable text content."

    if "html" in content_type.lower():
        # Strip script/style blocks, then all remaining tags — good enough
        # for an agent that needs prose, not pixel-perfect rendering.
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

    truncated = len(text) > max_chars
    text = text[:max_chars]
    suffix = f"\n\n[...truncated, {len(raw)} bytes fetched total...]" if truncated else ""
    return f"Content from {url}:\n\n{text}{suffix}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool: get_function_source — precise, line-numbered view of ONE function.
#
# Why this earns a spot next to get_outline
# ------------------------------------------
# get_outline tells the agent WHERE a function is. This tool returns WHAT is
# in it — but only that function, not the whole file — so the agent can
# inspect a single function's body for a fraction of the tokens read_file
# would cost on a large file.
# ─────────────────────────────────────────────────────────────────────────────

def get_function_source(path: str, function_name: str) -> str:
    """
    Returns the exact source of one function (or async function), with line
    numbers, found via AST — not text search, so it can't be fooled by a
    matching string inside a comment or docstring elsewhere in the file.

    Use this instead of read_file when you only need one function's body.
    """
    logger.info("get_function_source('%s', '%s')", path, function_name)
    resolved = validate_path(path)

    if is_env_file(resolved):
        return f"Access Denied: '{path}' is an environment/secrets file."
    if not resolved.exists():
        return f"Error: '{path}' does not exist."
    if resolved.suffix != ".py":
        return "Error: Only Python files are supported."

    text = _read_text_safe(resolved)
    if text is None:
        return f"Error: '{path}' is not a readable text file (binary or too large)."

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return f"Error: '{path}' has a syntax error and can't be parsed: {exc}"

    lines = text.splitlines()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            start, end = node.lineno, node.end_lineno
            snippet = lines[start - 1 : end]
            numbered = "\n".join(f"{i:4d} | {line}" for i, line in enumerate(snippet, start=start))
            return f"FUNCTION: {function_name}\nFILE: {path}\nLINES: {start}-{end}\n\n{numbered}"

    return f"Function '{function_name}' not found in '{path}'."


# ─────────────────────────────────────────────────────────────────────────────
# Tool: insert_function — append a brand-new function to the end of a file.
#
# Mutating tool, so it follows the same conventions as write_file/append_chunk
# in tools.py: ensure_git_initialized() first, .env guard, _git_stage() on
# success so the change shows up in `git diff HEAD`.
# ─────────────────────────────────────────────────────────────────────────────

def insert_function(path: str, new_source: str) -> str:
    """
    Inserts a new top-level function (or async function) at the end of a
    Python file. The new source is validated with ast.parse BEFORE anything
    is written, so a syntax error in new_source never corrupts the file.

    Use this to ADD a function that doesn't exist yet. To replace an
    existing function's body, use replace_function instead.
    """
    logger.info("insert_function('%s', %d chars)", path, len(new_source))
    ensure_git_initialized()

    resolved = validate_path(path)

    if is_env_file(resolved):
        return f"Access Denied: '{path}' is an environment/secrets file."
    if not resolved.exists():
        return f"Error: '{path}' does not exist."
    if resolved.suffix != ".py":
        return "Error: Only Python files are supported."

    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        return f"Syntax Error in new function: {exc}"

    try:
        source = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error reading '{path}': {exc}"

    updated_source = source.rstrip() + "\n\n\n" + new_source.strip() + "\n"

    try:
        resolved.write_text(updated_source, encoding="utf-8")
        _git_stage(resolved)
    except Exception as exc:
        logger.error("insert_function('%s'): %s", path, exc)
        return f"Error writing '{path}': {exc}"

    return f"✓ Function inserted into '{path}'. Run `git diff HEAD` to review."


# ─────────────────────────────────────────────────────────────────────────────
# Tool: replace_function — swap out an existing function's full source.
#
# Uses AST line numbers (lineno/end_lineno) to slice out exactly the old
# function and splice in the new one — same precision approach as
# get_function_source, so the two tools are a natural "read it, rewrite it"
# pair for the agent.
# ─────────────────────────────────────────────────────────────────────────────

def replace_function(path: str, function_name: str, new_source: str) -> str:
    """
    Replaces an existing top-level function (or async function) with new
    source code, located precisely via AST line numbers (not text matching,
    so a docstring mentioning the function name elsewhere can't confuse it).

    new_source must be syntactically valid on its own — it is validated with
    ast.parse before the file is touched. If function_name isn't found,
    nothing is written.
    """
    logger.info("replace_function('%s', '%s', %d chars)", path, function_name, len(new_source))
    ensure_git_initialized()

    resolved = validate_path(path)

    if is_env_file(resolved):
        return f"Access Denied: '{path}' is an environment/secrets file."
    if not resolved.exists():
        return f"Error: '{path}' does not exist."
    if resolved.suffix != ".py":
        return "Error: Only Python files are supported."

    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        return f"Syntax Error in new function: {exc}"

    try:
        source = resolved.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"Error: '{path}' has a syntax error and can't be parsed: {exc}"
    except Exception as exc:
        return f"Error reading '{path}': {exc}"

    target_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            target_node = node
            break

    if target_node is None:
        return f"Function '{function_name}' not found in '{path}'. Nothing was changed."

    start, end = target_node.lineno, target_node.end_lineno
    new_function_lines = new_source.strip().splitlines()
    updated_lines = lines[: start - 1] + new_function_lines + lines[end:]

    try:
        resolved.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
        _git_stage(resolved)
    except Exception as exc:
        logger.error("replace_function('%s'): %s", path, exc)
        return f"Error writing '{path}': {exc}"

    return (
        f"✓ Replaced '{function_name}' (was lines {start}-{end}) in '{path}'. "
        f"Run `git diff HEAD` to review."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch registry for this module — merged into tools.TOOL_DISPATCH by agent.py
# ─────────────────────────────────────────────────────────────────────────────

EXTENDED_TOOL_DISPATCH = {
    "search_code":          search_code,
    "find_files":           find_files,
    "get_outline":          get_outline,
    "list_todos":           list_todos,
    "get_diff":             get_diff,
    "check_dependencies":   check_dependencies,
    "rename_path":          rename_path,
    "fetch_url":            fetch_url,
    "get_function_source":  get_function_source,
    "insert_function":      insert_function,
    "replace_function":     replace_function,
}


if __name__ == "__main__":
    print(search_code(
        path=".",
        query="mock_cwd"
    ))