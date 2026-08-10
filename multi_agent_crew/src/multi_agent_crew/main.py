#!/usr/bin/env python
import os
import sys
import warnings

from multi_agent_crew.crew import MultiAgentCrew

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# 默认编码需求(可被命令行参数或 CREW_REQUIREMENT 环境变量覆盖)。
DEFAULT_REQUIREMENT = (
    "实现一个 Python 装饰器 retry:支持指定最大重试次数、指数退避间隔、"
    "以及只对指定异常类型重试(其余异常直接抛出);附带 pytest 单元测试。"
)


def resolve_requirement() -> str:
    """解析编码需求:命令行参数 > CREW_REQUIREMENT 环境变量 > 默认值。"""
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    return os.environ.get("CREW_REQUIREMENT", "").strip() or DEFAULT_REQUIREMENT


def run():
    """
    Run the crew.
    """
    inputs = {
        'requirement': resolve_requirement(),
    }

    try:
        MultiAgentCrew().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "requirement": DEFAULT_REQUIREMENT,
    }
    try:
        MultiAgentCrew().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        MultiAgentCrew().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "requirement": DEFAULT_REQUIREMENT,
    }

    try:
        MultiAgentCrew().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "requirement": DEFAULT_REQUIREMENT,
    }

    try:
        result = MultiAgentCrew().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
