import os

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai_tools import FileReadTool


def _build_llm() -> LLM:
    """构造走本地 Anthropic 兼容代理的 LLM。

    环境变量(由运行环境注入):
      ANTHROPIC_BASE_URL   代理地址
      ANTHROPIC_AUTH_TOKEN 代理托管的鉴权(占位即可)
    max_tokens 给大一些:该模型默认带 extended thinking,会占掉一部分输出额度;
    审校 Agent 需重排整篇长报告,额度太小会把输出截断。
    """
    return LLM(
        model="anthropic/claude-sonnet-4-6",
        base_url=os.environ["ANTHROPIC_BASE_URL"],
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN", "PROXY_MANAGED"),
        max_tokens=16384,
        temperature=0.7,
    )


@CrewBase
class MultiAgentCrew():
    """MultiAgentCrew crew:研究员 -> 写手 -> 审校 的 sequential 流水线"""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['researcher'], # type: ignore[index]
            verbose=True,
            llm=_build_llm(),
            tools=[FileReadTool()],  # crewai-tools:读取本地知识文件
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
        )

    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'], # type: ignore[index]
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
            output_file='report.md'
        )

    @crew
    def crew(self) -> Crew:
        """Creates the MultiAgentCrew crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
