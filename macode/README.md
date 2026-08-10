# macode — 多智能体 coding agent

基于 [crewAI](https://crewai.com) 的**多智能体写代码**系统:**架构师 → 工程师 → 测试执行 → 评审** 四 Agent 协作,把一个编码需求变成**经过真实运行验证**的可运行代码。

与一般「只会写」的 coding agent 不同,本项目的 Agent 具备**探索 / 编辑 / 执行 / 验证**全套能力(读文件、写文件、目录浏览、代码搜索、运行 Python、跑 pytest、执行 shell、语法检查),测试工程师会**真正运行**代码与测试,评审基于真实测试结果把关。

给定一个编码需求(默认:实现一个 `retry` 装饰器 + 测试),流水线产出:
- `generated/` 目录下的 **Python 源码与测试**(工程师用 FileWriterTool 写入,测试运行验证通过)
- `solution.md`:评审后的最终代码 + 测试结论 + 评审说明
- `solution_summary.md`(Flow deliver 分支):方案摘要 + 指标 + 结构

## 安装与使用(npm CLI,推荐)

以 npm 包形式安装部署(类似 grok build / claude code 的使用方式):

```bash
npm install -g .          # 从本仓库全局安装(或 npm install -g <tarball>)

# 首次运行自动准备 Python 环境(仅需一次),随后:
macode "实现一个带过期时间的 LRU 缓存,附 pytest 测试"   # 默认 crew 模式
macode flow "..."        # 事件驱动 Flow
macode dynamic "..."     # 动态工作流(并行子代理+模型路由+成本核算)
macode --help
```

**代码写进你运行命令的当前目录**(`generated/` + `solution.md`),而不是包目录。运行前需设置:
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`(指向你的 Anthropic 兼容端点)。

> 亦可 `npm pack` 打出 `multi-agent-coder-*.tgz` 后 `npm install -g <tgz>` 离线安装。

## 能力一览

| 能力 | 工具 | 挂载 Agent |
|---|---|---|
| 读文件 / 写文件 | `FileReadTool` / `FileWriterTool`(crewai-tools) | architect / coder |
| 目录树浏览 | `ListDirTool` | architect |
| 代码搜索(grep) | `CodeSearchTool` | architect / coder / reviewer |
| 运行 Python 文件 | `PythonRunTool` | tester |
| 跑 pytest | `PytestRunTool` | tester / reviewer |
| 执行 shell 命令 | `ShellCommandTool`(限工作区+拦截危险命令) | tester |
| 语法静态检查 | `PythonSyntaxCheckTool`(ast) | reviewer |

> 后 6 个为自定义工具(`src/macode/tools/`),执行类工具工作目录限定在 `generated/`,带超时与输出截断。

## 功能一览

| 功能 | 实现 | 状态 |
|---|---|---|
| 多 Agent 协作 | `Process.sequential`(可切 `hierarchical`),4 Agent | ✅ |
| crewai-tools 工具 | `FileReadTool` / `FileWriterTool` | ✅ |
| 自定义执行工具 | shell/python/pytest 运行验证 | ✅ |
| 自定义搜索工具 | grep 代码搜索 + 目录树 | ✅ |
| 结构化输出 | 架构师方案:纯 JSON + guardrail 按 `ImplementationPlan` 校验 | ✅ |
| Task guardrail | `guardrails.py`(JSON 校验 + 代码产物校验) | ✅ |
| RAG 知识检索 | `knowledge/coding_standards.md` + 本地 ONNX embedder | ✅ |
| Hierarchical | `CREW_PROCESS=hierarchical` + `manager_llm` | ✅ |
| HITL | `CREW_HITL=1` 评审任务人工确认 | ✅(默认关) |
| crewai Flow | `flow.py` 多路路由+并行+汇聚+有界循环 | ✅ |
| **动态工作流**(Pi-Dynamic-Workflows 风格) | `dynamic_flow.py`:动态规划子任务+并行子代理+模型路由+成本核算+`@persist`持久化 | ✅ |
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
run_crew                  # 或: python -c "from macode.main import run; run()"

# 方式二:跑 Flow(事件驱动编排,内嵌 Crew)
python -m macode.flow

# 仅测试 Flow 编排(跳过昂贵的 Crew,复用现有 solution.md):
FLOW_SKIP_CREW=1 python -m macode.flow

# 方式三:动态工作流(动态规划子任务 -> 并行子代理 -> 模型路由 -> 成本核算 -> 验证)
python -m macode.dynamic_flow

# 仅测试动态编排(跳过 LLM 规划,用内置小计划):
DYN_SKIP_PLAN=1 python -m macode.dynamic_flow
```

产物:`generated/` 下的代码文件 + `solution.md`(评审后最终代码);Flow 的 deliver 分支还会产出 `solution_summary.md`。

### 动态工作流(dynamic_flow.py)

Pi-Dynamic-Workflows 风格的动态编排,区别于 flow.py 的「固定 Crew + 事件分支」:

```
prepare → plan(架构师动态规划出 N 个文件子任务)
        → fan_out(N 个并行子代理,每个写一个文件;按文件类型路由 strong/fast 档模型;聚合 token)
        → verify(对 generated/ 跑 pytest)
        → finalize(成本核算汇总 + 交付)
```

- **并行子代理**:`ThreadPoolExecutor` 并发执行多个独立 Crew(LLM 调用是 I/O 密集)。
- **模型路由**:`test_*`/`conftest.py` 走 fast 档,核心逻辑走 strong 档(多提供方时可指向不同真实模型)。
- **成本核算**:聚合各 worker 的 `usage_metrics` 报告 token 总量。
- **持久化/可恢复**:`@persist` 把 Flow 状态落 SQLite(`~/Library/Application Support/macode/flow_states.db`),崩溃后可按 `id` 恢复续跑。

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

- **改编码需求**:改 `src/macode/main.py` 里的 `DEFAULT_REQUIREMENT`。
- **改 Agent 角色**:`config/agents.yaml`;**改任务**:`config/tasks.yaml`。
- **改编码规范/偏好**(RAG/工具读取):`knowledge/coding_standards.md`、`knowledge/coding_preference.txt`。

## 本仓库的环境适配说明

所用代理模型**强制开启 extended thinking 且关不掉**,带来两处适配:

1. **结构化输出**:crewai 的 `output_pydantic`(经 `tool_choice` / `json_schema`)与该模型不兼容,故改为「提示词要纯 JSON + guardrail 按 schema 校验」实现等价效果。
2. **Memory**:crewai memory 的智能分析/抽取同样依赖结构化输出,会降级为整段存储并刷警告,故默认关闭;`CREW_MEMORY=1` 可开(接受降级)。**RAG 知识检索不受影响,完全可用。**

## 项目结构

```
src/macode/
├── config/agents.yaml     # 4 个 coding Agent(架构师/工程师/测试执行/评审)
├── config/tasks.yaml      # 4 个 Task(规划/编码/验证/评审)
├── crew.py                # 装配 LLM/工具/RAG/流程 + 开关
├── flow.py                # crewai Flow 编排(多分支/并行/汇聚/有界循环)
├── dynamic_flow.py        # 动态工作流(动态规划+并行子代理+模型路由+成本核算+持久化)
├── output_models.py       # ImplementationPlan 结构化输出模型
├── guardrails.py          # Task 护栏(JSON schema / 代码产物校验)
├── tools/
│   ├── custom_tool.py       # PythonSyntaxCheckTool(ast 语法检查)
│   ├── execution_tools.py   # ShellCommandTool / PythonRunTool / PytestRunTool
│   └── search_tools.py      # CodeSearchTool(grep) / ListDirTool(目录树)
└── main.py                # Crew 入口(DEFAULT_REQUIREMENT)
knowledge/                 # 编码规范/偏好(供 RAG/工具)
generated/                 # 工程师写出的代码(运行产物,测试验证通过)
```

## CI

`.github/workflows/ci.yml`:push 到 main 时做离线冒烟检查(导入 + 配置 + 构建 + guardrail/语法工具,不发真实 LLM 请求)。
