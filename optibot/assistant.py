"""Ask OptiBot a question against the File Search store (same prompt as the AI Studio setup).

Usage: uv run python -m optibot.assistant "How do I add a YouTube video?"
Env:   GEMINI_API_KEY, GEMINI_MODEL (default: gemini-3.8-flash), GEMINI_STORE_DISPLAY_NAME
"""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from optibot.knowledge_base import DEFAULT_STORE_DISPLAY_NAME, make_client

# Verbatim from the assignment.
SYSTEM_PROMPT = """You are OptiBot, the customer-support bot for OptiSigns.com.
• Tone: helpful, factual, concise.
• Only answer using the uploaded docs.
• Max 5 bullet points; else link to the doc.
• Cite up to 3 "Article URL:" lines per reply."""

DEFAULT_MODEL = "gemini-3.8-flash"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    args = parser.parse_args()
    load_dotenv()

    client = make_client(os.environ["GEMINI_API_KEY"])
    display_name = os.environ.get("GEMINI_STORE_DISPLAY_NAME", DEFAULT_STORE_DISPLAY_NAME)
    store = next((s.name for s in client.file_search_stores.list() if s.display_name == display_name), None)
    if store is None:
        raise SystemExit(f"no file search store named {display_name!r}; run `python -m optibot.upload` first")

    interaction = client.interactions.create(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        input=args.question,
        system_instruction=SYSTEM_PROMPT,
        tools=[{"type": "file_search", "file_search_store_names": [store]}],
    )
    sources: dict[str, str] = {}
    for step in interaction.steps:
        if step.type != "model_output":
            continue
        for block in step.content or []:
            if block.type != "text":
                continue
            print(block.text)
            for note in block.annotations or []:
                meta = getattr(note, "custom_metadata", None) or {}
                if meta.get("url"):
                    sources[meta["url"]] = meta.get("title", "")
    if sources:
        print("\nRetrieved from:")
        for url, title in sources.items():
            print(f"  - {title}: {url}")


if __name__ == "__main__":
    main()
