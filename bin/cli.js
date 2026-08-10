#!/usr/bin/env node
/*
 * macode — 多智能体 coding agent 的命令行入口(npm 包装器)。
 *
 * 我们的 agent 是 Python(crewAI)实现;本 CLI 负责:
 *   1. 首次运行时在 ~/.multi-agent-coder/venv 建好 Python 环境(editable 安装随包的
 *      multi_agent_crew 项目,自动拉取 crewai[tools]/anthropic/pytest 依赖);
 *   2. 透传编码需求与工作区,调用对应编排模式(crew/flow/dynamic)。
 *
 * 代码始终写进**用户当前目录**(MAC_WORKSPACE=process.cwd()),而不是只读的包目录。
 */
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const PKG_ROOT = path.resolve(__dirname, "..");
const PY_PROJ = path.join(PKG_ROOT, "multi_agent_crew"); // 随包分发的 Python 项目
const WORK_HOME = path.join(os.homedir(), ".multi-agent-coder");
const VENV = path.join(WORK_HOME, "venv");
const BIN = path.join(VENV, "bin");
const PY = path.join(BIN, "python");

const HELP = `macode — 多智能体 coding agent(架构师 → 工程师 → 测试执行 → 评审)

用法:
  macode [模式] "<编码需求>"

模式:
  crew      固定 Crew 流水线(默认)
  flow      事件驱动 Flow(多路路由 + 并行 + 汇聚 + 有界循环)
  dynamic   动态工作流(动态规划 + 并行子代理 + 模型路由 + 成本核算 + 持久化)

示例:
  macode "实现一个带过期时间的 LRU 缓存,附 pytest 测试"
  macode dynamic "写一个解析 CSV 的命令行工具"

环境变量(必填,指向你的 Anthropic 兼容端点):
  ANTHROPIC_BASE_URL    例如 http://127.0.0.1:15721
  ANTHROPIC_AUTH_TOKEN  鉴权 token

产物(写到当前目录): generated/ 代码 + solution.md
`;

function run(cmd, args, opts) {
  const r = spawnSync(cmd, args, Object.assign({ stdio: "inherit" }, opts));
  if (r.error) {
    console.error(`\n[macode] 执行失败: ${cmd} -> ${r.error.message}`);
    process.exit(1);
  }
  return r.status === 0;
}

function have(cmd) {
  return !spawnSync(cmd, ["--version"], { stdio: "ignore" }).error;
}

// 首次运行:建 venv 并 editable 安装随包的 Python 项目(幂等,已装则跳过)。
function ensureEnv() {
  if (fs.existsSync(PY)) return;
  console.log("[macode] 首次运行,正在准备 Python 环境(约 1-2 分钟,仅一次)...");
  fs.mkdirSync(WORK_HOME, { recursive: true });
  if (have("uv")) {
    if (!run("uv", ["venv", VENV])) process.exit(1);
    // editable 安装:knowledge/ 等资源才能从包位置解析
    if (!run("uv", ["pip", "install", "--python", PY, "-e", PY_PROJ])) process.exit(1);
  } else {
    const py = have("python3") ? "python3" : "python";
    if (!run(py, ["-m", "venv", VENV])) process.exit(1);
    if (!run(path.join(BIN, "pip"), ["install", "-e", PY_PROJ])) process.exit(1);
  }
  console.log("[macode] 环境就绪。\n");
}

function main() {
  let args = process.argv.slice(2);
  if (args.includes("-h") || args.includes("--help") || args.includes("help")) {
    console.log(HELP);
    process.exit(0);
  }

  let mode = "crew";
  if (["crew", "flow", "dynamic"].includes(args[0])) mode = args.shift();
  const requirement = args.join(" ").trim();

  if (!process.env.ANTHROPIC_BASE_URL) {
    console.error("[macode] 缺少 ANTHROPIC_BASE_URL 环境变量(详见 macode --help)");
    process.exit(1);
  }

  ensureEnv();

  const env = Object.assign({}, process.env);
  if (requirement) env.CREW_REQUIREMENT = requirement;
  env.MAC_WORKSPACE = process.cwd(); // 代码写到用户当前目录

  let cmd, cmdArgs;
  if (mode === "crew") {
    cmd = path.join(BIN, "run_crew");
    cmdArgs = [];
  } else if (mode === "flow") {
    cmd = PY;
    cmdArgs = ["-m", "multi_agent_crew.flow"];
  } else {
    cmd = PY;
    cmdArgs = ["-m", "multi_agent_crew.dynamic_flow"];
  }

  const r = spawnSync(cmd, cmdArgs, { stdio: "inherit", env, cwd: process.cwd() });
  process.exit(r.status === null ? 1 : r.status);
}

main();
