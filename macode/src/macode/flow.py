"""crewai Flow 示例(coding agent 版):事件驱动编排,把编码 Crew 嵌入为流程中的一步。

流程拓扑(多路路由 + 并行扇出 + and_ 汇聚 + 有界循环):

    prepare(@start)                        准备编码需求,锚定工作目录到项目根
      └─> run_crew(@listen)                执行 架构师->工程师->评审 Crew,产出 solution.md
            └─> assess(@router)            按产物规模三路路由
                  ├─ "deliver" ──┬─ make_abstract(@listen)      并行:LLM 生成方案摘要
                  │              ├─ compute_metrics(@listen)    并行:确定性指标
                  │              ├─ extract_outline(@listen)    并行:提取结构
                  │              └─ package(@listen and_(...))  汇聚三者,写交付摘要
                  ├─ "revise"  ──> expand(@listen)              LLM 扩充/补全,revisions+1
                  │                  └─> reassess(@router)      有界循环重评(防死循环)
                  └─ "too_short"─> notify_short(@listen)        过短,放弃并提示

运行:
    cd macode
    python -m macode.flow          # 完整跑(含 Crew)
    FLOW_SKIP_CREW=1 python -m macode.flow   # 测试编排:跳过昂贵 Crew,复用现有 solution.md
"""

from datetime import datetime
import os
from pathlib import Path

from crewai.flow.flow import Flow, and_, listen, router, start
from pydantic import BaseModel, Field

from .crew import MultiAgentCrew, WORKSPACE, _build_llm
from .main import DEFAULT_REQUIREMENT, resolve_requirement

# 产物路径(落在用户工作区)
SOLUTION_PATH = WORKSPACE / "solution.md"
SUMMARY_PATH = WORKSPACE / "solution_summary.md"

# 路由阈值(字节)
DELIVER_BYTES = 2000   # >= 直接交付
REVISE_BYTES = 200     # [200, 2000) 需扩充; <200 过短
MAX_REVISIONS = 1      # 最多扩充次数,防止无限循环


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class SolutionState(BaseModel):
    """Flow 状态,在各步骤之间流转。"""

    requirement: str = DEFAULT_REQUIREMENT
    solution_bytes: int = 0
    revisions: int = 0
    abstract: str = ""
    outline: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)


