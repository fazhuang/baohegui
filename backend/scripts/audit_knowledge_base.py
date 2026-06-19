#!/usr/bin/env python3
"""知识库诊断脚本 — 默认只读，输出确定、可用于 CI。

用法:
  uv run python scripts/audit_knowledge_base.py           # 控制台报告
  uv run python scripts/audit_knowledge_base.py --json    # JSON 输出

依赖环境变量:
  BHG_DATABASE_URL  — 数据库连接字符串（默认 sqlite:////tmp/bhg_audit.db）
  BHG_RULES_DIR     — 规则资产目录（默认项目根 /rules）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("audit_kb")


def _get_db_url() -> str:
    return os.environ.get("BHG_DATABASE_URL", "sqlite:////tmp/bhg_audit.db")


def _get_rules_dir() -> Path:
    configured = os.environ.get("BHG_RULES_DIR")
    if configured:
        return Path(configured)
    container_rules = Path("/app/rules")
    if container_rules.exists():
        return container_rules
    return _BACKEND.parent / "rules"


def _get_session():
    """创建只读诊断用数据库会话。

    对 SQLite：如果文件路径不存在，提前报错而非自动创建空数据库。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = _get_db_url()
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        from sqlalchemy.pool import NullPool

        kwargs["poolclass"] = NullPool

        # 提取 SQLite 文件路径并检查是否存在
        path = url.replace("sqlite:///", "", 1)
        if not os.path.isabs(path) and not path.startswith("/"):
            # 相对路径：sqlite:///relative.db → 拼接 CWD
            path = os.path.join(os.getcwd(), path) if "///" not in url else path
        if "///" in url:
            # sqlite:////absolute/path
            path = url.replace("sqlite:///", "", 1)
        if path and not os.path.exists(path):
            raise FileNotFoundError(
                f"数据库文件不存在: {path}\n"
                f"请检查 BHG_DATABASE_URL 环境变量或确认数据库已初始化。"
            )

    engine = create_engine(url, **kwargs)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def _count_complaint_cases(db) -> dict:
    """complaint_cases 总数和状态分布。"""
    from app.models.complaint_case import ComplaintCase
    from sqlalchemy import func

    total = db.query(ComplaintCase).count()
    by_province = {}
    by_decision_type = {}
    by_analyzed = {}

    for row in db.query(
        ComplaintCase.province, func.count().label("cnt")
    ).group_by(ComplaintCase.province).all():
        by_province[row[0]] = row[1]

    for row in db.query(
        ComplaintCase.decision_type, func.count().label("cnt")
    ).group_by(ComplaintCase.decision_type).all():
        by_decision_type[row[0]] = row[1]

    for row in db.query(
        ComplaintCase.is_analyzed, func.count().label("cnt")
    ).group_by(ComplaintCase.is_analyzed).all():
        label = {0: "unanalyzed", 1: "analyzed", 2: "rule_extracted"}.get(row[0], f"unknown({row[0]})")
        by_analyzed[label] = row[1]

    return {
        "total": total,
        "by_province": by_province,
        "by_decision_type": by_decision_type,
        "by_analyzed": by_analyzed,
    }


def _count_kg_nodes(db) -> dict:
    """KG 节点总数、类型分布、审核状态分布。"""
    from app.models.knowledge_graph import KGNode
    from sqlalchemy import func

    total = db.query(KGNode).count()
    by_type = {}
    for row in db.query(
        KGNode.node_type, func.count().label("cnt")
    ).group_by(KGNode.node_type).all():
        by_type[row[0]] = row[1]

    by_status = {}
    for row in db.query(
        KGNode.audit_status, func.count().label("cnt")
    ).group_by(KGNode.audit_status).all():
        by_status[row[0]] = row[1]

    cc_projections = db.query(KGNode).filter(KGNode.rule_id.like("CC-%")).count()

    return {
        "total": total,
        "by_type": by_type,
        "by_audit_status": by_status,
        "cc_projection_count": cc_projections,
    }


