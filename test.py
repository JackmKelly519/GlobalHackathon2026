#!/usr/bin/env python3
"""
Minimal example: call Claude and let it use a tool.

  export ANTHROPIC_API_KEY=...
  python claude_tool_use_example.py
"""
import json
import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
MODEL = "claude-sonnet-4-6"

# 1. Describe the tool to Claude
tools = [{
    "name": "get_directions",
    "description": "Get directions between two places.",
    "input_schema": {
        "type": "object",
        "properties": {
            "origin": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["origin", "destination"],
    },
}]

# 2. The real function (here a stub)
def get_directions(origin, destination):
    return {"duration": "35 min", "steps": [f"Take matatu 46 from {origin}", f"Alight near {destination}"]}

messages = [{"role": "user", "content": "How do I get from Kibera to Kenyatta National Hospital?"}]

# 3. First call: Claude decides whether to use the tool
resp = client.messages.create(model=MODEL, max_tokens=500, tools=tools, messages=messages)

# 4. If it asked for a tool, run it and send the result back
if resp.stop_reason == "tool_use":
    messages.append({"role": "assistant", "content": resp.content})
    tool_results = []
    for block in resp.content:
        if block.type == "tool_use":
            result = get_directions(**block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })
    messages.append({"role": "user", "content": tool_results})

    # 5. Second call: Claude writes the final answer using the tool result
    resp = client.messages.create(model=MODEL, max_tokens=500, tools=tools, messages=messages)

print("".join(b.text for b in resp.content if b.type == "text"))