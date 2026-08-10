# multi_agent_crew

基于 [crewAI](https://crewai.com) 的多智能体中文内容生产示例:**研究员 → 写手 → 审校** 三 Agent 协作,产出一份调研报告 `report.md`。

## 功能一览

| 功能 | 实现 | 状态 |
|---|---|---|
| 多 Agent 协作 | `Process.sequential`(可切 `hierarchical`) | ✅ |
| crewai-tools 工具 | 研究员挂 `FileReadTool` / `ScrapeWebsiteTool` | ✅(联网抓取见下方说明) |
| 自定义工具 | `tools/custom_tool.py: TextStatsTool`(审校量化查篇幅) | ✅ |
| 结构化输出 | 提示词要纯 JSON + guardrail 按 Pydantic schema 校验 | ✅ |
| Task guardrail | `guardrails.py`(JSON 校验 + 报告结构/篇幅校验) | ✅ |
| RAG 知识检索 | `knowledge_sources` + 本地 ONNX embedder | ✅ |
| Hierarchical | `CREW_PROCESS=hierarchical` + `manager_llm` | ✅ |
| HITL | `CREW_HITL=1` 审校任务人工确认 | ✅(默认关) |
| crewai Flow | `flow.py` 事件驱动编排,内嵌 Crew | ✅ |
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
pip install -e .          # 安装(依赖 crewai[tools]>=1.15.14)

# 方式一:直接跑 Crew
run_crew                  # 或: python -c "from multi_agent_crew.main import run; run()"

# 方式二:跑 Flow(事件驱动编排,内嵌 Crew)
python -m multi_agent_crew.flow
```

产物 `report.md` 写入项目根目录。

## 环境变量开关

| 变量 | 默认 | 说明 |
|---|---|---|
| `CREW_PROCESS` | `sequential` | 设 `hierarchical` 切换为层级流程(自动加 manager) |
| `CREW_HITL` | `0` | 设 `1` 让审校任务在产出前等待人工确认 |
| `CREW_MEMORY` | `0` | 设 `1` 开启记忆(本代理下智能分析层降级,见下) |
| `CREW_KNOWLEDGE` | `1` | 设 `0` 关闭 RAG 知识检索 |

## 本仓库的环境适配说明

所用代理模型**强制开启 extended thinking 且关不掉**,带来两处适配:

1. **结构化输出**:crewai 的 `output_pydantic`(经 `tool_choice` / `json_schema`)与该模型不兼容,故改为「提示词要纯 JSON + guardrail 按 schema 校验」实现等价效果。
2. **Memory**:crewai memory 的智能分析/抽取同样依赖结构化输出,会降级为整段存储并刷警告,故默认关闭;`CREW_MEMORY=1` 可开(接受降级)。**RAG 知识检索不受影响,完全可用。**

> `ScrapeWebsiteTool` 在某些沙箱环境会因 SSRF 防护(域名被解析为内网 IP)误报拦截;正常网络环境可用。

## 项目结构

```
src/multi_agent_crew/
├── config/agents.yaml     # 3 个 Agent 定义
├── config/tasks.yaml      # 3 个 Task 定义
├── crew.py                # 装配 LLM/工具/RAG/流程 + 开关
├── flow.py                # crewai Flow 编排
├── output_models.py       # 结构化输出的 Pydantic 模型
├── guardrails.py          # Task 护栏(JSON schema / 报告校验)
├── tools/custom_tool.py   # 自定义工具 TextStatsTool
└── main.py                # Crew 入口
knowledge/                 # 知识文件(用户偏好 + 领域笔记,供 RAG/工具)
```

## CI

`.github/workflows/ci.yml`:push 到 main 时做离线冒烟检查(导入 + 配置 + 构建,不发真实 LLM 请求)。
