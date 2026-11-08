---
name: document-handoff
description: Engineering Flow 内部规则，用于文档建议、engineer-voice 显式改写与续接。
user-invocable: false
---

文档建议仅支持 Markdown，不自动覆盖。flow_document propose 参数 task_id/proposal，proposal 结构：target、mode(manual/generated/mixed)、region(mixed 的命名区域，其他为 null)、draft、reason、sources、protectedFacts。来源必须引用该任务实际快照代码或已保存检查/评审，不能用模型文字替代。完整 schema 与 CLI 相同，非法输入被 Core 拒绝。

需要工程表达改写时：

1. flow_document voice(document_id) 显式加载已校验规则。仅在 status="loaded" 时读取完整规则，按规则改写 draft。若返回 presentation 摘要，通过 flow_read 的 /draft、/protectedFacts 和 rules 中各 readPath 取得原文，逐页读取到 nextOffset=null；不要通过反复读取宿主临时文件猜测被截断内容。未成功则保留原稿并报告。不要声称加载本身证明执行。
2. 保留代码、命令、路径、数值、单位、条件、否定、建议强度、主体/对象及不确定性。使用原来的 proposalIntegrity/moduleDigest 和完整 rewritten 调用 rewrite；不要自报检查通过、已确认或语义等价。
3. 查看 voice.status/issues 和 after。rejected 时 after 退回原稿，如实报告拒绝。protected_checks_passed 只代表程序保护比较通过；仍为 proposed，技术语义须评审。
4. export 或 handoff 提供 before/after/patch 供核对。实际应用由宿主在用户范围内编辑；编辑后旧建议、检查与页面重新判断适用性。不要将正文相等当成已应用/已确认。

交接前用当前修订 checkpoint，记录真实进度、未决事项和下一步；handoff 使用同一 Review 快照，不宣告任务完成。输出 task_id、revision、材料路径及继续方法。只提出有实际来源的候选记忆，冲突保留双方，不自动升级为团队规则。
