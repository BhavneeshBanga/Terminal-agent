from pathlib import Path
import ast


def replace_function(
    file_path: str,
    function_name: str,
    new_source: str
) -> str:
    """
    Replaces an existing function with new source code.

    Parameters
    ----------
    file_path : str
        Path to Python file.

    function_name : str
        Name of function to replace.

    new_source : str
        Complete replacement function source.
        Example:

        def hello():
            print("Hello World")
    """

    path = Path(file_path)

    if not path.exists():
        return f"Error: '{file_path}' does not exist."

    if path.suffix != ".py":
        return "Error: Only Python files are supported."

    try:
        source = path.read_text(
            encoding="utf-8"
        )

        lines = source.splitlines()

        tree = ast.parse(source)

    except Exception as e:
        return f"Error parsing file: {e}"

    target_node = None

    for node in ast.walk(tree):

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef
            )
        ):

            if node.name == function_name:
                target_node = node
                break

    if target_node is None:
        return (
            f"Function '{function_name}' "
            f"not found."
        )

    start = target_node.lineno
    end = target_node.end_lineno

    new_function_lines = new_source.splitlines()

    updated_lines = (
        lines[:start - 1]
        + new_function_lines
        + lines[end:]
    )

    try:
        path.write_text(
            "\n".join(updated_lines),
            encoding="utf-8"
        )

    except Exception as e:
        return f"Error writing file: {e}"

    return (
        f"Successfully replaced "
        f"'{function_name}' "
        f"(lines {start}-{end})"
    )



new_code = """
def greet():
    print("Hello World")
    print("Modified")
""".strip()

print(
    replace_function(
        r"C:\Users\bhavi\Downloads\Coding Payground\agent using antigravity\faltu.py",
        "greet",
        new_code
    )
)