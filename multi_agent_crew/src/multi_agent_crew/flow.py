"""crewai Flow 示例:事件驱动编排,把多 Agent Crew 嵌入为流程中的一步。

流程拓扑(多路路由 + 并行扇出 + and_ 汇聚 + 有界循环):

    prepare(@start)                        准备输入,锚定工作目录到项目根
      └─> run_crew(@listen)                执行三 Agent Crew,产出 report.md
            └─> assess(@router)            按报告规模三路路由
                  ├─ "deliver" ──┬─ make_abstract(@listen)      并行:LLM 生成摘要
                  │              ├─ compute_metrics(@listen)    并行:确定性指标
                  │              ├─ extract_outline(@listen)    并行:提取大纲
                  │              └─ package(@listen and_(...))  汇聚三者,写交付摘要
                  ├─ "revise"  ──> expand(@listen)              LLM 扩充,revisions+1
                  │                  └─> reassess(@router)      有界循环重评(防死循环)
                  └─ "too_short"─> notify_short(@listen)        过短,放弃并提示

运行:
    cd multi_agent_crew
    python -m multi_agent_crew.flow          # 完整跑(含 Crew)
    FLOW_SKIP_CREW=1 python -m multi_agent_crew.flow   # 测试编排:跳过昂贵 Crew,复用现有 report.md
"""

from datetime import datetime
import os
from pathlib import Path

from crewai.flow.flow import Flow, and_, listen, router, start
from pydantic import BaseModel, Field

from .crew import MultiAgentCrew, _build_llm

# 项目根目录与 report.md 的绝对路径(与调用时的 cwd 无关)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = PROJECT_ROOT / "report.md"
SUMMARY_PATH = PROJECT_ROOT / "report_summary.md"

# 路由阈值(字节;中文 UTF-8 每字约 3 字节,完整报告约 13K)
DELIVER_BYTES = 2000   # >= 直接交付
REVISE_BYTES = 200     # [200, 2000) 需扩充; <200 过短
MAX_REVISIONS = 1      # 最多扩充次数,防止无限循环


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class ReportState(BaseModel):
    """Flow 状态,在各步骤之间流转。"""

    topic: str = "AI 大模型"
    current_year: str = ""
    report_bytes: int = 0
    revisions: int = 0
    abstract: str = ""
    outline: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)