def _count_kg_edges(db) -> dict:
    """KG 边数量及 relation 分布。"""
    from app.models.knowledge_graph import KGEdge
    from sqlalchemy import func

    total = db.query(KGEdge).count()
    by_relation = {}
    for row in db.query(
        KGEdge.relation, func.count().label("cnt")
    ).group_by(KGEdge.relation).all():
        by_relation[row[0]] = row[1]

    return {
        "total": total,
        "by_relation": by_relation,
    }


def _find_orphan_complaint_cases(db) -> list[dict]:
    """complaint_cases 中没有 KG 投影的孤儿记录。"""
    from app.models.complaint_case import ComplaintCase
    from app.models.knowledge_graph import KGNode
    from sqlalchemy import not_

    case_ids = {row[0] for row in db.query(ComplaintCase.id).all()}
    kg_cc_rule_ids = set()
    for row in db.query(KGNode.rule_id).filter(
        KGNode.rule_id.like("CC-%"), KGNode.node_type == "case"
    ).all():
        prefix_stripped = row[0].replace("CC-", "")
        try:
            kg_cc_rule_ids.add(int(prefix_stripped))
        except (ValueError, TypeError):
            pass

    orphan_ids = case_ids - kg_cc_rule_ids
    orphans = []
    for cid in sorted(orphan_ids):
        case = db.query(ComplaintCase).filter(ComplaintCase.id == cid).first()
        orphans.append({"id": case.id, "title": case.title, "province": case.province})
    return orphans


def _find_orphan_kg_projections(db) -> list[dict]:
    """KG 节点中 CC-* 投影找不到 ComplaintCase 的孤儿节点。"""
    from app.models.complaint_case import ComplaintCase
    from app.models.knowledge_graph import KGNode

    case_ids = set()
    for row in db.query(ComplaintCase.id).all():
        case_ids.add(row[0])

    orphans = []
    for node in db.query(KGNode).filter(
        KGNode.rule_id.like("CC-%"), KGNode.node_type == "case"
    ).all():
        prefix_stripped = node.rule_id.replace("CC-", "")
        try:
            cid = int(prefix_stripped)
        except (ValueError, TypeError):
            orphans.append({"kg_node_id": node.id, "rule_id": node.rule_id, "title": node.title})
            continue
        if cid not in case_ids:
            orphans.append({"kg_node_id": node.id, "rule_id": node.rule_id, "title": node.title, "missing_case_id": cid})
    return orphans


def _find_duplicate_source_urls(db) -> list[dict]:
    """complaint_cases 中重复的 source_url。"""
    from app.models.complaint_case import ComplaintCase
    from sqlalchemy import func

    dups = []
    rows = db.query(
        ComplaintCase.source_url, func.count().label("cnt")
    ).filter(
        ComplaintCase.source_url.isnot(None),
        ComplaintCase.source_url != "",
    ).group_by(ComplaintCase.source_url).having(func.count() > 1).all()
    for row in rows:
        dups.append({"source_url": row[0], "count": row[1]})
    return dups


def _find_duplicate_edges(db) -> list[dict]:
    """KG 重复边（同 source_id + target_id + relation）。"""
    from app.models.knowledge_graph import KGEdge
    from sqlalchemy import func

    dups = []
    rows = db.query(
        KGEdge.source_id, KGEdge.target_id, KGEdge.relation,
        func.count().label("cnt")
    ).group_by(
        KGEdge.source_id, KGEdge.target_id, KGEdge.relation
    ).having(func.count() > 1).all()
    for row in rows:
        dups.append({
            "source_id": row[0],
            "target_id": row[1],
            "relation": row[2],
            "count": row[3],
        })
    return dups


