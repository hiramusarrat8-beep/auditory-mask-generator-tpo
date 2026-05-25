from pathlib import Path
from typing import Any
import json


def save_session_data(filepath: str | Path, data: dict[str, Any]) -> Path:
    """Persist session metadata as formatted JSON and return the written path."""
    target_path = Path(filepath)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with target_path.open("w", encoding="utf-8") as output_file:
        json.dump(data, output_file, indent=2)
        output_file.write("\n")

    return target_path