class ReportFlow(Flow[ReportState]):
    """把多 Agent Crew 编排进一个事件驱动 Flow(多分支 + 并行 + 汇聚 + 有界循环)。"""

    # ---------------- 起点 ----------------
    @start()
    def prepare(self) -> None:
        """起点:准备输入参数,并把工作目录锚定到项目根(report.md 落点)。"""
        os.chdir(PROJECT_ROOT)  # crewai 的 output_file 按 cwd 相对写,先锚定到项目根
        self.state.current_year = str(datetime.now().year)
        self.state.revisions = 0
        print(f"[Flow] 起点 prepare: 主题={self.state.topic} 年份={self.state.current_year}")

    # ---------------- 执行 Crew ----------------
    @listen(prepare)
    def run_crew(self) -> None:
        """执行多 Agent Crew(研究员->写手->审校),产出 report.md。"""
        if _flag("FLOW_SKIP_CREW"):
            print("[Flow] run_crew: FLOW_SKIP_CREW=1,跳过 Crew 执行(复用现有 report.md)")
        else:
            print("[Flow] run_crew: 启动多 Agent Crew ...")
            MultiAgentCrew().crew().kickoff(
                inputs={
                    "topic": self.state.topic,
                    "current_year": self.state.current_year,
                }
            )
        self.state.report_bytes = REPORT_PATH.stat().st_size if REPORT_PATH.exists() else 0
        print(f"[Flow] run_crew 完成: report.md = {self.state.report_bytes} 字节")

    # ---------------- 路由(主) ----------------
    def _route(self) -> str:
        """按报告规模与已扩充次数决定分支。"""
        b = self.state.report_bytes
        if b >= DELIVER_BYTES:
            return "deliver"
        if b >= REVISE_BYTES and self.state.revisions < MAX_REVISIONS:
            return "revise"
        return "too_short"

    @router(run_crew, emit=["deliver", "revise", "too_short"])
    def assess(self) -> str:
        verdict = self._route()
        print(f"[Flow] assess 路由: {verdict} (report={self.state.report_bytes}B)")
        return verdict

    # ---------------- deliver 分支:并行后处理 ----------------
    @listen("deliver")
    def make_abstract(self) -> None:
        """并行分支①:用 LLM 给报告生成摘要。"""
        text = REPORT_PATH.read_text(encoding="utf-8")[:4000]
        llm = _build_llm(max_tokens=4096)
        self.state.abstract = llm.call(
            f"用 3 句话以内概括下面这份报告的核心结论,中文输出:\n\n{text}"
        )
        print(f"[Flow] make_abstract: 摘要 {len(self.state.abstract)} 字")

    @listen("deliver")
    def compute_metrics(self) -> None:
        """并行分支②:确定性计算报告指标(不调 LLM)。"""
        text = REPORT_PATH.read_text(encoding="utf-8")
        self.state.metrics = {
            "chars": len(text),
            "headings": sum(1 for ln in text.splitlines() if ln.startswith("#")),
            "reading_minutes": round(len(text) / 400, 1),
        }
        print(f"[Flow] compute_metrics: {self.state.metrics}")

    @listen("deliver")
    def extract_outline(self) -> None:
        """并行分支③:提取报告大纲(一二级标题,不调 LLM)。"""
        text = REPORT_PATH.read_text(encoding="utf-8")
        self.state.outline = [
            ln.strip() for ln in text.splitlines() if ln.startswith(("# ", "## "))
        ]
        print(f"[Flow] extract_outline: {len(self.state.outline)} 个标题")

    @listen(and_("make_abstract", "compute_metrics", "extract_outline"))
    def package(self) -> None:
        """汇聚:等三个并行分支都完成,产出交付摘要 report_summary.md。"""
        m = self.state.metrics
        summary = (
            f"# 报告交付摘要\n\n"
            f"## LLM 摘要\n{self.state.abstract}\n\n"
            f"## 指标\n- 字符数: {m.get('chars')}\n- 标题数: {m.get('headings')}\n"
            f"- 预计阅读: {m.get('reading_minutes')} 分钟\n\n"
            f"## 大纲\n" + "\n".join(self.state.outline) + "\n"
        )
        SUMMARY_PATH.write_text(summary, encoding="utf-8")
        print(f"[Flow] package: 交付摘要已写入 {SUMMARY_PATH}")

    # ---------------- revise 分支:扩充后重评(有界循环) ----------------
    @listen("revise")
    def expand(self) -> None:
        """报告偏短:用 LLM 扩充内容,revisions+1。"""
        self.state.revisions += 1
        text = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else ""
        llm = _build_llm(max_tokens=8192)
        expanded = llm.call(
            "下面这份报告内容偏少,请在保持原有结构的基础上扩写、补充具体例子与论述,"
            "使其更充实,输出完整 markdown 报告:\n\n" + text
        )
        REPORT_PATH.write_text(expanded, encoding="utf-8")
        self.state.report_bytes = REPORT_PATH.stat().st_size
        print(f"[Flow] expand: 第 {self.state.revisions} 次扩充,现 {self.state.report_bytes} 字节")

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
            f"[Flow] ✗ 报告偏短({self.state.report_bytes} 字节,已扩充 {self.state.revisions} 次),"
            "建议检查模型 max_tokens 后重跑。"
        )


def kickoff():
    """Flow 入口。"""
    return ReportFlow().kickoff()


if __name__ == "__main__":
    kickoff()
