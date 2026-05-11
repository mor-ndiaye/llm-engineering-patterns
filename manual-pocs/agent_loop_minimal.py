import os
from pathlib import Path
import json

from anthropic import Anthropic
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env.local"
# Loading env vars
load_dotenv(dotenv_path=ENV_PATH, override=True)

# Initialize Anthropic API client
client = Anthropic()

assert os.environ.get("ANTHROPIC_API_KEY") is not None

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


# Define the tools execution function
def execute_tool(name: str, input: dict) -> str:
    if name == "get_current_city_weather":
        city = input.get("city", "Unknown")
        return json.dumps({"city": city, "temperature_c": 22, "conditions": "sunny"})
    return json.dumps({"error": f"Tool {name} does not exist."})


MAX_ITERATIONS: int = 3  # the number of turn we allow our agent to run


def _extract_text(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


# The Agent Loop
def agent_loop(user_message: str) -> str:
    messages = [{"role": "user", "content": user_message}]
    iter_counter: int = 1

    while iter_counter <= MAX_ITERATIONS:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=messages,
            tools=TOOLS,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        )

        if response.stop_reason == "tool_use":
            # parallel calls disabled via tool_choice — exactly 1 tool_use block expected per response
            tool_use = next(
                block for block in response.content if block.type == "tool_use"
            )

            tool_result = execute_tool(name=tool_use.name, input=tool_use.input)

            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": tool_result,
                        }
                    ],
                }
            )
        elif response.stop_reason == "end_turn":
            return _extract_text(response)
        elif response.stop_reason == "max_tokens":
            raise RuntimeError("Response truncated, increase max_tokens")
        else:
            raise RuntimeError(f"Unexpected stop_reason: {response.stop_reason}")
        iter_counter += 1
    raise RuntimeError(f"Agent did not converge after {MAX_ITERATIONS} iterations")


if __name__ == "__main__":
    result = agent_loop(user_message="What's the weather like in Tokyo today?")
    print(result)
