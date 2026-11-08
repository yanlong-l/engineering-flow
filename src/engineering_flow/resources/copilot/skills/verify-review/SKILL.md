---
name: verify-review
description: Engineering Flow 内部规则，用于真实检查、快照失效和 Review 材料。
user-invocable: false
---

1. resume 当前 task_id，核对分支、任务修订、启动已有改动和 verification。用 doctor 读取项目检查配置，不接收调用者提交的检查结果。
2. 调用 flow_check action="run"，参数 task_id/check_id。按实际命令约定读取状态、exitCode、failure、applicability 和原始输出。长结果摘要不包含完整日志时，使用 presentation.responseId 和 /run/stdout/data、/run/stderr/data，通过 flow_read 读到 nextOffset=null，保留 encoding、truncated 和摘要限制。全部必需项的最近运行必须 passed/current 才能陈述 requiredChecksPassed；skip 只记录未执行。
3. flow_review build 保存材料。解释用 explain，提交 content={summary,behaviors:[{title,description,acceptanceCriteria:[1],references:[{file,layer,startLine,endLine}]}]}，绑定该 review_id 的历史快照。行号必须从 flow_snapshot 读取的对应文件取得，不猜测当前文件位置。解释存为 AI，不是程序证据。
4. 展示实际 review.html 的本地路径。record 只保存 caller 意见，范围 files/memory_ids/document_ids 互斥；不伪造确认。解释或意见写入后 build 新材料，旧页不会实时刷新。
5. 代码或配置/任务修订变化后，重新 resume 并判断旧检查、解释、意见/确认是否适用，按需重跑与新建 Review。历史通过或批准不能覆盖新失败。
