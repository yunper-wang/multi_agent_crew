"""crewAI 最小可跑示例:一个 Agent + 一个 Task + 一个 Crew。

LLM 走本地 Anthropic 兼容代理(环境变量已注入):
  ANTHROPIC_BASE_URL  → 代理地址
  ANTHROPIC_AUTH_TOKEN → 代理托管的鉴权
运行:  source .venv/bin/activate && python crewai_demo.py
"""

import os

from crewai import Agent, Crew, LLM, Task

# 显式构造 LLM:model 用 anthropic/ 前缀,base_url/api_key 从环境读。
# max_tokens 给大一点 —— 该模型默认带 extended thinking,会占掉一部分输出额度。
llm = LLM(
    model="anthropic/claude-sonnet-4-6",
    base_url=os.environ["ANTHROPIC_BASE_URL"],
    api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN", "PROXY_MANAGED"),
    max_tokens=4096,
    temperature=0.7,
)

# 1. Agent:角色 + 目标 + 背景
greeter = Agent(
    role="问候专家",
    goal="用热情且简洁的中文向用户打招呼,并说明 crewAI 已就绪",
    backstory="你是一位经验丰富的多智能体框架布道者,擅长用简短的话把事情讲清楚。",
    llm=llm,
    verbose=True,
)

# 2. Task:具体要做什么 + 期望产出
greet_task = Task(
    description="写一句不超过 30 字的中文问候语,确认 crewAI 在这个 workspace 安装成功。",
    expected_output="一句简洁的中文问候语,包含 'crewAI' 字样。",
    agent=greeter,
)

# 3. Crew:把 Agent 和 Task 编排起来
crew = Crew(agents=[greeter], tasks=[greet_task], verbose=True)

if __name__ == "__main__":
    result = crew.kickoff()
    print("\n===== Crew 最终输出 =====")
    print(result)
