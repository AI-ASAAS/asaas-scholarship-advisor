"""Shared prompt loader reading versioned Markdown files from prompts/."""

from pathlib import Path
from typing import Tuple

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def load_prompt(name: str, prompts_dir: Path | None = None) -> Tuple[str, str]:
    """Return `(prompt_text, prompt_version)` from `prompts/<name>.md`.

    The first line of each prompt file must start with `version: <tag>`.
    """
    base_dir = prompts_dir or PROMPTS_DIR
    file_path = base_dir / f"{name}.md"
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found at {file_path}")

    content = file_path.read_text(encoding="utf-8")
    first_line, _, body = content.partition("\n")
    version = (
        first_line.removeprefix("version:").strip()
        if first_line.startswith("version:")
        else f"{name}@1.0"
    )
    return body.strip(), version
