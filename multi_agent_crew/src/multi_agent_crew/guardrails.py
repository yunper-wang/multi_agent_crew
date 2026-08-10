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


def min_length_guardrail(min_chars: int = 300):
    """生成一个「最小长度」校验器(闭包),可按需调整阈值。"""

    def _check(output: TaskOutput) -> Tuple[bool, Any]:
        text = output.raw or ""
        if len(text) < min_chars:
            return (
                False,
                f"内容太短({len(text)} 字),未达到 {min_chars} 字要求。请扩写,确保每个要点论述充分、含具体例子。",
            )
        return (True, output)

    return _check


def contains_markdown_heading_guardrail(output: TaskOutput) -> Tuple[bool, Any]:
    """校验产出是带标题的 markdown 报告。"""
    text = output.raw or ""
    if "#" not in text:
        return (False, "产出缺少 markdown 标题(# 开头),请补全标题与分节结构。")
    return (True, output)


def report_guardrail(min_chars: int = 300):
    """报告专用组合校验:先查结构(markdown 标题),再查篇幅(最小字数)。"""

    def _check(output: TaskOutput) -> Tuple[bool, Any]:
        ok, res = contains_markdown_heading_guardrail(output)
        if not ok:
            return ok, res
        return min_length_guardrail(min_chars)(output)

    return _check


# ---------------------------------------------------------------------------
# 结构化输出(JSON schema)校验
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
