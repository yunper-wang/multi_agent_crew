from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class TextStatsInput(BaseModel):
    """TextStatsTool 的输入。"""

    text: str = Field(..., description="要统计的文本内容")


class TextStatsTool(BaseTool):
    """文本统计工具:给审校 Agent 用来量化检查报告篇幅是否达标。"""

    name: str = "text_stats"
    description: str = (
        "统计一段中文文本的字符数、行数、段落数,并估算阅读时长(分钟)。"
        "当你需要确认一篇报告/文章是否达到篇幅或结构要求时使用。"
    )
    args_schema: Type[BaseModel] = TextStatsInput

    def _run(self, text: str) -> str:
        chars = len(text)
        lines = text.count("\n") + 1 if text else 0
        paragraphs = len([p for p in text.split("\n\n") if p.strip()])
        minutes = round(chars / 400, 1)  # 中文约 400 字/分钟
        return (
            f"字符数:{chars} 行数:{lines} 段落数:{paragraphs} "
            f"预计阅读时长:{minutes} 分钟"
        )
