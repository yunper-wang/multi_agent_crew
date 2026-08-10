# 编码交付摘要

## LLM 摘要
本交付物实现了一个支持最大重试次数、指数退避（`base_delay * backoff**attempt`）和按异常类型白名单选择性重试的 `retry` 装饰器工厂，所有参数（含 `retry_exceptions` 合法性）均在定义阶段校验、失败尽早暴露，并用 `functools.wraps` 保留元信息、模块级 `time.sleep` 便于测试 monkeypatch。评审修正了三类问题：补充 `retry_exceptions` 必须是异常类元组的定义期校验、在循环末尾加 `raise AssertionError("unreachable")` 兜底以杜绝隐式返回 `None`、补齐 sleep 调用次数断言（验证 `base_delay=0` 时仍按规则调用 `sleep(0)`）及针对非法白名单的参数化测试。最终 `retry.py` 与 `test_retry.py` 均通过语法检查，14 个测试用例全部通过且无真实等待。

## 指标
- 字符数: 8877
- 代码块数: 6
- 标题数: 8

## 结构
# retry 装饰器 — 代码评审与最终版本
## 一、语法检查结论
## 二、评审发现的问题与修正
## 三、最终代码
# 占位文件:借助 pytest「conftest.py 所在目录自动加入 sys.path」的机制,使 tests/ 中的用例可直接 import retry,无需 sys.path hack。
