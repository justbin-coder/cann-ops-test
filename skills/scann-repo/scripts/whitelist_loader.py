import re
from pathlib import Path
from typing import List, Pattern

LINE = re.compile(r'^\s*[-*]\s*([\w:]+)\s*$')

INFRASTRUCTURE_BLACKLIST: frozenset = frozenset({
    # Data containers / types (not compute APIs)
    "AscendC::LocalTensor",
    "AscendC::GlobalTensor",
    "AscendC::TBuf",
    "AscendC::TQue",
    "AscendC::TPipe",
    # Memory move (basic data movement, not cube/vector compute)
    "AscendC::DataCopy",
    "AscendC::DataCopyPad",
    "AscendC::DataCopyPadExtParams",
    # Pipeline / synchronization
    "AscendC::PipeBarrier",
    "AscendC::SetFlag",
    "AscendC::WaitFlag",
    # Block / pipe query
    "AscendC::GetBlockIdx",
    "AscendC::GetBlockNum",
    "AscendC::GetSubBlockIdx",
    "AscendC::GetSubBlockNum",
    "AscendC::GetTPipePtr",
    "AscendC::GetSysWorkSpacePtr",
    "AscendC::GetUserWorkspace",
    # Alignment / arithmetic helpers (not vector compute)
    "AscendC::AlignUp",
    "AscendC::AlignDown",
    "AscendC::DivCeil",
    # HCCL context (not cube/vector hardware feature)
    "AscendC::GetHcclContext",
    # Cube setup/config (not cube COMPUTE — real compute is Mmad/Matmul/LoadData/Fixpipe/etc)
    "AscendC::AippParams",
    "AscendC::SetAippFunctions",
    "AscendC::SetFixPipeAddr",
    "AscendC::SetFixPipeConfig",
    "AscendC::SetFixpipeNz2ndFlag",
    "AscendC::SetFixpipePreQuantFlag",
    "AscendC::SetFmatrix",
    "AscendC::SetHF32Mode",
    "AscendC::SetHF32TransMode",
    "AscendC::SetLoadDataBoundary",
    "AscendC::SetLoadDataPaddingValue",
    "AscendC::SetLoadDataRepeat",
    "AscendC::SetMMColumnMajor",
    "AscendC::SetMMRowMajor",
    "AscendC::FixpipeParamsArch3510",
    # Mask reset (not compute)
    "AscendC::ResetMask",
})

def load_whitelist(path: Path) -> List[str]:
    text = Path(path).read_text(encoding="utf-8")
    names = []
    seen = set()
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        name = m.group(1)
        if "::" not in name:    # 安全过滤,非全限定名跳过
            continue
        if name in INFRASTRUCTURE_BLACKLIST:
            continue
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names

def build_pattern(qualnames: List[str]) -> Pattern:
    if not qualnames:
        return re.compile(r"(?!x)x")    # never match
    bare_names = sorted({n.split("::")[-1] for n in qualnames}, key=len, reverse=True)
    qualnames_sorted = sorted(qualnames, key=len, reverse=True)
    ns_part = "|".join(re.escape(n) for n in qualnames_sorted)
    bare_part = "|".join(re.escape(n) for n in bare_names)
    return re.compile(
        rf"(?:\b(?:{ns_part})\s*[(<])"
        rf"|(?<![.\w>:])\b(?:{bare_part})\s*[(<]"
    )
