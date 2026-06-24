from pathlib import Path
import ast


def get_function_source(
    file_path: str,
    function_name: str
) -> str:
    """
    Returns the complete source code of a function
    using AST line numbers.
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

    for node in ast.walk(tree):

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef
            )
        ):

            if node.name == function_name:

                start = node.lineno
                end = node.end_lineno

                function_lines = lines[
                    start - 1 : end
                ]

                output = []

                output.append(
                    f"FUNCTION: {function_name}"
                )

                output.append(
                    f"LINES: {start}-{end}"
                )

                output.append("")

                for idx, line in enumerate(
                    function_lines,
                    start=start
                ):
                    output.append(
                        f"{idx:4d} | {line}"
                    )

                return "\n".join(output)

    return (
        f"Function '{function_name}' "
        f"not found."
    )


print(get_function_source(
    r"C:\Users\bhavi\Downloads\Coding Payground\agent using antigravity\bhavai\llm.py",
    "query_llm_with_continuation"

))