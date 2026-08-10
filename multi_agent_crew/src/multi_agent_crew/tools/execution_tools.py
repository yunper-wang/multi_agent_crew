"""执行类自定义工具:让 coding agent 能真正**运行**代码/命令并拿到结果。

安全边界:
- 所有执行的工作目录都限定在 WORKSPACE(项目 generated/ 目录)内;
- 有超时与输出截断;
- ShellCommandTool 会拦截少数灾难性命令(并非完整沙箱,仅面向本项目的编码验证用途)。
"""

from pathlib import Path
import os
import subprocess
import sys
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# 代码工作区 = 项目根的 generated/ 目录(从包位置推算)。
# tools/execution_tools.py -> parents[3] 是项目根。
WORKSPACE = Path(__file__).resolve().parents[3] / "generated"

_MAX_OUTPUT = 4000      # 输出截断长度
_DEFAULT_TIMEOUT = 60   # 秒

# 明显灾难性的命令片段(最小防护,非完整沙箱)。
_BLOCKED = ("rm -rf /", "rm -rf ~", "mkfs", ":(){ :|:& };:", "> /dev/sda", "dd if=")


def _exec_env() -> dict:
    """构造子进程环境:把当前解释器(venv)的 bin 目录提到 PATH 最前。

    这样 shell 里的 `python` / `pytest` 等命令会用 agent 自己的 Python 环境,
    而不是系统 Python(否则可能缺 pytest 等已装依赖)。
    """
    env = dict(os.environ)
    # 注意:不能 resolve() sys.executable —— 它是 venv 里的符号链接,
    # resolve 后会指向不带依赖的基础 Python。要用 venv 的 bin 目录。
    venv_bin = str(Path(sys.executable).parent)
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    return env


def _truncate(text: str) -> str:
    if len(text) > _MAX_OUTPUT:
        return text[:_MAX_OUTPUT] + f"\n... (输出过长已截断,共 {len(text)} 字符)"
    return text


def _safe_path(path: str) -> Path:
    """把用户给的路径解析到 WORKSPACE 内,防止 ../ 逃逸。"""
    p = (WORKSPACE / path).resolve()
    if WORKSPACE.resolve() not in p.parents and p != WORKSPACE.resolve():
        raise ValueError(f"路径越界: {path} 不在工作区 {WORKSPACE} 内")
    return p


class ShellInput(BaseModel):
    command: str = Field(..., description="要执行的 shell 命令(在工作区目录下运行)")


class ShellCommandTool(BaseTool):
    """在工作区内执行 shell 命令(装依赖/构建/跑脚本等),返回退出码与输出。"""

    name: str = "shell_command"
    description: str = (
        f"在代码工作区(generated/)执行一条 shell 命令,返回退出码、stdout 与 stderr。"
        "用于安装依赖、运行构建、执行脚本、查看环境等。命令有超时限制。"
    )
    args_schema: Type[BaseModel] = ShellInput

    def _run(self, command: str) -> str:
        low = command.lower()
        if any(b in low for b in _BLOCKED):
            return f"已拒绝执行:命令包含危险操作片段。({command[:80]})"
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(WORKSPACE),
                capture_output=True, text=True, timeout=_DEFAULT_TIMEOUT,
                env=_exec_env(),
            )
        except subprocess.TimeoutExpired:
            return f"命令超时(>{_DEFAULT_TIMEOUT}s)被终止: {command[:80]}"
        out = proc.stdout or ""
        err = proc.stderr or ""
        return (
            f"退出码: {proc.returncode}\n"
            f"--- stdout ---\n{_truncate(out) or '(空)'}\n"
            f"--- stderr ---\n{_truncate(err) or '(空)'}"
        )


class PythonRunInput(BaseModel):
    file_path: str = Field(..., description="要运行的 Python 文件(相对工作区,如 retry.py)")
    args: str = Field(default="", description="可选命令行参数")


class PythonRunTool(BaseTool):
    """运行一个 Python 文件,返回其 stdout/stderr 与退出码(用于验证代码能跑)。"""

    name: str = "python_run"
    description: str = (
        "运行工作区内的一个 Python 文件,返回退出码、stdout、stderr。"
        "用于验证代码能否正常执行、查看运行输出。"
    )
    args_schema: Type[BaseModel] = PythonRunInput

    def _run(self, file_path: str, args: str = "") -> str:
        try:
            target = _safe_path(file_path)
        except ValueError as e:
            return str(e)
        if not target.exists():
            return f"文件不存在: {file_path}(工作区内)"
        import sys
        try:
            proc = subprocess.run(
                [sys.executable, str(target)] + (args.split() if args else []),
                cwd=str(WORKSPACE), capture_output=True, text=True, timeout=_DEFAULT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return f"运行超时(>{_DEFAULT_TIMEOUT}s): {file_path}"
        return (
            f"退出码: {proc.returncode}\n"
            f"--- stdout ---\n{_truncate(proc.stdout or '') or '(空)'}\n"
            f"--- stderr ---\n{_truncate(proc.stderr or '') or '(空)'}"
        )


class PytestInput(BaseModel):
    path: str = Field(default=".", description="pytest 目标(相对工作区,如 tests/ 或 test_x.py)")
    extra_args: str = Field(default="", description="额外 pytest 参数,如 -q -k expr")


class PytestRunTool(BaseTool):
    """运行 pytest,返回测试结果摘要(用于客观验证代码是否通过测试)。"""

    name: str = "pytest_run"
    description: str = (
        "在工作区内运行 pytest(默认 -q),返回通过/失败统计与失败详情。"
        "用于客观验证代码是否正确。"
    )
    args_schema: Type[BaseModel] = PytestInput

    def _run(self, path: str = ".", extra_args: str = "") -> str:
        import sys
        try:
            target = _safe_path(path)
        except ValueError as e:
            return str(e)
        if not target.exists():
            return f"路径不存在: {path}(工作区内)"
        cmd = [sys.executable, "-m", "pytest", str(target), "-q"] + (extra_args.split() if extra_args else [])
        try:
            proc = subprocess.run(
                cmd, cwd=str(WORKSPACE), capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            return "pytest 运行超时(>180s)"
        tail = "\n".join((proc.stdout or "").splitlines()[-30:])  # 取结果尾部
        return (
            f"退出码: {proc.returncode}(0=全部通过)\n"
            f"--- pytest 输出(尾部) ---\n{_truncate(tail) or '(空)'}\n"
            f"--- stderr ---\n{_truncate(proc.stderr or '') or '(空)'}"
        )
