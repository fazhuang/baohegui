"""合规报告生成服务 - HTML/PDF"""

import os
from datetime import datetime, timezone
from typing import Optional

from jinja2 import Template
from weasyprint import HTML

from app.core.config import settings
from app.engine.fusion import ComplianceReport

REPORT_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif; font-size: 12pt; margin: 40px; color: #333; }
  h1 { color: #1a365d; font-size: 20pt; border-bottom: 3px solid #2563eb; padding-bottom: 8px; }
  h2 { color: #2563eb; font-size: 15pt; margin-top: 24px; }
  .score-box { display: inline-block; padding: 12px 24px; border-radius: 8px; font-size: 28pt; font-weight: bold; margin: 16px 0; color: white; }
  .score-green { background: #16a34a; }
  .score-yellow { background: #eab308; color: #333; }
  .score-red { background: #dc2626; }
  .score-table { width: 100%; border-collapse: collapse; margin: 12px 0; }
  .score-table td, .score-table th { padding: 8px 12px; border: 1px solid #ddd; text-align: left; }
  .score-table th { background: #f1f5f9; }
  .violation { margin: 8px 0; padding: 12px; border-radius: 6px; }
  .violation-high { background: #fef2f2; border-left: 4px solid #dc2626; }
  .violation-medium { background: #fffbeb; border-left: 4px solid #eab308; }
  .violation-low { background: #f0fdf4; border-left: 4px solid #16a34a; }
  .risk-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 9pt; color: white; }
  .risk-high { background: #dc2626; }
  .risk-medium { background: #eab308; color: #333; }
  .risk-low { background: #16a34a; }
  .meta { color: #666; font-size: 10pt; margin: 8px 0; }
  .footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 9pt; color: #999; }
</style>
</head>
<body>
<h1>包合规 · 招标文件合规审查报告</h1>
<div class="meta">
  <p>文件名称：{{ report.file_name }}</p>
  <p>审查时间：{{ report.check_time }}</p>
  <p>违规总数：{{ report.total_violations }} 项（高风险 {{ report.high_risk_count }} 项，中风险 {{ report.medium_risk_count }} 项，低风险 {{ report.low_risk_count }} 项）</p>
</div>

{% set score = report.total_score %}
{% if score >= 85 %}
<div class="score-box score-green">{{ score }}</div>
{% elif score >= 60 %}
<div class="score-box score-yellow">{{ score }}</div>
{% else %}
<div class="score-box score-red">{{ score }}</div>
{% endif %}
<p style="margin-top: 8px; color: #666;">合规评分（满分100）</p>

<h2>分项评分</h2>
<table class="score-table">
  <tr><th>审查维度</th><th>得分</th></tr>
  <tr><td>章节完整性</td><td>{{ report.section_score }}</td></tr>
  <tr><td>关键字合规</td><td>{{ report.keyword_score }}</td></tr>
  <tr><td>禁用词检查</td><td>{{ report.forbidden_score }}</td></tr>
  <tr><td>语义合规（AI分析）</td><td>{{ report.semantic_score }}</td></tr>
</table>

<h2>违规详情</h2>
{% for v in report.rule_violations %}
<div class="violation violation-{{ v.risk_level }}">
  <strong>[规则引擎] {{ v.description }}</strong>
  <span class="risk-tag risk-{{ v.risk_level }}">{{ v.risk_level }}</span>
  {% if v.location %}<p>位置：{{ v.location }}</p>{% endif %}
  {% if v.suggestion %}<p>建议：{{ v.suggestion }}</p>{% endif %}
  {% if v.law_ref %}<p>法规依据：{{ v.law_ref }}</p>{% endif %}
  {% if v.platform_codes %}
  <p>对应平台规则：
  {% for pc in v.platform_codes %}
    <span style="background:#e0e7ff;padding:1px 6px;border-radius:3px;">{{ pc.get('platform','') }} ({{ pc.get('code','') }})</span>
  {% endfor %}
  </p>
  {% endif %}
</div>
{% endfor %}

{% for v in report.llm_violations %}
<div class="violation violation-{{ v.risk_level }}">
  <strong>[AI语义分析] {{ v.reason[:80] }}{% if v.reason|length > 80 %}...{% endif %}</strong>
  <span class="risk-tag risk-{{ v.risk_level }}">{{ v.risk_level }}</span>
  <p>章节：{{ v.section }}</p>
  <p>原文：{{ v.text[:120] }}{% if v.text|length > 120 %}...{% endif %}</p>
  <p>建议：{{ v.suggestion }}</p>
  {% if v.law_ref %}<p>法规依据：{{ v.law_ref }}</p>{% endif %}
</div>
{% endfor %}

<div class="footer">
  <p>本报告由「包合规」AI合规审查系统自动生成，仅供参考，不构成法律意见。</p>
  <p>系统版本：{{ settings.app_version }} | {% if report.llm_model_used %}AI模型：{{ report.llm_model_used }} | 消耗Token：{{ report.llm_tokens_used }}{% else %}仅规则引擎{% endif %}</p>
</div>
</body>
</html>"""


class ReportGenerator:
    """报告生成器"""

    def __init__(self):
        self.template = Template(REPORT_HTML_TEMPLATE)

    def generate_html(self, report: ComplianceReport) -> str:
        return self.template.render(report=report, settings=settings)

    def generate_pdf(self, report: ComplianceReport, output_dir: str = "/tmp") -> str:
        html = self.generate_html(report)
        os.makedirs(output_dir, exist_ok=True)
        filename = f"baohegui_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = os.path.join(output_dir, filename)
        HTML(string=html).write_pdf(filepath)
        return filepath


report_generator = ReportGenerator()
