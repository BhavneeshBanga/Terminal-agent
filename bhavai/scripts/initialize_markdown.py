import os
from pathlib import Path
from bhavai.llm import call_sarvam

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
    "site-packages", ".eggs", ".tox", "htmlcov",
}

IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "BHAVAI.md",  # never re-insert our own output file
}

IGNORE_EXTS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".pdf", ".zip", ".tar", ".gz", ".7z", ".lock", ".db", ".sqlite3",
    ".woff", ".woff2", ".ttf", ".mp4", ".mov", ".bin",
}

def scan_and_summarize_project(
    root_dir: str = ".",
    output_file: str = "BHAVAI.md",
    max_chars_per_file: int = 4000,   
    max_total_chars_to_be_sent_to_llm: int = 60000,     
) -> str:
    """
    scans root folder, collect valid files,
    build summary, save in BHAVAI.md.

    Returns:
        Generated summary (str)
    """
    
    root_path = Path(root_dir).resolve()
    collected_content = []
    total_chars = 0
    file_count = 0  #number of files present in the directory

    for dirpath, dirnames, filenames in os.walk(root_path):
        
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for fname in filenames:
            if fname in IGNORE_FILES:
                continue

            ext = Path(fname).suffix.lower()
            if ext in IGNORE_EXTS:
                continue

            fpath = Path(dirpath) / fname
            rel_path = fpath.relative_to(root_path)

            try:
                #ignore binary garbage fiels
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError, PermissionError):
                continue

            if not text.strip():
                continue

            # bahut badi files ko truncate kar do
            if len(text) > max_chars_per_file:
                text = text[:max_chars_per_file] + "\n...[truncated]..."

            entry = f"\n\n### File: {rel_path}\n```\n{text}\n```"

            # total budget cross ho jaye toh stop
            if total_chars + len(entry) > max_total_chars_to_be_sent_to_llm:
                break

            collected_content.append(entry)
            total_chars += len(entry)
            file_count += 1

        else:
            continue
        break  # inner loop break hua to outer bhi break (budget khatam)

    if not collected_content:
        return "No readable files found to summarize."

    project_dump = "".join(collected_content)

    messages = [
    {
        "role": "system",
        "content": (
            "You are a senior software engineer and software architect. "
            "Your job is to analyze the source code of a project and produce a "
            "clear, well-structured, and concise project summary in Markdown.\n\n"

            "Your summary should include the following sections:\n"
            "1. Project Overview – What is the purpose of the project?\n"
            "2. Major Components – List the important files, modules, or folders and explain their responsibilities.\n"
            "3. Tech Stack and Dependencies – Mention the programming languages, frameworks, libraries, and external services used.\n"
            "4. Application Flow – Explain how the project works, including the entry point and the flow between components.\n"
            "5. Key Features – Highlight the main capabilities of the project.\n"
            "6. Important Observations – Mention code patterns, architectural decisions, potential issues, or TODOs if they are visible.\n\n"

            "Write the output in clean, professional Markdown with appropriate headings, bullet points, and short explanations."
        ),
    },
    {
        "role": "user",
        "content": (
            f"The following text contains the contents of {file_count} project files.\n\n"
            "Analyze the entire codebase and generate a comprehensive project summary in Markdown.\n\n"
            f"{project_dump}"
        ),
    },
]

    summary = call_sarvam(messages)

    output_path = root_path / output_file
    header = (
        f"# BHAVAI {root_path.name}\n\n"
        f"_Auto-generated summary of {file_count} file(s)._\n\n---\n\n"
    )

    output_path.write_text(header + summary, encoding="utf-8")
    print(f"✅ Summary saved to: {output_path}")

    return summary


if __name__ == "__main__":
    scan_and_summarize_project(root_dir=".")