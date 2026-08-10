"""搜索/浏览类自定义工具:让 coding agent 能探索代码库。

CodeSearchTool:按正则 grep 代码;ListDirTool:查看目录树。
都限定在项目工作区内,输出有截断。
"""

from pathlib import Path
import os
import re
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# 用户工作区(从运行时 cwd 推算,可用 MAC_WORKSPACE 覆盖)——搜索/浏览针对用户项目。
WORKSPACE = Path(os.environ.get("MAC_WORKSPACE") or os.getcwd()).resolve()

_MAX_RESULTS = 50
_MAX_OUTPUT = 4000
_IGNORE = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache"}


def _truncate(text: str) -> str:
    return text[:_MAX_OUTPUT] + "\n... (已截断)" if len(text) > _MAX_OUTPUT else text


class CodeSearchInput(BaseModel):
    pattern: str = Field(..., description="正则表达式(按内容搜索,如 'def retry')")
    path: str = Field(default=".", description="搜索范围(相对项目根,默认整个项目)")


class CodeSearchTool(BaseTool):
    """在项目代码里按正则搜索内容,返回 文件:行号:内容 的命中列表。"""

    name: str = "code_search"
    description: str = (
        "按正则表达式在项目代码中搜索内容,返回 '文件:行号: 内容' 的命中列表。"
        "用于定位函数/类/变量的定义与使用。"
    )
    args_schema: Type[BaseModel] = CodeSearchInput

    def _run(self, pattern: str, path: str = ".") -> str:
        base = (WORKSPACE / path).resolve()
        if WORKSPACE not in base.parents and base != WORKSPACE:
            return f"路径越界: {path}"
        if not base.exists():
            return f"路径不存在: {path}"
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"正则非法: {e}"
        hits = []
        for f in sorted(base.rglob("*")):
            if not f.is_file() or any(part in _IGNORE for part in f.parts):
                continue
            if f.suffix not in (".py", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg"):
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{f.relative_to(WORKSPACE)}:{i}: {line.strip()[:120]}")
                        if len(hits) >= _MAX_RESULTS:
                            break
            except Exception:
                continue
            if len(hits) >= _MAX_RESULTS:
                break
        if not hits:
            return f"无命中: /{pattern}/ 在 {path}"
        return _truncate("\n".join(hits))


class ListDirInput(BaseModel):
    path: str = Field(default=".", description="目录(相对项目根,默认当前)")
    max_depth: int = Field(default=3, description="递归深度")


class ListDirTool(BaseTool):
    """以树形列出目录结构(忽略 .git/.venv/__pycache__ 等),用于了解项目布局。"""

    name: str = "list_dir"
    description: str = "以树形列出目录结构,用于快速了解项目布局与文件分布。"
    args_schema: Type[BaseModel] = ListDirInput

    def _run(self, path: str = ".", max_depth: int = 3) -> str:
        base = (WORKSPACE / path).resolve()
        if WORKSPACE not in base.parents and base != WORKSPACE:
            return f"路径越界: {path}"
        if not base.is_dir():
            return f"不是目录: {path}"
        lines: list[str] = []

        def walk(d: Path, depth: int, prefix: str) -> None:
            if depth > max_depth or len(lines) > _MAX_RESULTS:
                return
            try:
                entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
            except PermissionError:
                return
            for e in entries:
                if e.name in _IGNORE:
                    continue
                lines.append(f"{prefix}{'📄' if e.is_file() else '📁'} {e.name}")
                if e.is_dir():
                    walk(e, depth + 1, prefix + "  ")

        walk(base, 1, "")
        return _truncate(f"{base.relative_to(WORKSPACE) or '.'}/\n" + "\n".join(lines)) if lines else "(空目录)"
