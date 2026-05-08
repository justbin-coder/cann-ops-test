import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Pattern

SCAN_DIRS = ["op_kernel", "op_host", "op_graph", "op_api"]
SCAN_EXTS = {".cpp", ".cc", ".cxx", ".h", ".hpp"}
RULE_NAMES = ["simt", "hif8", "regbase"]   # cv_fusion added in Task 5

PATTERNS = {
    "simt":    re.compile(r"__simt_vf__"),
    "hif8":    re.compile(r"\bHIFLOAT8\b"),
    "regbase": re.compile(r"AscendC::MicroAPI::RegTensor\b"),
}

@dataclass
class Hit:
    file: str       # path relative to op_dir
    line: int
    match: str

def _iter_source_files(op_dir: Path):
    for sub in SCAN_DIRS:
        d = op_dir / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix in SCAN_EXTS:
                yield p

def _iter_kernel_files(op_dir: Path):
    """Iterate only op_kernel source files (for CV fusion scanning)."""
    d = op_dir / "op_kernel"
    if not d.is_dir():
        return
    for p in d.rglob("*"):
        if p.is_file() and p.suffix in SCAN_EXTS:
            yield p

def scan_simple_rules(op_dir: Path) -> Dict[str, List[Hit]]:
    hits = {r: [] for r in RULE_NAMES}
    op_dir = Path(op_dir)
    for f in _iter_source_files(op_dir):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(f.relative_to(op_dir))
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rule in RULE_NAMES:
                m = PATTERNS[rule].search(line)
                if m:
                    hits[rule].append(Hit(file=rel, line=lineno, match=m.group(0)))
    return hits

def scan_cv_fusion(
    op_dir: Path,
    cube_pattern: Pattern,
    vector_pattern: Pattern,
) -> Optional[Dict[str, List[Hit]]]:
    cube_hits: List[Hit] = []
    vector_hits: List[Hit] = []
    op_dir = Path(op_dir)
    for f in _iter_kernel_files(op_dir):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(f.relative_to(op_dir))
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in cube_pattern.finditer(line):
                cube_hits.append(Hit(file=rel, line=lineno, match=m.group(0)))
            for m in vector_pattern.finditer(line):
                vector_hits.append(Hit(file=rel, line=lineno, match=m.group(0)))
    if cube_hits and vector_hits:
        return {"cube": cube_hits, "vector": vector_hits}
    return None
