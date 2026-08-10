"""结构化输出的 Pydantic 模型。

plan_task 用「提示词要纯 JSON + json_output_guardrail 按 schema 校验」产出
结构化的实现方案,供工程师 Agent 直接按文件拆分来写,而不是解析自由文本。

(说明:本项目所用本地代理模型不支持 API 级 output_pydantic,详见 guardrails.py。)
"""

from pydantic import BaseModel, Field


class FilePlan(BaseModel):
    """单个文件的实现规划。"""

    path: str = Field(description="相对 generated/ 的文件路径,如 retry.py 或 test_retry.py")
    purpose: str = Field(description="该文件的职责(一句话)")
    key_points: list[str] = Field(description="关键实现点列表")


class ImplementationPlan(BaseModel):
    """架构师的结构化产出:把编码需求拆成若干文件的实现方案。"""

    goal: str = Field(description="一句话目标")
    files: list[FilePlan] = Field(description="要创建的文件列表,1~4 个")
