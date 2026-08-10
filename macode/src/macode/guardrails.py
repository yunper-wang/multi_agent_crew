"""Task guardrail(护栏)函数:校验任务产出,不合格则打回重试。

crewai guardrail 约定:接收 TaskOutput,返回 Tuple[bool, Any]。
- (True, output)  → 通过,output 作为最终结果
- (False, message)→ 不通过,message 作为反馈让 Agent 重试
注意:返回类型注解必须严格是 Tuple[bool, Any],crewai 会校验。
"""

from typing import Any, Tuple

import json
import re

from crewai import TaskOutput
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# 结构化输出(JSON schema)校验 —— 用于 plan_task
#
# 说明:本项目所用本地代理模型强制开启 extended thinking 且不支持
# tool_choice / json_schema 等 API 级结构化输出,因此 crewai 的 output_pydantic
# 在此环境不可用。改用「提示词要求输出纯 JSON + guardrail 按 Pydantic schema
# 校验、不合格打回重试」的方式,达到等价的结构化产出。
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> str:
    """从模型输出中提取 JSON 串:去 markdown 围栏,截取首个 { 到末个 }。"""
    t = (text or "").strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
        if m:
            t = m.group(1).strip()
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            t = t[start : end + 1]
    return t


def json_output_guardrail(model: type[BaseModel]):
    """生成一个 JSON-schema 校验器:要求产出为符合 model 的纯 JSON。"""

    def _check(output: TaskOutput) -> Tuple[bool, Any]:
        candidate = _extract_json(output.raw or "")
        try:
            data = json.loads(candidate)
            model.model_validate(data)
        except Exception as e:  # JSON 解析或 schema 校验失败 → 打回重试
            return (
                False,
                "输出需为符合要求的**纯 JSON**(不要 markdown 围栏、不要额外解释文字)。"
                f"schema 字段: {list(model.model_fields.keys())}。"
                f"错误: {type(e).__name__}: {str(e)[:150]}",
            )
        return (True, output)

    return _check


# ---------------------------------------------------------------------------
# 代码产物校验 —— 用于 review_task
# ---------------------------------------------------------------------------


def code_solution_guardrail(min_chars: int = 200):
    """代码评审产物校验:必须含 ```python 代码块,且达到一定篇幅。"""

    def _check(output: TaskOutput) -> Tuple[bool, Any]:
        text = output.raw or ""
        if "```python" not in text and "```py" not in text:
            return (
                False,
                "产出缺少 ```python 代码块。请把最终代码放在 ```python 围栏中,并附评审说明。",
            )
        if len(text) < min_chars:
            return (
                False,
                f"产出太短({len(text)} 字),未达到 {min_chars} 字。请给出完整代码与评审说明。",
            )
        return (True, output)

    return _check
