from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class SyntaxCheckInput(BaseModel):
    """PythonSyntaxCheckTool 的输入。"""

    code: str = Field(..., description="要检查的 Python 源代码字符串")


class PythonSyntaxCheckTool(BaseTool):
    """Python 语法检查工具:用 ast 解析校验语法合法性(只解析、不执行)。

    评审 Agent 用它来客观验证工程师写出的代码语法是否正确,并定位到行号。
    """

    name: str = "python_syntax_check"
    description: str = (
        "检查一段 Python 代码的语法是否合法(不执行代码,只做静态解析)。"
        "传入源代码字符串,返回语法是否通过;若不通过会给出错误行号与原因。"
    )
    args_schema: Type[BaseModel] = SyntaxCheckInput

    def _run(self, code: str) -> str:
        import ast

        try:
            ast.parse(code)
        except SyntaxError as e:
            return f"语法错误: 第 {e.lineno} 行 {e.msg} ({(e.text or '').strip()})"
        except Exception as e:  # 极端情况(如编码问题)
            return f"解析失败: {type(e).__name__}: {e}"
        return "语法正确: 通过 ast 解析,无语法错误。"