def _count_json_rule_assets(rules_dir: Path) -> dict:
    """统计 JSON 规则资产文件。"""
    if not rules_dir.exists():
        return {"error": f"rules_dir not found: {rules_dir}", "total_files": 0}

    total_files = 0
    by_category = {}

    for fname in sorted(os.listdir(rules_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = rules_dir / fname
        if not fpath.is_file():
            continue
        total_files += 1
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            by_category[fname] = {"error": "parse_failed"}
            continue

        if isinstance(data, dict):
            if "rules" in data:
                by_category[fname] = {"rule_count": len(data["rules"])}
            elif "mappings" in data:
                by_category[fname] = {"mapping_count": len(data["mappings"])}
            elif "patterns" in data:
                # forbidden_words.json
                pattern_count = sum(
                    len(v.get("regex_list", [])) if isinstance(v, dict) else 0
                    for v in data["patterns"].values()
                )
                by_category[fname] = {"pattern_count": pattern_count}
            elif "violation_patterns" in data:
                by_category[fname] = {"violation_pattern_count": len(data["violation_patterns"])}
            else:
                by_category[fname] = {"keys": list(data.keys())[:10]}
        elif isinstance(data, list):
            by_category[fname] = {"item_count": len(data)}

    # Subdirectories
    for subdir_name in sorted(os.listdir(rules_dir)):
        subdir = rules_dir / subdir_name
        if not subdir.is_dir():
            continue
        sub_files = 0
        for fname in sorted(os.listdir(subdir)):
            if fname.endswith(".json"):
                sub_files += 1
                total_files += 1
        by_category[f"{subdir_name}/" if sub_files else subdir_name] = {
            "json_file_count": sub_files,
        }

    return {"total_files": total_files, "by_category": by_category}


def _count_rule_engine_loaded(db) -> dict:
    """RuleEngine 实际加载的规则数量和类型分布。

    self.rules 是 list[RuleDefinition]（Pydantic 模型），每个元素用 .type 属性。
    """
    try:
        from app.engine.rule_engine import RuleEngine

        engine = RuleEngine()
        total = len(engine.rules) if hasattr(engine, "rules") else 0
        by_type: dict[str, int] = {}
        if hasattr(engine, "rules") and engine.rules:
            for rule in engine.rules:
                rt = getattr(rule, "type", "unknown")
                by_type[rt] = by_type.get(rt, 0) + 1
        return {"loaded_rules": total, "by_type": by_type}
    except Exception as e:
        return {"error": str(e), "loaded_rules": 0}


def audit(args) -> dict:
    """主审计函数，返回检查结果字典。"""
    result = {}
    errors = []

    # 1. 数据库连接和基础查询
    result["connection"] = {"database_url": _get_db_url(), "rules_dir": str(_get_rules_dir())}
    try:
        db = _get_session()
    except FileNotFoundError as e:
        result["connection_error"] = str(e)
        result["hint"] = "数据库文件不存在；请先执行 alembic upgrade head 或指向已有数据库。"
        return result
    except Exception as e:
        result["connection_error"] = str(e)
        return result

    try:
        # 2. complaint_cases
        result["complaint_cases"] = _count_complaint_cases(db)

        # 3. KG nodes
        result["kg_nodes"] = _count_kg_nodes(db)

        # 4. KG edges
        result["kg_edges"] = _count_kg_edges(db)

        # 5. CC-* 投影
        # (included in kg_nodes.by_type for "case" type)

        # 6. 孤儿记录
        result["orphan_complaint_cases_no_kg"] = _find_orphan_complaint_cases(db)
        result["orphan_kg_projections_no_case"] = _find_orphan_kg_projections(db)

        # 7. 重复 source_url
        result["duplicate_source_urls"] = _find_duplicate_source_urls(db) or []

        # 8. 重复边
        result["duplicate_edges"] = _find_duplicate_edges(db) or []

    finally:
        db.close()

    # 9. JSON 规则资产
    rules_dir = _get_rules_dir()
    result["json_assets"] = _count_json_rule_assets(rules_dir)

    # 10. RuleEngine 加载量
    result["rule_engine"] = _count_rule_engine_loaded(None)

    return result


def print_report(data: dict, args):
    """打印控制台报告。"""
    print("=" * 72)
    print("  包合规知识库诊断报告")
    print("=" * 72)
    print()

    # 1. complaint_cases
    cc = data.get("complaint_cases", {})
    print(f"📋 complaint_cases: 总数={cc.get('total', 'N/A')}")
    print(f"   按省份: {cc.get('by_province', {})}")
    print(f"   按决定类型: {cc.get('by_decision_type', {})}")
    print(f"   按分析状态: {cc.get('by_analyzed', {})}")
    print()

    # 2. KG nodes
    kg = data.get("kg_nodes", {})
    print(f"🔵 KG 节点: 总数={kg.get('total', 'N/A')}")
    print(f"   按类型: {kg.get('by_type', {})}")
    print(f"   按审核状态: {kg.get('by_audit_status', {})}")
    print(f"   CC-* 采集案例投影: {kg.get('cc_projection_count', 0)}")
    print()

    # 3. KG edges
    edges = data.get("kg_edges", {})
    print(f"🔗 KG 边: 总数={edges.get('total', 'N/A')}")
    print(f"   按关系: {edges.get('by_relation', {})}")
    print()

    # 4. Orphans
    orphans_cc = data.get("orphan_complaint_cases_no_kg", [])
    orphans_kg = data.get("orphan_kg_projections_no_case", [])
    print(f"🔍 孤儿记录: complaint_cases 无 KG 投影: {len(orphans_cc)}")
    for o in orphans_cc[:10]:
        print(f"   - ID={o['id']} {o['title'][:60]} [{o['province']}]")
    if len(orphans_cc) > 10:
        print(f"   ... 共 {len(orphans_cc)} 条，仅显示前 10 条")
    print(f"🔍 孤儿 KG 投影 (CC-* 无 ComplaintCase): {len(orphans_kg)}")
    for o in orphans_kg[:10]:
        print(f"   - KGNode.id={o['kg_node_id']} rule_id={o['rule_id']} {o.get('title', '')[:60]}")
    if len(orphans_kg) > 10:
        print(f"   ... 共 {len(orphans_kg)} 条，仅显示前 10 条")
    print()

    # 5. Duplicates
    dup_urls = data.get("duplicate_source_urls", [])
    dup_edges = data.get("duplicate_edges", [])
    print(f"⚠️  重复 source_url: {len(dup_urls)}")
    for d in dup_urls[:5]:
        print(f"   - {d['source_url'][:80]} (×{d['count']})")
    if len(dup_urls) > 5:
        print(f"   ... 共 {len(dup_urls)} 组")
    print(f"⚠️  重复 KG 边: {len(dup_edges)}")
    for e in dup_edges[:5]:
        print(f"   - src={e['source_id']} tgt={e['target_id']} rel={e['relation']} (×{e['count']})")
    if len(dup_edges) > 5:
        print(f"   ... 共 {len(dup_edges)} 组")
    print()

    # 6. JSON assets
    ja = data.get("json_assets", {})
    print(f"📁 JSON 规则资产文件: 总计 {ja.get('total_files', 'N/A')}")
    for name, info in sorted(ja.get("by_category", {}).items()):
        if "error" in info:
            print(f"   - {name}: ERROR {info['error']}")
        elif "rule_count" in info:
            print(f"   - {name}: {info['rule_count']} 规则")
        elif "mapping_count" in info:
            print(f"   - {name}: {info['mapping_count']} 映射")
        elif "pattern_count" in info:
            print(f"   - {name}: {info['pattern_count']} 模式")
        elif "violation_pattern_count" in info:
            print(f"   - {name}: {info['violation_pattern_count']} 违规模式")
        elif "item_count" in info:
            print(f"   - {name}: {info['item_count']} 条目")
        elif "json_file_count" in info:
            print(f"   - {name}: {info['json_file_count']} json 文件")
        else:
            print(f"   - {name}: {info}")
    print()

    # 7. RuleEngine
    re_data = data.get("rule_engine", {})
    print(f"⚙️  RuleEngine 实际加载: {re_data.get('loaded_rules', 'N/A')} 条")
    print(f"   按类型: {re_data.get('by_type', {})}")
    print()

    print("=" * 72)
    print("  诊断完成 — 以上数据为只读查询，未修改任何数据。")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="包合规知识库诊断脚本")
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 格式（适合 CI）",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="数据库连接字符串（覆盖 BHG_DATABASE_URL）",
    )
    args = parser.parse_args()

    if args.db_url:
        os.environ["BHG_DATABASE_URL"] = args.db_url

    result = audit(args)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(result, args)

    # CI 约定：出现任何诊断级错误时返回非零退出码
    errors = 0
    if result.get("connection_error"):
        errors += 1
    re_info = result.get("rule_engine", {})
    if re_info.get("error"):
        errors += 1
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
