"""结构化输出的 Pydantic 模型。

research_task 用 output_pydantic=ResearchFindings 产出结构化结果,
供下游任务/系统直接以对象方式消费,而不是解析一大段自由文本。
"""

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """单条调研要点。"""

    point: str = Field(description="核心信息要点(一句话)")
    example: str = Field(description="对应的落地例子或数据")
    relevance: str = Field(description="该要点如何呼应用户偏好")


class ResearchFindings(BaseModel):
    """研究员的结构化产出。"""

    topic: str = Field(description="调研主题")
    findings: list[Finding] = Field(description="调研要点列表,3~5 条")
