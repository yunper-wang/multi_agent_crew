"""动态工作流编排层(Pi-Dynamic-Workflows 风格),叠加在 coding agent 之上。

对应 Pi-Dynamic-Workflows 的核心能力在本项目的实现:
- **动态工作流**   : 子任务不是写死的,而是架构师根据需求**动态规划**出来再扇出
- **并行子代理**   : 每个文件一个 worker,用 ThreadPoolExecutor **并行**执行(LLM 调用是 I/O 密集)
- **模型路由**     : 按文件类型把子任务路由到不同档位 LLM(核心逻辑 vs 测试/配置)
- **成本核算**     : 聚合各 worker 的 usage_metrics,报告 token 用量
- **持久化/可恢复**: @persist 把 Flow 状态落 SQLite,崩溃后可按 id 恢复续跑

与 flow.py 的区别:flow.py 是「固定 Crew + 事件分支」;本模块是「动态规划 + 并行扇出」。

运行:
    cd multi_agent_crew
    python -m multi_agent_crew.dynamic_flow
    DYN_SKIP_PLAN=1 python -m multi_agent_crew.dynamic_flow   # 测试:跳过 LLM 规划,用内置小计划
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from crewai import Agent, Crew, LLM, Task
from crewai.flow.flow import Flow, listen, start
from crewai.flow.persistence import persist
from crewai_tools import FileWriterTool
from pydantic import BaseModel, Field

from .crew import GENERATED_DIR, PROJECT_ROOT, _build_llm
from .guardrails import _extract_json, json_output_guardrail
from .main import DEFAULT_REQUIREMENT
from .output_models import ImplementationPlan
from .tools import PytestRunTool


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _tier_llm(path: str) -> LLM:
    """模型路由:按文件类型分配不同档位的 LLM。

    核心逻辑文件 -> 高档(更多思考/输出额度);测试/配置 -> 低档(更快更省)。
    在多提供方环境下,这里可分别指向不同的真实模型;本代理由同一上游兜底,
    故以 max_tokens/temperature 区分档位来演示路由结构。
    """
    name = Path(path).name.lower()
    if name.startswith("test_") or name in ("conftest.py", "__init__.py"):
        return _build_llm(max_tokens=8192)     # fast 档
    return _build_llm(max_tokens=16384)        # strong 档


def _tier_name(path: str) -> str:
    name = Path(path).name.lower()
    return "fast" if (name.startswith("test_") or name in ("conftest.py", "__init__.py")) else "strong"


class DynamicState(BaseModel):
    """动态工作流状态(@persist 需要 id 字段)。"""

    id: str = "dynamic-coding-flow"
    requirement: str = DEFAULT_REQUIREMENT
    planned_files: list[str] = Field(default_factory=list)
    worker_results: list[dict] = Field(default_factory=list)
    total_tokens: int = 0
    verify_tail: str = ""


@persist(verbose=True)  # 持久化:每个 Flow 方法完成后把 state 落 SQLite,崩溃可按 id 恢复
class DynamicCodingFlow(Flow[DynamicState]):
    """动态工作流:动态规划子任务 -> 并行子代理 -> 模型路由 -> 成本核算 -> 验证。"""

    @start()
    def prepare(self) -> None:
        """起点:准备工作目录与输出目录。"""
        os.chdir(PROJECT_ROOT)
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[Dyn] 起点 prepare: 需求={self.state.requirement[:40]}...")

    @listen(prepare)
    def plan(self) -> None:
        """动态规划:架构师把需求拆成若干文件子任务(数量/内容运行时决定)。"""
        if _flag("DYN_SKIP_PLAN"):
            # 测试模式:跳过 LLM 规划,用内置小计划
            self.state.planned_files = ["retry.py", "test_retry.py"]
            print(f"[Dyn] plan: DYN_SKIP_PLAN=1,内置计划 {self.state.planned_files}")
            return
        architect = Agent(
            role="资深软件架构师", goal="把编码需求拆成文件级实现方案",
            backstory="经验丰富,输出结构化方案", llm=_build_llm(), verbose=False,
        )
        task = Task(
            description=(
                f"把以下编码需求拆成文件级实现方案,只输出纯 JSON(无围栏): {self.state.requirement}"
            ),
            expected_output='{"goal":"...","files":[{"path":"...","purpose":"...","key_points":["..."]}]}',
            agent=architect,
            guardrail=json_output_guardrail(ImplementationPlan),
        )
        out = Crew(agents=[architect], tasks=[task], verbose=False).kickoff()
        plan = ImplementationPlan.model_validate(json.loads(_extract_json(out.raw)))
        self.state.planned_files = [f.path for f in plan.files]
        print(f"[Dyn] plan: 动态规划出 {len(self.state.planned_files)} 个子任务: {self.state.planned_files}")

    @listen(plan)
    def fan_out(self) -> None:
        """并行子代理:每个文件一个 worker 并行写代码,按类型路由模型,聚合 token 用量。"""
        files = self.state.planned_files

        def work(path: str) -> dict:
            tier = _tier_name(path)
            coder = Agent(
                role="高级 Python 工程师", goal=f"写出 {path} 的完整可运行代码",
                backstory="严谨,代码规范", llm=_tier_llm(path), verbose=False,
                tools=[FileWriterTool(base_dir=str(PROJECT_ROOT))],
            )
            task = Task(
                description=(
                    f"根据需求 '{self.state.requirement}',用 file_writer_tool 把文件 {path} 的"
                    f"完整代码写入 generated/(调用时 directory 用 \"generated\")。代码要可运行、符合规范。"
                ),
                expected_output=f"已写入 generated/{path}",
                agent=coder,
            )
            crew = Crew(agents=[coder], tasks=[task], verbose=False)
            crew.kickoff()
            um = crew.usage_metrics
            return {
                "file": path, "tier": tier,
                "tokens": (um.total_tokens if um else 0),
                "ok": (GENERATED_DIR / path).exists(),
            }

        # 并行执行(LLM 调用是 I/O 密集,线程即可并行;每个 worker 是独立 Crew,无共享状态)
        with ThreadPoolExecutor(max_workers=max(1, len(files))) as pool:
            results = list(pool.map(work, files))

        self.state.worker_results = results
        self.state.total_tokens = sum(r["tokens"] for r in results)
        tiers = {r["file"]: r["tier"] for r in results}
        print(f"[Dyn] fan_out: {len(results)} 个并行 worker 完成,模型路由={tiers}, 总 token≈{self.state.total_tokens}")

    @listen(fan_out)
    def verify(self) -> None:
        """客观验证:对 generated/ 跑 pytest(不调 LLM)。"""
        out = PytestRunTool()._run(path=".", extra_args="")
        self.state.verify_tail = out[-300:]
        # 提取 pytest 结果行(如 "20 passed in 0.09s" / "1 failed ...")
        summary = next(
            (ln for ln in out.splitlines() if ("passed" in ln or "failed" in ln or "error" in ln)),
            "(无 pytest 结果行)",
        )
        print(f"[Dyn] verify: {summary.strip()}")

    @listen(verify)
    def finalize(self) -> None:
        """成本核算 + 交付汇总。"""
        ok = sum(1 for r in self.state.worker_results if r["ok"])
        print(
            f"[Dyn] finalize: 交付 {ok}/{len(self.state.worker_results)} 个文件到 generated/,"
            f" 累计 token≈{self.state.total_tokens}(成本核算),测试结论见上方 verify。"
        )


def kickoff():
    """Flow 入口。"""
    return DynamicCodingFlow().kickoff()


if __name__ == "__main__":
    kickoff()
