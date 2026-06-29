import json

def get_last_n_tools(messages, n=3):
    tools = []

    for msg in reversed(messages):
        if msg["role"] != "assistant":
            continue

        try:
            data = json.loads(msg["content"])
            tool_name = data.get("tool_name")

            if tool_name and tool_name != "final_answer":
                tools.append(tool_name)

            if len(tools) >= n:
                break

        except Exception:
            pass

    return list(reversed(tools))