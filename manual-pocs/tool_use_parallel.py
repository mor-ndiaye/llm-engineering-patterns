import os
import json
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

# Load env vars
ENV_PATH = Path(__file__).parent.parent / ".env.local"
load_dotenv(dotenv_path=ENV_PATH, override=True)

assert os.environ.get("ANTHROPIC_API_KEY") is not None

# Initialize Anthropic API client
client = Anthropic()

# Define tools used
TOOLS = [
    {
        "name": "get_current_city_weather",
        "description": "Get the current weather (temperature in Celsius and conditions) for a given city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "The name of the city for which to retrieve the current weather. e.g: Tokyo, Paris, Dakar",
                }
            },
            "required": ["city"],
        },
    }
]

MAX_ITERATIONS: int = 5


def execute_tool(name: str, input: dict) -> str:
    if name == "get_current_city_weather":
        city = input.get("city", "unknown")
        return json.dumps({"city": city, "temperature_c": 22, "conditions": "sunny"})
    return json.dumps({"error": f"Tool {name} does not exist."})


def _extract_blocks_text(response) -> str:
    return "".join(blk.text for blk in response.content if blk.type == "text")


def agent_loop(user_message: str) -> str:
    messages = [{"role": "user", "content": user_message}]

    iter_counter: int = 1

    while iter_counter <= MAX_ITERATIONS:
        response = client.messages.create(
            model="claude-haiku-4-5",
            messages=messages,
            tools=TOOLS,
            max_tokens=1024,
        )

        if response.stop_reason == "tool_use":
            tool_use_results = []
            tool_use_calls = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_use_calls.append(f"-> {block.name}({block.input})")
                    tool_result = execute_tool(name=block.name, input=block.input)
                    tool_use_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_result,
                        }
                    )
            print(
                f"ROUND {iter_counter} / {MAX_ITERATIONS}: {len(tool_use_results)} parallel calls"
            )
            print("\n".join(tool_use_calls))
            # Add all the result block to a single matching user message
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_use_results})
        elif response.stop_reason == "end_turn":
            return _extract_blocks_text(response)
        elif response.stop_reason == "max_tokens":
            raise RuntimeError("response truncated, increase max_tokens")
        else:
            raise RuntimeError(f"Unexpected stop_reason: {response.stop_reason}")
        iter_counter += 1

    raise RuntimeError(f"Agent did not converge after {MAX_ITERATIONS} iterations")


if __name__ == "__main__":
    result = agent_loop(
        user_message="What's the current weather in Tokyo, Kuala Lumpur and Paris? "
    )
    print(result)
