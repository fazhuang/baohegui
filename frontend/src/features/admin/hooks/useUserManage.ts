/** Admin feature — 用户管理 Tab 状态 hook */

import { useState, useCallback, useEffect, useMemo } from 'react';
import { message } from 'antd';
import { listUsers, createUser, updateUser } from '../../../services/api';
import type { CreateUserRequest, UpdateUserRequest } from '../../../types';
import type { UserInfo } from '../../../types/admin-types';
import { getErrorMessage } from '../../../utils/error';

export function useUserManage() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null);
  const [roleFilter, setRoleFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setUsers(await listUsers()); } catch { message.error('加载用户列表失败'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filteredUsers = useMemo(() => {
    let list = users;
    if (roleFilter) list = list.filter(u => u.role === roleFilter);
    if (statusFilter) list = list.filter(u => statusFilter === 'active' ? u.is_active : !u.is_active);
    return list;
  }, [users, roleFilter, statusFilter]);

  const handleCreate = async (values: CreateUserRequest) => {
    try {
      await createUser(values);
      message.success('用户已创建');
      setModalOpen(false);
      load();
    } catch (e: unknown) { message.error(getErrorMessage(e, '创建失败')); }
  };

  const handleUpdate = async (values: UpdateUserRequest & { password?: string }) => {
    if (!editingUser) return;
    const payload: UpdateUserRequest = { password: values.password };
    if (values.role) payload.role = values.role;
    if (values.company !== undefined) payload.company = values.company;
    if (values.email !== undefined) payload.email = values.email;
    if (values.is_active !== undefined) payload.is_active = values.is_active;
    try {
      await updateUser(editingUser.id, payload);
      message.success('用户已更新');
      setModalOpen(false); setEditingUser(null);
      load();
    } catch (e: unknown) { message.error(getErrorMessage(e, '更新失败')); }
  };

  return {
    users, loading, modalOpen, editingUser, roleFilter, statusFilter, filteredUsers,
    setModalOpen, setEditingUser, setRoleFilter, setStatusFilter,
    load, handleCreate, handleUpdate,
  };
}
