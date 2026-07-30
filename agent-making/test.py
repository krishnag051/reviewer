"""Cheapest possible live check: does ANTHROPIC_API_KEY (from .env in this
folder) work at all, and does the account have credit? Makes exactly one
tiny API call (a few tokens) — nothing pipeline-related, no document, no
judgment rules. Run this before anything expensive.

Usage (from agent-making):
    .venv/Scripts/python.exe test.py
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import anthropic  # noqa: E402

MODEL = "claude-sonnet-5"


def main() -> None:
    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        )
    except anthropic.AuthenticationError as e:
        print(f"FAIL — invalid or missing API key: {e.message}")
        return
    except anthropic.BadRequestError as e:
        if "credit balance" in str(e.message).lower():
            print(f"FAIL — key is valid but the account has no credit: {e.message}")
        else:
            print(f"FAIL — bad request (not a credit/auth issue): {e.message}")
        return
    except anthropic.APIStatusError as e:
        print(f"FAIL — API error (status {e.status_code}): {e.message}")
        return
    except anthropic.APIConnectionError as e:
        print(f"FAIL — network error, could not reach the API: {e}")
        return

    text = next((b.text for b in response.content if b.type == "text"), "")
    print(f"OK — key is valid and has credit. Model replied: {text!r}")
    print(f"Tokens used: {response.usage.input_tokens} in / {response.usage.output_tokens} out")


if __name__ == "__main__":
    main()
