from pathlib import Path
import ast


def get_file_outline(file_path: str) -> str:
    """
    Returns a high-level outline of a Python file:
    - Imports
    - Classes
    - Functions
    - Async Functions
    - Line numbers
    """

    path = Path(file_path)

    if not path.exists():
        return f"Error: '{file_path}' does not exist."

    if path.suffix != ".py":
        return "Error: Only Python files are currently supported."

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        return f"Error parsing file: {e}"

    imports = []
    classes = []
    functions = []
    async_functions = []

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.append(f"from {module}")

        elif isinstance(node, ast.ClassDef):
            classes.append(
                (node.name, node.lineno)
            )

        elif isinstance(node, ast.FunctionDef):
            functions.append(
                (node.name, node.lineno)
            )

        elif isinstance(node, ast.AsyncFunctionDef):
            async_functions.append(
                (node.name, node.lineno)
            )

    output = []

    output.append(f"FILE: {path.name}")
    output.append("")

    output.append("IMPORTS:")
    if imports:
        for imp in sorted(set(imports)):
            output.append(f"  - {imp}")
    else:
        output.append("  None")

    output.append("")

    output.append("CLASSES:")
    if classes:
        for name, line in classes:
            output.append(f"  - {name} (line {line})")
    else:
        output.append("  None")

    output.append("")

    output.append("FUNCTIONS:")
    if functions:
        for name, line in functions:
            output.append(f"  - {name} (line {line})")
    else:
        output.append("  None")

    output.append("")

    output.append("ASYNC FUNCTIONS:")
    if async_functions:
        for name, line in async_functions:
            output.append(f"  - {name} (line {line})")
    else:
        output.append("  None")

    return "\n".join(output)




print(get_file_outline(r"C:\Users\bhavi\Downloads\Coding Payground\agent using antigravity\bhavai\llm.py"))