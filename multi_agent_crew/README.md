# multi_agent_crew — coding agent

基于 [crewAI](https://crewai.com) 的**多智能体写代码**示例:**架构师 → 工程师 → 评审** 三 Agent 协作,把一个编码需求变成可运行的代码。

给定一个编码需求(默认:实现一个 `retry` 装饰器 + 测试),流水线产出:
- `generated/` 目录下的 **Python 源码与测试**(工程师用 FileWriterTool 写入)
- `solution.md`:评审后的最终代码 + 评审说明
- `solution_summary.md`(Flow deliver 分支):方案摘要 + 指标 + 结构

## 功能一览

| 功能 | 实现 | 状态 |
|---|---|---|
| 多 Agent 协作 | `Process.sequential`(可切 `hierarchical`) | ✅ |
| crewai-tools 工具 | 架构师 `FileReadTool` / 工程师 `FileWriterTool` | ✅ |
| 自定义工具 | `tools/custom_tool.py: PythonSyntaxCheckTool`(评审静态校验语法) | ✅ |
| 结构化输出 | 架构师方案:提示词要纯 JSON + guardrail 按 `ImplementationPlan` 校验 | ✅ |
| Task guardrail | `guardrails.py`(JSON 校验 + 代码产物校验) | ✅ |
| RAG 知识检索 | `knowledge/coding_standards.md` + 本地 ONNX embedder | ✅ |
| Hierarchical | `CREW_PROCESS=hierarchical` + `manager_llm` | ✅ |
| HITL | `CREW_HITL=1` 评审任务人工确认 | ✅(默认关) |
| crewai Flow | `flow.py` 事件驱动编排,内嵌 Crew;多路路由+并行+汇聚+有界循环 | ✅ |
| Memory | `CREW_MEMORY=1` 开启 | ⚠ 降级(见下) |

## 环境要求(LLM 代理)

本项目 LLM 走本地 Anthropic 兼容代理,运行前需要两个环境变量:

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:15721"   # 代理地址
export ANTHROPIC_AUTH_TOKEN="..."                     # 鉴权(或占位)
```

模型 `anthropic/claude-sonnet-4-6`。embedding 用**本地 ONNX**(`embedder={"provider":"onnx"}`),无需任何 API key。

## 运行

```bash
pip install -e .          # 安装(依赖 crewai[tools]>=1.15.14, anthropic)

# 方式一:直接跑 Crew
run_crew                  # 或: python -c "from multi_agent_crew.main import run; run()"

# 方式二:跑 Flow(事件驱动编排,内嵌 Crew)
python -m multi_agent_crew.flow

# 仅测试 Flow 编排(跳过昂贵的 Crew,复用现有 solution.md):
FLOW_SKIP_CREW=1 python -m multi_agent_crew.flow
```

产物:`generated/` 下的代码文件 + `solution.md`(评审后最终代码);Flow 的 deliver 分支还会产出 `solution_summary.md`。

### Flow 分支拓扑

```
prepare → run_crew → assess(路由)
   ├─ deliver   → make_abstract / compute_metrics / extract_outline(并行) → package(and_ 汇聚)
   ├─ revise    → expand(LLM 扩充) → reassess(重评,有界循环,最多 MAX_REVISIONS 次)
   └─ too_short → notify_short
```

## 环境变量开关

| 变量 | 默认 | 说明 |
|---|---|---|
| `CREW_PROCESS` | `sequential` | 设 `hierarchical` 切换为层级流程(自动加 manager) |
| `CREW_HITL` | `0` | 设 `1` 让评审任务在产出前等待人工确认 |
| `CREW_MEMORY` | `0` | 设 `1` 开启记忆(本代理下智能分析层降级,见下) |
| `CREW_KNOWLEDGE` | `1` | 设 `0` 关闭 RAG 编码规范检索 |
| `FLOW_SKIP_CREW` | `0` | 设 `1` 跑 Flow 时跳过 Crew 执行(复用现有 solution.md,便于测试编排) |

## 自定义

- **改编码需求**:改 `src/multi_agent_crew/main.py` 里的 `DEFAULT_REQUIREMENT`。
- **改 Agent 角色**:`config/agents.yaml`;**改任务**:`config/tasks.yaml`。
- **改编码规范/偏好**(RAG/工具读取):`knowledge/coding_standards.md`、`knowledge/coding_preference.txt`。

## 本仓库的环境适配说明

所用代理模型**强制开启 extended thinking 且关不掉**,带来两处适配:

1. **结构化输出**:crewai 的 `output_pydantic`(经 `tool_choice` / `json_schema`)与该模型不兼容,故改为「提示词要纯 JSON + guardrail 按 schema 校验」实现等价效果。
2. **Memory**:crewai memory 的智能分析/抽取同样依赖结构化输出,会降级为整段存储并刷警告,故默认关闭;`CREW_MEMORY=1` 可开(接受降级)。**RAG 知识检索不受影响,完全可用。**

## 项目结构

```
src/multi_agent_crew/
├── config/agents.yaml     # 3 个 coding Agent(架构师/工程师/评审)
├── config/tasks.yaml      # 3 个 Task(规划/编码/评审)
├── crew.py                # 装配 LLM/工具/RAG/流程 + 开关
├── flow.py                # crewai Flow 编排(多分支/并行/汇聚/有界循环)
├── output_models.py       # ImplementationPlan 结构化输出模型
├── guardrails.py          # Task 护栏(JSON schema / 代码产物校验)
├── tools/custom_tool.py   # 自定义工具 PythonSyntaxCheckTool
└── main.py                # Crew 入口(DEFAULT_REQUIREMENT)
knowledge/                 # 编码规范/偏好(供 RAG/工具)
generated/                 # 工程师写出的代码(运行产物)
```

## CI

`.github/workflows/ci.yml`:push 到 main 时做离线冒烟检查(导入 + 配置 + 构建 + guardrail/语法工具,不发真实 LLM 请求)。
