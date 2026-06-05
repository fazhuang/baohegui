import React, { useState, useCallback, useRef, useEffect } from 'react'
import {
  Card, Typography, Button, Progress, Alert, Space, Tag,
  Result, Collapse, Tour,
} from 'antd'
import {
  InboxOutlined, UploadOutlined, FileSearchOutlined,
  CheckCircleOutlined, ReloadOutlined,
  ExperimentOutlined, SafetyOutlined, CloseCircleOutlined, HistoryOutlined,
  ProfileOutlined, ArrowRightOutlined,
  ThunderboltOutlined, FlagOutlined, MergeCellsOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { uploadFile, runCheck, getDashboardStats, listReports, getErrorMessage } from '../services/api'
import type { ReportListItem } from '../types'

const { Title, Text } = Typography

// ── 步骤定义 ────────────────────────────────────────────────

type StepName = 'idle' | 'uploading' | 'parsing' | 'routing' | 'rule_engine' | 'parameter_bias' | 'llm_analysis' | 'risk_merge' | 'done'

interface StepConfig {
  key: StepName
  label: string
  icon: React.ReactNode
  subtitle: string  // brief description
}

const STEPS: StepConfig[] = [
  { key: 'uploading', label: '文件上传', icon: <UploadOutlined />, subtitle: '上传并存储文件' },
  { key: 'parsing', label: '文档解析', icon: <FileSearchOutlined />, subtitle: '章节结构化抽取' },
  { key: 'routing', label: '智能路由', icon: <ThunderboltOutlined />, subtitle: '零Token风险分级' },
  { key: 'rule_engine', label: '规则引擎', icon: <SafetyOutlined />, subtitle: '确定性规则检查' },
  { key: 'parameter_bias', label: '参数倾向性', icon: <FlagOutlined />, subtitle: '9种违规模式检测' },
  { key: 'llm_analysis', label: 'AI语义审查', icon: <ExperimentOutlined />, subtitle: '17维隐含风险分析' },
  { key: 'risk_merge', label: '风险合并', icon: <MergeCellsOutlined />, subtitle: '四路结果汇总' },
]

const STEP_ORDER: StepName[] = ['uploading', 'parsing', 'routing', 'rule_engine', 'parameter_bias', 'llm_analysis', 'risk_merge', 'done']

interface PipelineResult {
  traffic_light: string  // green/yellow/red
  routing_reasoning: string
  parameter_bias_score: number
  parameter_bias_findings: number
  merge_risk_level: string
  merge_review_status: string
  merge_requires_human_review: boolean
  merge_confirmed_count: number
  merge_high_risk_count: number
}
const stepIndex = (s: StepName) => STEP_ORDER.indexOf(s)

// ── 过程轨道节点 ────────────────────────────────────────────

const ProcessNode: React.FC<{
  step: StepConfig
  status: 'wait' | 'active' | 'done' | 'error'
  errorMsg?: string
  onRetry?: () => void
  progressPct?: number
}> = ({ step, status, errorMsg, onRetry, progressPct = 0 }) => {
  const circleClass = [
    'process-node-circle',
    status === 'active' ? 'active' : '',
    status === 'done' ? 'done' : '',
    status === 'error' ? 'error' : '',
  ].filter(Boolean).join(' ')

  const labelClass = [
    'process-node-label',
    status === 'active' ? 'active' : '',
    status === 'done' ? 'done' : '',
    status === 'error' ? 'error' : '',
  ].join(' ')

  return (
    <div className="process-node" style={{ minWidth: 80 }}>
      <div className={circleClass}>
        {status === 'done' ? <CheckCircleOutlined /> : status === 'error' ? <CloseCircleOutlined /> : step.icon}
      </div>
      <div className={labelClass} style={{ fontWeight: status === 'active' ? 600 : 400, fontSize: 13 }}>
        {step.label}
      </div>
      {status === 'active' && (
        <Progress
          percent={Math.min(progressPct, 95)}
          size="small"
          strokeColor="var(--color-action)"
          trailColor="var(--color-brand-light)"
          style={{ width: 100, marginTop: 4 }}
          showInfo={false}
        />
      )}
      {status === 'active' && (
        <Text type="secondary" style={{ fontSize: 11 }}>{step.subtitle}</Text>
      )}
      {status === 'error' && errorMsg && (
        <div style={{ marginTop: 4, textAlign: 'center' }}>
          <Text type="danger" style={{ fontSize: 11 }}>{errorMsg}</Text>
          {onRetry && (
            <div style={{ marginTop: 4 }}>
              <Button size="small" type="link" danger icon={<ReloadOutlined />} onClick={onRetry}>
                重试
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── 行业 Chip 选项（去掉 emoji）────────────────────────────

interface IndustryOption {
  value: string
  label: string
  desc: string
}

const INDUSTRY_OPTIONS: IndustryOption[] = [
  { value: 'construction', label: '工程建设', desc: '建筑工程、市政工程等施工类招标' },
  { value: 'it', label: '信息技术', desc: '软件开发、系统集成、信息化项目' },
  { value: 'healthcare', label: '医疗采购', desc: '医疗器械、药品、医疗服务' },
]

// ── 最近检查概览 ────────────────────────────────────────────

const RecentCheckStrip: React.FC<{ onClick?: (id: number) => void }> = ({ onClick }) => {
  const [items, setItems] = useState<ReportListItem[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    listReports()
      .then((reports) => setItems(reports.slice(0, 5)))
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [])

  if (!loaded || items.length === 0) return null

  const scoreColor = (score: number) =>
    score >= 85 ? 'var(--color-success)' : score >= 60 ? 'var(--color-warning)' : 'var(--color-error)'

  return (
    <div style={{ marginBottom: 16 }}>
      <div className="section-header">
        <HistoryIcon />
        <Text style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>最近检查</Text>
      </div>
      <div className="recent-check-strip">
        {items.map((item) => (
          <div
            key={item.id}
            className="recent-check-item"
            onClick={() => onClick?.(item.id)}
          >
            <Text
              style={{ fontSize: 12, color: 'var(--color-text)', display: 'block' }}
              ellipsis
            >
              {item.file_id || `报告 #${item.id}`}
            </Text>
            <div
              className="recent-check-score"
              style={{
                width: `${Math.max(item.total_score || 0, 5)}%`,
                backgroundColor: scoreColor(item.total_score || 0),
              }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

// Need History icon — use a simple inline one
const HistoryIcon: React.FC = () => (
  <HistoryOutlined style={{ fontSize: 14, color: "var(--color-text-tertiary)" }} />
)

// ── 上传页主组件 ──────────────────────────────────────────

const UploadPage: React.FC = () => {
  const navigate = useNavigate()

  const [currentStep, setCurrentStep] = useState<StepName>('idle')
  const [error, setError] = useState<{ step: StepName; message: string } | null>(null)
  const [result, setResult] = useState<{ report_id: number; score: number; pipeline?: PipelineResult } | null>(null)
  const [progress, setProgress] = useState(10)

  // 行业选择
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([])
  const [availableIndustries, setAvailableIndustries] = useState<string[]>([])
  const [showIndustrySelect, setShowIndustrySelect] = useState(false)

  // 拖拽状态
  const [dragOver, setDragOver] = useState(false)

  // 保存上传结果以便重试
  const fileRef = useRef<File | null>(null)
  const uploadResultRef = useRef<{ db_id: number } | null>(null)

  // 加载可用行业列表
  useEffect(() => {
    getDashboardStats().then(stats => {
      setAvailableIndustries(stats.industries || [])
    }).catch(() => {
      setAvailableIndustries(['construction', 'it', 'healthcare'])
    })
  }, [])

  // 模拟进度动画
  const animateProgress = useCallback(() => {
    setProgress(10)
    const timer = setInterval(() => {
      setProgress((p) => {
        if (p >= 95) {
          clearInterval(timer)
          return 95
        }
        return p + Math.random() * 8
      })
    }, 800)
    return () => clearInterval(timer)
  }, [])

  // 主流程
  const startUpload = useCallback(async (file: File, industries?: string[]) => {
    fileRef.current = file
    setError(null)
    setResult(null)

    const indStr = (industries && industries.length > 0) ? industries.join(',') : undefined

    try {
      setCurrentStep('uploading')
      animateProgress()
      const uploadResult = await uploadFile(file, indStr)
      setProgress(100)
      uploadResultRef.current = { db_id: uploadResult.db_id }

      await new Promise(r => setTimeout(r, 300))
      setCurrentStep('parsing')
      animateProgress()

      await new Promise(r => setTimeout(r, 200))
      setCurrentStep('routing')
      animateProgress()

      await new Promise(r => setTimeout(r, 200))
      setCurrentStep('rule_engine')
      animateProgress()

      await new Promise(r => setTimeout(r, 200))
      setCurrentStep('parameter_bias')
      animateProgress()

      await new Promise(r => setTimeout(r, 200))
      setCurrentStep('llm_analysis')
      animateProgress()

      await new Promise(r => setTimeout(r, 200))
      setCurrentStep('risk_merge')
      animateProgress()

      const checkResult = await runCheck(uploadResult.db_id, indStr)
      setProgress(100)

      // Extract pipeline data from the check result
      const pipeline: PipelineResult = {
        traffic_light: checkResult.traffic_light || 'green',
        routing_reasoning: checkResult.routing_reasoning || '',
        parameter_bias_score: checkResult.parameter_bias_score ?? 0,
        parameter_bias_findings: checkResult.parameter_bias_findings ?? 0,
        merge_risk_level: checkResult.merge_risk_level || 'low',
        merge_review_status: checkResult.merge_review_status || 'auto_passed',
        merge_requires_human_review: checkResult.merge_requires_human_review ?? false,
        merge_confirmed_count: checkResult.merge_confirmed_count ?? 0,
        merge_high_risk_count: checkResult.merge_high_risk_count ?? 0,
      }

      setCurrentStep('done')
      setResult({ report_id: checkResult.report_id, score: checkResult.total_score, pipeline })
    } catch (err: any) {
      const msg = getErrorMessage(err)
      setError({ step: currentStep, message: msg })
      setProgress(0)
    }
  }, [currentStep, animateProgress])

  // 重试
  const handleRetry = useCallback(async () => {
    if (!fileRef.current) return
    setError(null)
    setResult(null)
    const f = fileRef.current
    fileRef.current = null
    uploadResultRef.current = null
    startUpload(f, selectedIndustries)
  }, [startUpload, selectedIndustries])

  // 行业 Chip 切换
  const toggleIndustry = useCallback((value: string) => {
    setSelectedIndustries(prev =>
      prev.includes(value) ? prev.filter(v => v !== value) : [...prev, value]
    )
  }, [])

  // Tour
  const [tourOpen, setTourOpen] = useState(false)
  const tourSteps = [
    { title: '包合规操作指南', description: '帮助您在提交前发现合规问题。只需三步。', target: () => document.getElementById('tour-upload-area') as HTMLElement, placement: 'bottom' as const },
    { title: '上传文件', description: '拖拽招标文件到上传区域。支持 PDF 和 Word。', target: () => document.getElementById('tour-upload-area') as HTMLElement, placement: 'bottom' as const },
    { title: '查看操作指南', description: '点击此处查看详细的操作说明。', target: () => document.querySelector('.ant-collapse-header') as HTMLElement, placement: 'right' as const },
    { title: '等待检查', description: '自动完成上传→解析→五层审查流水线（智能路由、规则引擎、参数倾向性、AI语义、风险合并），约1-3分钟。', target: () => document.getElementById('process-track') as HTMLElement, placement: 'top' as const },
  ]

  const currentIdx = stepIndex(currentStep)
  const isRunning = currentStep !== 'idle' && currentStep !== 'done' && !error

  // 拖拽事件处理
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!isRunning) setDragOver(true)
  }
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)

    if (isRunning) return

    const file = e.dataTransfer.files?.[0]
    if (!file) return

    const ext = file.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'docx'].includes(ext || '')) {
      setError({ step: 'idle', message: '仅支持 PDF 和 Word (.docx) 格式' })
      return
    }
    if (file.size > 50 * 1024 * 1024) {
      setError({ step: 'idle', message: '文件大小不能超过 50MB' })
      return
    }
    startUpload(file, selectedIndustries)
  }

  // 点击选择文件
  const fileInputRef = useRef<HTMLInputElement>(null)
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || isRunning) return
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'docx'].includes(ext || '')) {
      setError({ step: 'idle', message: '仅支持 PDF 和 Word (.docx) 格式' })
      return
    }
    if (file.size > 50 * 1024 * 1024) {
      setError({ step: 'idle', message: '文件大小不能超过 50MB' })
      return
    }
    startUpload(file, selectedIndustries)
  }

  const getStepStatus = (key: StepName): 'wait' | 'active' | 'done' | 'error' => {
    const idx = stepIndex(key)
    if (error?.step === key) return 'error'
    if (currentStep === key && !error) return 'active'
    if (currentIdx > idx || (currentStep === 'done' && idx < STEP_ORDER.length - 1)) return 'done'
    return 'wait'
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Title level={3} style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>
        上传招标文件
      </Title>
      <Text type="secondary" style={{ marginBottom: 20, display: 'block', fontSize: 14 }}>
        支持 PDF 和 Word 格式，单文件不超过 50MB
      </Text>

      {/* ── 最近检查概览 ────────────────────────── */}
      {currentStep === 'idle' && (
        <RecentCheckStrip onClick={(id) => navigate(`/report/${id}`)} />
      )}

      {/* ── 行业选择 Chip ──────────────────────── */}
      {currentStep === 'idle' && (
        <Card
          size="small"
          style={{
            marginBottom: 16,
            borderRadius: 10,
            border: '1px solid var(--color-border)',
          }}
          styles={{ body: { padding: '12px 16px' } }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
            <Space>
              <ProfileOutlined style={{ color: 'var(--color-action)', fontSize: 16 }} />
              <Text strong style={{ fontSize: 14 }}>行业类型</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {selectedIndustries.length === 0 ? '（不选则仅使用通用规则）' : `已选 ${selectedIndustries.length} 项`}
              </Text>
            </Space>
            <Button
              type="link"
              size="small"
              onClick={() => setShowIndustrySelect(!showIndustrySelect)}
            >
              {showIndustrySelect ? '收起' : '选择行业'}
            </Button>
          </div>
          {showIndustrySelect && (
            <div style={{ marginTop: 12 }}>
              <Space wrap size={[8, 8]}>
                {INDUSTRY_OPTIONS.filter(o => availableIndustries.length === 0 || availableIndustries.includes(o.value)).map(opt => (
                  <Tag.CheckableTag
                    key={opt.value}
                    checked={selectedIndustries.includes(opt.value)}
                    onChange={() => toggleIndustry(opt.value)}
                    style={{
                      padding: '4px 14px',
                      borderRadius: 6,
                      fontSize: 13,
                      border: `1px solid ${selectedIndustries.includes(opt.value) ? 'var(--color-action)' : 'var(--color-border)'}`,
                    }}
                  >
                    {opt.label}
                  </Tag.CheckableTag>
                ))}
              </Space>
              <Alert
                message="选择行业后，系统将加载该行业的专属审查规则，提高审查精准度"
                type="info"
                showIcon={false}
                style={{ marginTop: 10, background: 'var(--color-brand-light)', border: 'none', fontSize: 12, padding: '6px 12px', borderRadius: 6 }}
              />
            </div>
          )}
        </Card>
      )}

      {/* ── 首次使用引导 ────────────────────────── */}
      {currentStep === 'idle' && (
        <Collapse
          ghost
          size="small"
          items={[{
            key: 'guide',
            label: <span style={{ color: 'var(--color-action)', fontSize: 13 }}>首次使用？查看操作指南</span>,
            children: (
              <div>
                <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', marginBottom: 8 }}>
                  {[
                    { step: 1, title: '上传文件', desc: '拖拽或选择 PDF/Word 文件，系统自动上传' },
                    { step: 2, title: '文档解析', desc: '自动提取招标文件的章节结构' },
                    { step: 3, title: '五层审查', desc: '智能路由→规则引擎→参数倾向→AI语义→风险合并' },
                    { step: 4, title: '查看报告', desc: '获得合规评分和详细整改建议' },
                  ].map(({ step, title, desc }) => (
                    <div key={step} style={{ flex: '1 0 140px', minWidth: 120 }}>
                      <div className="guide-step-icon">{step}</div>
                      <div style={{ fontWeight: 600, fontSize: 13, marginTop: 6 }}>{title}</div>
                      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 2 }}>{desc}</div>
                    </div>
                  ))}
                </div>
                <Alert
                  message="合规检查通常需要 1-3 分钟，具体时间取决于文件大小和复杂程度"
                  type="info"
                  showIcon={false}
                  style={{ background: 'var(--color-brand-light)', border: 'none', fontSize: 12, padding: '8px 12px', borderRadius: 6 }}
                />
              </div>
            ),
          }]}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* ── 快速引导按钮 ────────────────────────── */}
      {currentStep === 'idle' && (
        <div style={{ textAlign: 'right', marginBottom: 8 }}>
          <Button type="link" size="small" onClick={() => setTourOpen(true)}>
            快速入门引导
          </Button>
        </div>
      )}

      {/* ── 自定义上传区域 ──────────────────────── */}
      {currentStep === 'idle' && (
        <div
          id="tour-upload-area"
          className={`upload-zone ${dragOver ? 'drag-over' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
          <InboxOutlined className="upload-zone-icon" />
          <div className="upload-zone-title">点击或拖拽招标文件到此处</div>
          <div className="upload-zone-hint">支持 PDF、DOCX 格式，系统将自动完成上传、解析、合规检查</div>
        </div>
      )}

      {/* ── 文件已选取信息 ──────────────────────── */}
      {currentStep !== 'idle' && fileRef.current && (
        <Card
          size="small"
          style={{
            marginBottom: 20,
            borderRadius: 8,
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
          }}
        >
          <Space>
            <InboxOutlined style={{ fontSize: 18, color: 'var(--color-action)' }} />
            <Text strong>{fileRef.current.name}</Text>
            <Text type="secondary">
              ({(fileRef.current.size / 1024 / 1024).toFixed(1)} MB)
            </Text>
            {!isRunning && !error && currentStep !== 'done' && (
              <Button size="small" type="link" onClick={() => { setCurrentStep('idle'); setError(null) }}>
                重新选择
              </Button>
            )}
          </Space>
        </Card>
      )}

      {/* ── 水平过程轨道 ────────────────────────── */}
      {(isRunning || error || currentStep === 'done') && (
        <Card
          style={{ marginBottom: 20, borderRadius: 12 }}
          styles={{ body: { padding: '24px 16px' } }}
          id="process-track"
        >
          <div className="process-track">
            {STEPS.map((s, i) => (
              <React.Fragment key={s.key}>
                <ProcessNode
                  step={s}
                  status={getStepStatus(s.key)}
                  errorMsg={error?.step === s.key ? error.message : undefined}
                  onRetry={error?.step === s.key ? (s.key === 'uploading' ? handleRetry : () => startUpload(fileRef.current!)) : undefined}
                  progressPct={getStepStatus(s.key) === 'active' ? Math.min(progress, 95) : getStepStatus(s.key) === 'done' ? 100 : 0}
                />
                {i < STEPS.length - 1 && (
                  <div
                    className={`process-line ${getStepStatus(s.key) === 'done' ? 'done' : getStepStatus(s.key) === 'active' ? 'active' : ''}`}
                    style={{ flexShrink: 0 }}
                  />
                )}
              </React.Fragment>
            ))}
          </div>

          {/* 错误详情卡片 */}
          {error && error.step !== 'idle' && (
            <>
              <Alert
                message="检查未完成"
                description={
                  <div>
                    <Text strong style={{ color: 'var(--color-error)' }}>{error.message}</Text>
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        请检查文件是否符合要求后重新上传
                      </Text>
                    </div>
                  </div>
                }
                type="error"
                showIcon
                style={{ marginTop: 12, borderRadius: 8 }}
              />
              <div style={{ textAlign: 'center', marginTop: 12 }}>
                <Space size={12}>
                  <Button
                    onClick={() => {
                      setCurrentStep('idle')
                      setError(null)
                      setResult(null)
                      fileRef.current = null
                      uploadResultRef.current = null
                    }}
                    style={{ borderRadius: 8 }}
                  >
                    重新选择文件
                  </Button>
                  <Button icon={<ReloadOutlined />} onClick={handleRetry} style={{ borderRadius: 8 }}>
                    重试此文件
                  </Button>
                </Space>
              </div>
            </>
          )}
        </Card>
      )}

      {/* ── 完成状态 ────────────────────────────── */}
      {currentStep === 'done' && result && (
        <Result
          status="success"
          title="合规检查完成"
          subTitle="系统已完成对招标文件的全部合规审查"
          extra={[
            /* ── 五层流水线摘要 ──────────────────── */
            result.pipeline && (
              <Card
                key="pipeline-summary"
                size="small"
                style={{
                  marginBottom: 16,
                  borderRadius: 10,
                  border: '1px solid var(--color-border)',
                  textAlign: 'left',
                  maxWidth: 480,
                  margin: '0 auto 16px auto',
                }}
                styles={{ body: { padding: '14px 18px' } }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <ThunderboltOutlined style={{ color: 'var(--color-action)', fontSize: 14 }} />
                    <Text style={{ fontSize: 13 }}>智能路由</Text>
                    <Tag color={result.pipeline.traffic_light === 'green' ? 'green' : result.pipeline.traffic_light === 'yellow' ? 'gold' : 'red'} style={{ marginLeft: 'auto' }}>
                      {result.pipeline.traffic_light === 'green' ? '🟢 绿灯' : result.pipeline.traffic_light === 'yellow' ? '🟡 黄灯' : '🔴 红灯'}
                      {result.pipeline.traffic_light === 'green' ? ' · 跳过AI' : ' · 进入AI审查'}
                    </Tag>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <SafetyOutlined style={{ color: 'var(--color-action)', fontSize: 14 }} />
                    <Text style={{ fontSize: 13 }}>规则引擎</Text>
                    <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>命中{result.score < 85 ? '违规' : '0'}项</Text>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <FlagOutlined style={{ color: 'var(--color-action)', fontSize: 14 }} />
                    <Text style={{ fontSize: 13 }}>参数倾向性</Text>
                    <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
                      发现{result.pipeline.parameter_bias_findings}个风险 · 得分{result.pipeline.parameter_bias_score}
                    </Text>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <ExperimentOutlined style={{ color: 'var(--color-action)', fontSize: 14 }} />
                    <Text style={{ fontSize: 13 }}>AI语义</Text>
                    <Text type={result.pipeline.traffic_light === 'green' ? 'secondary' : undefined} style={{ fontSize: 12, marginLeft: 'auto' }}>
                      {result.pipeline.traffic_light === 'green' ? '已跳过 (绿色路由)' : '分析完成'}
                    </Text>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <MergeCellsOutlined style={{ color: 'var(--color-action)', fontSize: 14 }} />
                    <Text style={{ fontSize: 13 }}>风险合并</Text>
                    <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
                      {result.pipeline.merge_risk_level} · {result.pipeline.merge_review_status}
                      {result.pipeline.merge_requires_human_review ? ' · 需人工复核' : ' · 自动通过'}
                    </Text>
                  </div>
                </div>
              </Card>
            ),
            <div key="score" style={{ marginBottom: 16 }}>
              <Tag
                color={result.score >= 85 ? 'green' : result.score >= 60 ? 'gold' : 'red'}
                style={{ padding: '4px 16px', borderRadius: 20, fontSize: 16 }}
              >
                合规评分：{result.score}
              </Tag>
            </div>,
            <Button
              key="report"
              type="primary"
              size="large"
              icon={<ArrowRightOutlined />}
              onClick={() => navigate(`/report/${result.report_id}`)}
              style={{ borderRadius: 8, paddingLeft: 28, paddingRight: 28 }}
            >
              查看详细报告
            </Button>,
            <Button
              key="new"
              onClick={() => {
                setCurrentStep('idle')
                setError(null)
                setResult(null)
                fileRef.current = null
                uploadResultRef.current = null
              }}
              style={{ borderRadius: 8 }}
            >
              检查新文件
            </Button>,
          ]}
        />
      )}

      {/* 文件校验错误（idle 态） */}
      {error?.step === 'idle' && (
        <Alert
          message="文件校验失败"
          description={error.message}
          type="error"
          showIcon
          style={{ marginTop: 16, borderRadius: 8 }}
          closable
          onClose={() => setError(null)}
        />
      )}

      {/* Tour */}
      <Tour open={tourOpen} onClose={() => setTourOpen(false)} steps={tourSteps} />
    </div>
  )
}

export default UploadPage
