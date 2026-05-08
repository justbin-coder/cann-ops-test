import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Optional


@dataclass
class State:
    api_doc_path: str
    pdf_files: List[Dict[str, str]] = field(default_factory=list)
    whitelist_cube_sha: str = ""
    whitelist_vector_sha: str = ""
    last_refreshed_at: str = ""
    last_refreshed_by: str = ""


def load_state(path: Path) -> Optional[State]:
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return State(**data)


def save_state(path: Path, state: State) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
