import os
from pathlib import Path

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource
from crewai_tools import FileReadTool, ScrapeWebsiteTool

from .output_models import ResearchFindings
from .guardrails import json_output_guardrail, report_guardrail
from .tools.custom_tool import TextStatsTool

# 本地 ONNX embedding(无需任何 API key;模型首次运行已缓存到本地)。
# 本地代理不提供 embeddings 接口,故 memory/RAG 改用本地模型。
EMBEDDER = {"provider": "onnx"}

# 项目根目录(multi_agent_crew/)的绝对路径,从包位置推算,与运行时 cwd 无关。
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 领域知识文件(RAG 用)的绝对路径。
# 传入 Path 对象(而非 str)时 crewai 不会额外拼 knowledge/ 前缀。
KNOWLEDGE_FILE = PROJECT_ROOT / "knowledge" / "ai_engineering_notes.md"


def _build_llm(max_tokens: int = 16384) -> LLM:
    """构造走本地 Anthropic 兼容代理的 LLM。

    环境变量(由运行环境注入):
      ANTHROPIC_BASE_URL   代理地址
      ANTHROPIC_AUTH_TOKEN 代理托管的鉴权(占位即可)
    max_tokens 给大:该模型默认带 extended thinking,会占掉一部分输出额度;
    审校/写长文的 Agent 额度太小会被截断。
    """
    return LLM(
        model="anthropic/claude-sonnet-4-6",
        base_url=os.environ["ANTHROPIC_BASE_URL"],
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN", "PROXY_MANAGED"),
        max_tokens=max_tokens,
        temperature=0.7,
    )


def _flag(name: str, default: bool = False) -> bool:
    """读取布尔开关环境变量。"""
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@CrewBase
class MultiAgentCrew():
    """MultiAgentCrew:研究员 -> 写手 -> 审校。

    环境变量开关:
      CREW_PROCESS=hierarchical  切换为层级流程(默认 sequential)
      CREW_HITL=1                审校任务开启人工确认(默认关,便于无人值守运行)
      CREW_MEMORY=1              开启记忆(默认关:本代理不兼容 memory 的结构化分析,会降级)
      CREW_KNOWLEDGE=0           关闭 RAG 知识检索(默认开;CI 或快速运行可关)
    """

    agents: list[BaseAgent]
    tasks: list[Task]

    # ---------------- agents ----------------
    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['researcher'], # type: ignore[index]
            verbose=True,
            llm=_build_llm(),
            # crewai-tools:读本地文件(base_dir 锁定项目根,cwd 无关) + 抓网页
            tools=[FileReadTool(base_dir=str(PROJECT_ROOT)), ScrapeWebsiteTool()],
        )

    @agent
    def writer(self) -> Agent:
        return Agent(
            config=self.agents_config['writer'], # type: ignore[index]
            verbose=True,
            llm=_build_llm(),
        )

    @agent
    def reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['reviewer'], # type: ignore[index]
            verbose=True,
            llm=_build_llm(),
            tools=[TextStatsTool()],  # 自定义工具:量化检查报告篇幅
        )

    # ---------------- tasks ----------------
    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'], # type: ignore[index]
            # 结构化输出:代理模型不支持 API 级 output_pydantic,
            # 改用「提示词要纯 JSON + guardrail 按 schema 校验打回重试」。
            guardrail=json_output_guardrail(ResearchFindings),
        )

    @task
    def writing_task(self) -> Task:
        return Task(
            config=self.tasks_config['writing_task'], # type: ignore[index]
        )

    @task
    def review_task(self) -> Task:
        return Task(
            config=self.tasks_config['review_task'], # type: ignore[index]
            output_file='report.md',      # crewai 按 cwd 相对写;经 flow 运行时先 chdir 到项目根
            guardrail=report_guardrail(min_chars=300),  # 护栏:结构+篇幅校验
            human_input=_flag("CREW_HITL", False),      # HITL 开关
        )

    # ---------------- crew ----------------
    @crew
    def crew(self) -> Crew:
        """Creates the MultiAgentCrew crew"""
        hierarchical = os.environ.get("CREW_PROCESS", "").strip().lower() == "hierarchical"
        # memory 默认关:crewai memory 的智能分析/抽取内部依赖结构化输出(tool_choice),
        # 与本代理模型(强制 thinking)不兼容,会降级并刷警告;RAG(知识检索)则完全可用。
        # 需要时仍可 CREW_MEMORY=1 开启(接受降级)。
        use_memory = _flag("CREW_MEMORY", False)       # CI/快速运行:CREW_MEMORY=0
        use_knowledge = _flag("CREW_KNOWLEDGE", True)  # CI/快速运行可关:CREW_KNOWLEDGE=0
        # embedder 同时服务于 memory 和 knowledge(RAG):任一开启就需要。
        embedder = EMBEDDER if (use_memory or use_knowledge) else None
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.hierarchical if hierarchical else Process.sequential,
            manager_llm=_build_llm() if hierarchical else None,  # 层级流程的 manager
            verbose=True,
            memory=use_memory,                         # 短期/长期/实体记忆
            embedder=embedder,                         # 本地 ONNX 向量
            knowledge_sources=(                        # RAG:检索领域知识
                [TextFileKnowledgeSource(file_paths=[KNOWLEDGE_FILE])]
                if use_knowledge
                else None
            ),
        )
