/** Upload feature — 上传队列状态管理 hook */

import { useState, useCallback, useRef, useEffect } from 'react';
import type { FileItemData, PipelineResult } from '../types';
import { uploadFile, runCheck } from '../../../services/api';
import { getErrorMessage } from '../../../utils/error';
import type { StepName } from '../types';

interface UseUploadQueueOptions {
  onAllDone?: (lastResult: { report_id: number; score: number; pipeline?: PipelineResult }) => void;
}

export function useUploadQueue(opts: UseUploadQueueOptions = {}) {
  const [currentStep, setCurrentStep] = useState<StepName>('idle');
  const [error, setError] = useState<{ step: StepName; message: string } | null>(null);
  const [result, setResult] = useState<{ report_id: number; score: number; pipeline?: PipelineResult } | null>(null);
  const [progress, setProgress] = useState(10);
  const [files, setFiles] = useState<FileItemData[]>([]);
  const nextFileId = useRef(0);
  const filesRef = useRef<FileItemData[]>([]);
  const processingRef = useRef(false);
  const fileRef = useRef<File | null>(null);
  const uploadResultRef = useRef<{ db_id: number } | null>(null);

  // 模拟进度
  const animateProgress = useCallback(() => {
    setProgress(10);
    const timer = setInterval(() => {
      setProgress((p) => {
        if (p >= 95) { clearInterval(timer); return 95; }
        return p + Math.random() * 8;
      });
    }, 800);
    return () => clearInterval(timer);
  }, []);

  const updateFiles = useCallback((updater: (prev: FileItemData[]) => FileItemData[]) => {
    setFiles(prev => { const next = updater(prev); filesRef.current = next; return next; });
  }, []);

  const isRunning = currentStep !== 'idle' && currentStep !== 'done' && !error;
  const isBatchMode = files.length > 1;
  const doneCount = files.filter(f => f.status === 'done').length;

  const processSingleFile = useCallback(async (item: FileItemData): Promise<void> => {
    fileRef.current = item.file;
    uploadResultRef.current = null;
    setError(null);
    setResult(null);
    try {
      setCurrentStep('uploading');
      setProgress(0);
      const uploadResult = await uploadFile(item.file);
      setProgress(100);
      uploadResultRef.current = { db_id: uploadResult.db_id };
      updateFiles(prev => prev.map(f =>
        f.id === item.id ? { ...f, status: 'checking' as const, dbId: uploadResult.db_id } : f
      ));
      await new Promise(r => setTimeout(r, 200));

      setCurrentStep('routing'); animateProgress(); setProgress(50);
      setCurrentStep('rule_engine'); animateProgress(); setProgress(60);
      setCurrentStep('parameter_bias'); animateProgress(); setProgress(70);
      setCurrentStep('llm_analysis'); animateProgress(); setProgress(80);
      setCurrentStep('risk_merge'); animateProgress(); setProgress(90);

      const checkResult = await runCheck(uploadResult.db_id);
      setProgress(100);
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
      };
      const fileResult = { report_id: checkResult.report_id, score: checkResult.total_score, pipeline };
      updateFiles(prev => prev.map(f =>
        f.id === item.id ? { ...f, status: 'done' as const, result: fileResult } : f
      ));
    } catch (err: unknown) {
      const msg = getErrorMessage(err, '处理失败');
      updateFiles(prev => prev.map(f =>
        f.id === item.id ? { ...f, status: 'error' as const, errorMsg: msg } : f
      ));
      setError({ step: currentStep, message: msg });
      setProgress(0);
    }
  }, [animateProgress, updateFiles, currentStep]);

  const processQueue = useCallback(async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    try {
      while (true) {
        const pendingIdx = filesRef.current.findIndex(f => f.status === 'pending');
        if (pendingIdx === -1) break;
        const item = filesRef.current[pendingIdx];
        updateFiles(prev => prev.map(f =>
          f.id === item.id ? { ...f, status: 'uploading' as const } : f
        ));
        await processSingleFile(item);
      }
    } finally { processingRef.current = false; }

    const doneFiles = filesRef.current.filter(f => f.status === 'done');
    if (doneFiles.length > 0) {
      setCurrentStep('done');
      setResult(doneFiles[doneFiles.length - 1].result!);
      opts.onAllDone?.(doneFiles[doneFiles.length - 1].result!);
    } else if (filesRef.current.length > 0) {
      setCurrentStep('idle');
    }
  }, [processSingleFile, updateFiles, opts]);

  const addFiles = useCallback((newFiles: File[]) => {
    if (isRunning) return;
    setError(null);
    const items: FileItemData[] = newFiles.map(f => ({
      id: nextFileId.current++, file: f, status: 'pending' as const,
    }));
    updateFiles(prev => [...prev, ...items]);
  }, [isRunning, updateFiles]);

  useEffect(() => {
    if (!files.some(f => f.status === 'pending')) return;
    if (processingRef.current) return;
    processQueue();
  }, [files, processQueue]);

  const handleRetryFile = useCallback((fileId: number) => {
    updateFiles(prev => prev.map(f =>
      f.id === fileId ? { ...f, status: 'pending' as const, errorMsg: undefined, result: undefined } : f
    ));
  }, [updateFiles]);

  const handleRetryAll = useCallback(() => {
    setError(null); setResult(null);
    updateFiles(prev => prev.map(f => ({
      ...f, status: 'pending' as const, errorMsg: undefined, result: undefined, dbId: undefined,
    })));
  }, [updateFiles]);

  const resetAll = useCallback(() => {
    setCurrentStep('idle'); setError(null); setResult(null); setProgress(10);
    fileRef.current = null; uploadResultRef.current = null;
    processingRef.current = false; setFiles([]); filesRef.current = [];
  }, []);

  return {
    currentStep, error, result, progress, files, isRunning, isBatchMode, doneCount,
    totalCount: files.length, processingRef, fileRef,
    setError, addFiles, handleRetryFile, handleRetryAll, resetAll, setProgress,
    getStepStatus: (key: StepName): 'wait' | 'active' | 'done' | 'error' => {
      const idx = (() => { const order = ['uploading', 'parsing', 'routing', 'rule_engine', 'parameter_bias', 'llm_analysis', 'risk_merge', 'done']; return order.indexOf(key); })();
      const currentIdx = ['uploading', 'parsing', 'routing', 'rule_engine', 'parameter_bias', 'llm_analysis', 'risk_merge', 'done'].indexOf(currentStep);
      if (error?.step === key) return 'error';
      if (currentStep === key && !error) return 'active';
      if (currentIdx > idx || (currentStep === 'done' && idx < 7)) return 'done';
      return 'wait';
    },
  };
}
