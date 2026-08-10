"""crewai Flow 示例:事件驱动编排,把多 Agent Crew 嵌入为流程中的一步。

流程拓扑:
    prepare(@start)
        └─> run_crew(@listen)          执行三 Agent Crew,产出 report.md
              └─> assess(@router)      按报告规模路由
                    ├─ "deliver"   -> finalize(@listen)    达标,交付
                    └─ "too_short" -> notify_short(@listen) 偏短,提示重跑

运行:
    cd multi_agent_crew
    python -m multi_agent_crew.flow
"""

from datetime import datetime
import os
from pathlib import Path

from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel

from .crew import MultiAgentCrew

# 项目根目录与 report.md 的绝对路径(与调用时的 cwd 无关)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = PROJECT_ROOT / "report.md"
# 判定「报告达标」的字节阈值(中文 UTF-8 每字 3 字节;完整报告约 14K)
MIN_REPORT_BYTES = 2000


class ReportState(BaseModel):
    """Flow 状态,在各步骤之间流转。"""

    topic: str = "AI 大模型"
    current_year: str = ""
    report_bytes: int = 0


class ReportFlow(Flow[ReportState]):
    """把多 Agent Crew 编排进一个事件驱动 Flow。"""

    @start()
    def prepare(self) -> None:
        """起点:准备输入参数,并把工作目录锚定到项目根(report.md 落点)。"""
        os.chdir(PROJECT_ROOT)  # crewai 的 output_file 按 cwd 相对写,先锚定到项目根
        self.state.current_year = str(datetime.now().year)
        print(f"[Flow] 起点 prepare: 主题={self.state.topic} 年份={self.state.current_year}")

    @listen(prepare)
    def run_crew(self) -> None:
        """执行多 Agent Crew(研究员->写手->审校),产出 report.md。"""
        print("[Flow] run_crew: 启动多 Agent Crew ...")
        MultiAgentCrew().crew().kickoff(
            inputs={
                "topic": self.state.topic,
                "current_year": self.state.current_year,
            }
        )
        self.state.report_bytes = REPORT_PATH.stat().st_size if REPORT_PATH.exists() else 0
        print(f"[Flow] run_crew 完成: report.md = {self.state.report_bytes} 字节")

    @router(run_crew)
    def assess(self) -> str:
        """路由:按报告规模决定后续分支。"""
        verdict = "deliver" if self.state.report_bytes >= MIN_REPORT_BYTES else "too_short"
        print(f"[Flow] assess 路由: {verdict}")
        return verdict

    @listen("deliver")
    def finalize(self) -> None:
        print(f"[Flow] ✓ 报告达标({self.state.report_bytes} 字节),可交付: {REPORT_PATH}")

    @listen("too_short")
    def notify_short(self) -> None:
        print(f"[Flow] ✗ 报告偏短({self.state.report_bytes} 字节),建议检查模型 max_tokens 后重跑。")


def kickoff():
    """Flow 入口。"""
    return ReportFlow().kickoff()


if __name__ == "__main__":
    kickoff()
