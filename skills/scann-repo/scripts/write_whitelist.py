import datetime
import hashlib
from pathlib import Path
from typing import Dict, List


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _render_md(title: str, source_pdfs: List[dict], chapters: Dict[str, List[str]]) -> str:
    lines = [f"# {title}", ""]
    lines.append(f"> Extracted: {datetime.datetime.now().isoformat(timespec='seconds')}")
    for pdf in source_pdfs:
        lines.append(f"> Source PDF: {pdf['name']} (sha256: {pdf['sha256'][:16]}...)")
    lines.append("")
    for chapter, names in chapters.items():
        lines.append(f"## {chapter}")
        for n in sorted(set(names)):
            lines.append(f"- {n}")
        lines.append("")
    return "\n".join(lines)


def write_whitelists(
    api_path: Path,
    cube_chapters: Dict[str, List[str]],
    vector_chapters: Dict[str, List[str]],
    actor: str,
) -> None:
    api_path = Path(api_path)
    if not api_path.is_dir():
        raise ValueError(f"api_path is not a directory: {api_path}")

    pdfs = []
    for p in sorted(api_path.glob("*.pdf")):
        pdfs.append({"name": p.name, "sha256": _sha256(p)})
    if not pdfs:
        raise ValueError(f"no .pdf files in {api_path}")

    (api_path / "whitelist_cube.md").write_text(
        _render_md("whitelist_cube.md", pdfs, cube_chapters), encoding="utf-8"
    )
    (api_path / "whitelist_vector.md").write_text(
        _render_md("whitelist_vector.md", pdfs, vector_chapters), encoding="utf-8"
    )

    src_lines = [
        "# WHITELIST_SOURCE.md",
        "",
        f"refreshed_at: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"refreshed_by: {actor}",
        "",
        "## PDFs",
    ]
    for pdf in pdfs:
        src_lines.append(f"- {pdf['name']}  sha256={pdf['sha256']}")
    (api_path / "WHITELIST_SOURCE.md").write_text("\n".join(src_lines), encoding="utf-8")