class CodingFlow(Flow[SolutionState]):
    """把编码 Crew 编排进一个事件驱动 Flow(多分支 + 并行 + 汇聚 + 有界循环)。"""

    # ---------------- 起点 ----------------
    @start()
    def prepare(self) -> None:
        """起点:准备编码需求(支持命令行/环境变量覆盖),锚定工作目录到用户工作区。"""
        os.chdir(WORKSPACE)  # crewai 的 output_file 按 cwd 相对写,锚定到工作区
        self.state.requirement = resolve_requirement()
        self.state.revisions = 0
        print(f"[Flow] 起点 prepare: 需求={self.state.requirement[:40]}...")

    # ---------------- 执行 Crew ----------------
    @listen(prepare)
    def run_crew(self) -> None:
        """执行编码 Crew(架构师->工程师->评审),产出 solution.md。"""
        if _flag("FLOW_SKIP_CREW"):
            print("[Flow] run_crew: FLOW_SKIP_CREW=1,跳过 Crew 执行(复用现有 solution.md)")
        else:
            print("[Flow] run_crew: 启动编码 Crew ...")
            MultiAgentCrew().crew().kickoff(
                inputs={"requirement": self.state.requirement}
            )
        self.state.solution_bytes = SOLUTION_PATH.stat().st_size if SOLUTION_PATH.exists() else 0
        print(f"[Flow] run_crew 完成: solution.md = {self.state.solution_bytes} 字节")

    # ---------------- 路由(主) ----------------
    def _route(self) -> str:
        """按产物规模与已扩充次数决定分支。"""
        b = self.state.solution_bytes
        if b >= DELIVER_BYTES:
            return "deliver"
        if b >= REVISE_BYTES and self.state.revisions < MAX_REVISIONS:
            return "revise"
        return "too_short"

    @router(run_crew, emit=["deliver", "revise", "too_short"])
    def assess(self) -> str:
        verdict = self._route()
        print(f"[Flow] assess 路由: {verdict} (solution={self.state.solution_bytes}B)")
        return verdict

    # ---------------- deliver 分支:并行后处理 ----------------
    @listen("deliver")
    def make_abstract(self) -> None:
        """并行分支①:用 LLM 给编码方案生成摘要。"""
        text = SOLUTION_PATH.read_text(encoding="utf-8")[:4000]
        llm = _build_llm(max_tokens=4096)
        self.state.abstract = llm.call(
            "用 3 句话以内概括下面这份编码交付物的实现思路与要点,中文输出:\n\n" + text
        )
        print(f"[Flow] make_abstract: 摘要 {len(self.state.abstract)} 字")

    @listen("deliver")
    def compute_metrics(self) -> None:
        """并行分支②:确定性计算产物指标(不调 LLM)。"""
        text = SOLUTION_PATH.read_text(encoding="utf-8")
        self.state.metrics = {
            "chars": len(text),
            "code_blocks": text.count("```python") + text.count("```py"),
            "headings": sum(1 for ln in text.splitlines() if ln.startswith("#")),
        }
        print(f"[Flow] compute_metrics: {self.state.metrics}")

    @listen("deliver")
    def extract_outline(self) -> None:
        """并行分支③:提取产物结构(一二级标题,不调 LLM)。"""
        text = SOLUTION_PATH.read_text(encoding="utf-8")
        self.state.outline = [
            ln.strip() for ln in text.splitlines() if ln.startswith(("# ", "## "))
        ]
        print(f"[Flow] extract_outline: {len(self.state.outline)} 个标题")

    @listen(and_("make_abstract", "compute_metrics", "extract_outline"))
    def package(self) -> None:
        """汇聚:等三个并行分支都完成,产出交付摘要 solution_summary.md。"""
        m = self.state.metrics
        summary = (
            f"# 编码交付摘要\n\n"
            f"## LLM 摘要\n{self.state.abstract}\n\n"
            f"## 指标\n- 字符数: {m.get('chars')}\n- 代码块数: {m.get('code_blocks')}\n"
            f"- 标题数: {m.get('headings')}\n\n"
            f"## 结构\n" + "\n".join(self.state.outline) + "\n"
        )
        SUMMARY_PATH.write_text(summary, encoding="utf-8")
        print(f"[Flow] package: 交付摘要已写入 {SUMMARY_PATH}")

    # ---------------- revise 分支:扩充后重评(有界循环) ----------------
    @listen("revise")
    def expand(self) -> None:
        """产物偏短:用 LLM 补全/完善代码与说明,revisions+1。"""
        self.state.revisions += 1
        text = SOLUTION_PATH.read_text(encoding="utf-8") if SOLUTION_PATH.exists() else ""
        llm = _build_llm(max_tokens=8192)
        expanded = llm.call(
            "下面这份编码交付物内容不完整,请补全:确保每个文件都有完整可运行的 "
            "```python 代码块(含测试)和评审说明,输出完整 markdown:\n\n" + text
        )
        SOLUTION_PATH.write_text(expanded, encoding="utf-8")
        self.state.solution_bytes = SOLUTION_PATH.stat().st_size
        print(f"[Flow] expand: 第 {self.state.revisions} 次扩充,现 {self.state.solution_bytes} 字节")

    @router(expand, emit=["deliver", "revise", "too_short"])
    def reassess(self) -> str:
        """扩充后重评;revisions 已达上限则不再 loop。"""
        verdict = self._route()
        print(f"[Flow] reassess 路由: {verdict} (revisions={self.state.revisions})")
        return verdict

    # ---------------- too_short 分支 ----------------
    @listen("too_short")
    def notify_short(self) -> None:
        print(
            f"[Flow] ✗ 产物偏短({self.state.solution_bytes} 字节,已扩充 {self.state.revisions} 次),"
            "建议检查模型 max_tokens 后重跑。"
        )


def kickoff():
    """Flow 入口。"""
    return CodingFlow().kickoff()


if __name__ == "__main__":
    kickoff()
