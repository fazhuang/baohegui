# 反馈→执行链隔离架构

```mermaid
stateDiagram-v2
    direction TB

    state "User Feedback" as FB {
        [*] --> submitted: user submits feedback
        submitted --> acknowledged: admin reviews
        acknowledged --> resolved: action taken
        acknowledged --> closed: no action needed
        resolved --> closed: finalized
    }

    state "Candidate Builder (独立 Worker)" as CB {
        [*] --> idle
        idle --> scanning: scheduled / manual trigger
        scanning --> building: cases found
        building --> idle: candidates written
        scanning --> idle: no cases

        note right of CB: 触发源：cron / admin API\n绝不响应 feedback_event
    }

    state "Policy Approval Workflow" as PA {
        [*] --> draft
        draft --> review: submit for review
        review --> approved: admin approves
        review --> rejected: admin rejects
        approved --> applied: promote to production
        applied --> rolled_back: emergency rollback
        rejected --> draft: revise

        note right of PA: 只有 applied 状态影响执行链
    }

    state "Execution Chain (隔离区)" as EC {
        direction LR
        Routing → RuleEngine → BiasDetector → LLMEngine → Fusion → PolicyKernel
    }

    FB --> CB: ❌ 禁止
    FB --> EC: ❌ 禁止
    FB --> PA: ❌ 禁止

    CB --> PA: candidate (pending)
    PA --> EC: applied policy only

    note bottom of EC: feedback 永远不参与：\n• 规则修改\n• LLM 输入\n• 输出排序
```
