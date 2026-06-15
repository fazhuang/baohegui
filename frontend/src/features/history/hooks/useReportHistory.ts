/** History feature — 报告列表状态 hook */

import { useState, useEffect, useMemo } from 'react';
import { listReports } from '../../../services/api';
import type { ReportListItem } from '../../../types';
import { getErrorMessage } from '../../../utils/error';

type SortValue = `${string}:${'asc' | 'desc'}`;

export const DEFAULT_PAGE_SIZE = 20;

export const SORT_OPTIONS: Array<{ value: SortValue; label: string }> = [
  { value: 'created_at:desc', label: '最新优先' },
  { value: 'created_at:asc', label: '最早优先' },
  { value: 'total_score:desc', label: '评分从高到低' },
  { value: 'total_score:asc', label: '评分从低到高' },
  { value: 'violation_count:desc', label: '违规数从多到少' },
  { value: 'violation_count:asc', label: '违规数从少到多' },
  { value: 'file_name:asc', label: '文件名 A-Z' },
  { value: 'file_name:desc', label: '文件名 Z-A' },
];

export function useReportHistory() {
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');
  const [searchText, setSearchText] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [scoreMin, setScoreMin] = useState(0);
  const [scoreMax, setScoreMax] = useState(100);
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  const loadReports = async (overrides?: {
    search?: string; date_from?: string; date_to?: string;
    score_min?: number; score_max?: number; sort_by?: string;
    sort_order?: string; page?: number; page_size?: number;
  }) => {
    const params = {
      search: overrides?.search ?? searchText,
      date_from: overrides?.date_from ?? dateFrom,
      date_to: overrides?.date_to ?? dateTo,
      score_min: overrides?.score_min ?? scoreMin,
      score_max: overrides?.score_max ?? scoreMax,
      sort_by: overrides?.sort_by ?? sortBy,
      sort_order: overrides?.sort_order ?? sortOrder,
      page: overrides?.page ?? page,
      page_size: overrides?.page_size ?? pageSize,
    };
    setLoading(true);
    try {
      const data = await listReports(params);
      setReports(data.items); setTotal(data.total);
      setPage(data.page); setPageSize(data.page_size);
      setErrorMsg('');
    } catch (err: unknown) { setErrorMsg(getErrorMessage(err, '加载失败')); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadReports(); }, []);

  const resetFilters = () => {
    setSearchText(''); setDateFrom(''); setDateTo('');
    setScoreMin(0); setScoreMax(100); setSortBy('created_at'); setSortOrder('desc');
    loadReports({ search: '', date_from: '', date_to: '', score_min: 0, score_max: 100,
      sort_by: 'created_at', sort_order: 'desc', page: 1, page_size: DEFAULT_PAGE_SIZE });
  };

  const applySort = (value: SortValue) => {
    const [nextSortBy, nextSortOrder] = value.split(':') as [string, 'asc' | 'desc'];
    setSortBy(nextSortBy); setSortOrder(nextSortOrder);
    loadReports({ sort_by: nextSortBy, sort_order: nextSortOrder, page: 1 });
  };

  const applyScoreRange = (value: number[] | null) => {
    const nextMin = value?.[0] ?? 0; const nextMax = value?.[1] ?? 100;
    setScoreMin(nextMin); setScoreMax(nextMax);
    loadReports({ score_min: nextMin, score_max: nextMax, page: 1 });
  };

  const applyDateFrom = (value: string) => { setDateFrom(value); loadReports({ date_from: value, page: 1 }); };
  const applyDateTo = (value: string) => { setDateTo(value); loadReports({ date_to: value, page: 1 }); };
  const handleSearch = (value: string) => { setSearchText(value); loadReports({ search: value, page: 1 }); };

  const trendReports = useMemo(() => reports.slice().reverse().slice(-10), [reports]);

  const hasFilters = searchText || dateFrom || dateTo || scoreMin !== 0 || scoreMax !== 100 || sortBy !== 'created_at' || sortOrder !== 'desc';

  return {
    reports, total, page, pageSize, loading, errorMsg,
    searchText, dateFrom, dateTo, scoreMin, scoreMax, sortBy, sortOrder,
    trendReports, hasFilters,
    setSearchText, setDateFrom, setDateTo, setScoreMin, setScoreMax,
    loadReports, resetFilters, applySort, applyScoreRange, applyDateFrom, applyDateTo, handleSearch,
  };
}
