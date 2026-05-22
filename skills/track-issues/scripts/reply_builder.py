"""Build markdown reply text for PASS / FAIL retest outcomes."""
from __future__ import annotations

_PASS_TMPL = """\
感谢您的回复！

我们按照您提供的方案（`{fix_kind}`：`{fix_summary}`）在本地重新跑测，结果如下：

- **算子**：`{repo}` / `{op}`
- **SOC**：`{soc}`
- **结果**：✅ **PASS**

修复信息已记录到本地 FAQ，后续遇到相同问题将自动提示。

此 issue 将标记为已解决并关闭，感谢社区支持！
"""

_FAIL_TMPL = """\
感谢您的回复！

我们尝试了您提供的方案（`{fix_kind}`：`{fix_summary}`）在本地重新跑测，但问题未能解决：

- **算子**：`{repo}` / `{op}`
- **SOC**：`{soc}`
- **结果**：❌ **FAIL**

错误摘要：
```
{error_snippet}
```

能否提供更多信息？例如完整环境配置或其他排查思路，非常感谢。
"""


def build_pass_reply(*, repo: str, op: str, soc: str, fix_kind: str, fix_summary: str) -> str:
    return _PASS_TMPL.format(
        repo=repo, op=op, soc=soc,
        fix_kind=fix_kind, fix_summary=fix_summary,
    ).strip()


def build_fail_reply(
    *,
    repo: str,
    op: str,
    soc: str,
    fix_kind: str,
    fix_summary: str,
    error_snippet: str = "",
) -> str:
    snippet = (error_snippet or "（无详细错误信息）")[:800]
    return _FAIL_TMPL.format(
        repo=repo, op=op, soc=soc,
        fix_kind=fix_kind, fix_summary=fix_summary,
        error_snippet=snippet,
    ).strip()
