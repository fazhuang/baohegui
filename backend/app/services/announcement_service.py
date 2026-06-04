"""警示公告服务 — 初始化 + CRUD"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.announcement import Announcement

logger = logging.getLogger(__name__)

# 内置默认公告（真实案例）
_DEFAULT_ANNOUNCEMENTS = [
    {
        "title": "甘肃省政府采购网：关于某建设工程咨询有限公司提供虚假材料谋取中标的行政处罚通报",
        "severity": "danger",
        "category": "违规处罚",
        "case_date": "2026-06-02",
        "summary": "经省财政厅大数据比对核查，涉事供应商在参与省直机关综合办公楼维修改造项目投标中，伪造一级建造师执业资格证书及相关社保缴纳证明，情节严重。",
        "source": "甘肃省政府采购网",
    },
    {
        "title": "中国政府采购网：某信息技术服务商涉嫌串通投标行为的立案查处公示",
        "severity": "critical",
        "category": "违规处罚",
        "case_date": "2026-05-28",
        "summary": "在智慧政务云平台二期建设项目评标过程中，专家评审组发现三家投标单位的电子投标文件由同一台电脑终端（MAC地址一致）加密上传，存在串通投标行为。",
        "source": "中国政府采购网",
    },
    {
        "title": "甘肃省公共资源交易局：关于某建筑工程局有限公司违规转包项目的不良行为记录",
        "severity": "warning",
        "category": "违规处罚",
        "case_date": "2026-05-25",
        "summary": "涉事建筑企业在中标省道提升改造标段后，擅自将主体结构工程肢解转包给无资质的劳务施工队，引发质量安全隐患。",
        "source": "甘肃省公共资源交易网",
    },
    {
        "title": "财政部：关于进一步规范政府采购评审工作的通知",
        "severity": "info",
        "category": "政策法规",
        "case_date": "2026-05-15",
        "summary": "财政部发布通知强调：不得以不合理条件对供应商实行差别待遇或歧视待遇；不得将注册资本、资产总额、营业收入等规模条件作为资格要求或评审因素。评审委员会成员应客观、公正、审慎地履行职责。",
        "source": "中国政府采购网",
    },
    {
        "title": "甘肃省财政厅：某招标代理机构因招标文件存在排他性条款被通报批评",
        "severity": "danger",
        "category": "违规处罚",
        "case_date": "2026-04-20",
        "summary": "涉事代理机构在编制医疗器械采购招标文件时，设置了'进口品牌优先''需提供厂家独家授权'等排他性条款，被供应商投诉后经查属实，被责令整改并通报批评。",
        "source": "甘肃省财政厅",
    },
]


def seed_announcements(db: Session) -> int:
    """首次启动时将默认公告写入数据库（跳过已存在的）"""
    existing = db.query(Announcement).count()
    if existing > 0:
        return 0

    count = 0
    for item in _DEFAULT_ANNOUNCEMENTS:
        ann = Announcement(**item, is_published=1)
        db.add(ann)
        count += 1

    db.commit()
    logger.info("已播种 %d 条默认公告", count)
    return count
