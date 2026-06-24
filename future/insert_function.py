from pathlib import Path
import ast


def insert_function(
    file_path: str,
    new_source: str
) -> str:
    """
    Inserts a new function at the end of a Python file.

    Parameters
    ----------
    file_path : str
        Path to Python file.

    new_source : str
        Complete function source code.

    Example
    -------
    def validate_token(token):
        return True
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

        # Validate syntax of new function
        ast.parse(new_source)

    except SyntaxError as e:
        return f"Syntax Error in new function: {e}"

    except Exception as e:
        return f"Error: {e}"

    try:

        updated_source = (
            source.rstrip()
            + "\n\n\n"
            + new_source.strip()
            + "\n"
        )

        path.write_text(
            updated_source,
            encoding="utf-8"
        )

    except Exception as e:
        return f"Error writing file: {e}"

    return "Function inserted successfully."



new_code = """
def validate_token(token):
    return token == "abc123"
""".strip()

print(
    insert_function(
        r"C:\Users\bhavi\Downloads\Coding Payground\agent using antigravity\faltu.py",
        new_code
    )
)