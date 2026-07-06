"""候选规则构建 Worker — 独立于反馈执行链

触发源：
- 定时 cron 任务（推荐：每日凌晨）
- 管理员手动触发（POST /api/admin/candidate-rules/mine）
- 绝不响应 feedback_event（违者 code review 直接拒绝）

设计约束：
- 从投诉案例扫描新模式，不与 feedback_records 交互
- 输出到 candidate_rules 表（review_status=pending），需人工审核
- 从不直接写入生产规则库
- 从不影响当前执行链（rule_engine / llm_engine / fusion / policy_kernel）
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CandidateBuilderWorker:
    """候选规则构建 Worker

    职责边界：
    ✅ 从 ComplaintCase 扫描新模式
    ✅ 写入 candidate_rules 表（pending 状态）
    ✅ 更新已存在候选规则的置信度
    ❌ 响应 feedback_event
    ❌ 直接写入生产规则
    ❌ 修改 Rule 表
    ❌ 影响执行链

    用法:
        worker = CandidateBuilderWorker()
        result = worker.run(db, case_ids=[1,2,3])
        # 或全量扫描
        result = worker.run(db)
    """

    # 触发来源枚举 — 用于审计
    VALID_TRIGGERS = {"cron", "manual_admin", "scheduler"}

    def __init__(self):
        self._last_run_at: Optional[datetime] = None
        self._last_trigger: Optional[str] = None

    @property
    def last_run_at(self) -> Optional[datetime]:
        return self._last_run_at

    @property
    def last_trigger(self) -> Optional[str]:
        return self._last_trigger

    def run(
        self,
        db: Session,
        *,
        case_ids: Optional[list[int]] = None,
        trigger: str = "manual_admin",
        auto_write: bool = True,
    ) -> dict:
        """执行一次候选规则构建。

        Args:
            db: 数据库会话
            case_ids: 指定案例 ID（None = 全量未分析）
            trigger: 触发来源（cron / manual_admin / scheduler）
            auto_write: 是否写入候选规则

        Returns:
            {
                "trigger": str,
                "scanned": int,
                "candidates_created": int,
                "candidates_updated": int,
                "run_at": str,
            }
        """
        if trigger not in self.VALID_TRIGGERS:
            raise ValueError(
                f"无效触发来源: {trigger}。"
                f"允许: {', '.join(sorted(self.VALID_TRIGGERS))}"
            )

        logger.info(
            f"CandidateBuilderWorker 启动: trigger={trigger}, "
            f"cases={len(case_ids) if case_ids else 'all'}"
        )

        from app.services.rule_miner import mine_to_candidates

        result = mine_to_candidates(db, case_ids=case_ids, auto_write=auto_write)

        self._last_run_at = datetime.now(timezone.utc)
        self._last_trigger = trigger

        logger.info(
            f"CandidateBuilderWorker 完成: "
            f"scanned={result['scanned']}, "
            f"created={result.get('candidates_created', 0)}, "
            f"updated={result.get('candidates_updated', 0)}"
        )

        return {
            "trigger": trigger,
            "scanned": result["scanned"],
            "candidates_created": result.get("candidates_created", 0),
            "candidates_updated": result.get("candidates_updated", 0),
            "run_at": self._last_run_at.isoformat(),
            "miner_version": result.get("miner_version", "unknown"),
        }

    # ponytail: no run_continuous — scheduler layer handles cron, this is just the unit


# ── 全局单例 ─────────────────────────────────────────

candidate_builder_worker = CandidateBuilderWorker()
