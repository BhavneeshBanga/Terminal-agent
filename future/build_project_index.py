from pathlib import Path
import ast
import json


def build_project_index(project_path="."):
    """
    Builds a lightweight project index for BhavAI.

    Creates:
        .bhavai/project_index.json

    Stores:
        - files
        - functions
        - classes
        - docstrings
        - line numbers
    """

    project_root = Path(project_path)

    if not project_root.exists():
        return f"Error: {project_path} does not exist"

    index = {
        "readme": None,
        "files": {}
    }

    # -------------------------
    # README
    # -------------------------

    for readme_name in [
        "README.md",
        "readme.md",
        "README.txt"
    ]:

        readme_path = project_root / readme_name

        if readme_path.exists():

            try:
                index["readme"] = readme_path.read_text(
                    encoding="utf-8"
                )[:5000]

            except Exception:
                pass

            break

    # -------------------------
    # PY FILES
    # -------------------------

    for py_file in project_root.rglob("*.py"):

        try:

            source = py_file.read_text(
                encoding="utf-8"
            )

            tree = ast.parse(source)

        except Exception:
            continue

        relative_path = str(
            py_file.relative_to(project_root)
        )

        file_data = {
            "functions": [],
            "classes": []
        }

        for node in ast.walk(tree):

            # Functions

            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef
                )
            ):

                file_data["functions"].append({

                    "name":
                    node.name,

                    "start_line":
                    node.lineno,

                    "end_line":
                    getattr(
                        node,
                        "end_lineno",
                        node.lineno
                    ),

                    "docstring":
                    ast.get_docstring(node)

                })

            #For Classes

            elif isinstance(
                node,
                ast.ClassDef
            ):

                file_data["classes"].append({

                    "name":node.name,

                    "start_line": node.lineno,

                    "end_line":getattr(node, "end_lineno", node.lineno ),

                    "docstring":ast.get_docstring(node)

                })

        index["files"][relative_path] = file_data

    

    bhavai_dir = project_root / ".bhavai"

    bhavai_dir.mkdir(
        exist_ok=True
    )

    output_file = (
        bhavai_dir /
        "project_index.json"
    )

    output_file.write_text(

        json.dumps(
            index,
            indent=2
        ),

        encoding="utf-8"
    )

    return (
        f"Project index created:\n"
        f"{output_file}"
    )




print(
    build_project_index(
        r"C:\Users\bhavi\Downloads\Coding Payground\agent using antigravity"
    )
)

