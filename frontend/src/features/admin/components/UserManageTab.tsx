/**
 * UserManageTab — 用户管理 Tab 组件
 *
 * 从 AdminPanel.tsx 拆分，独立为 features/admin/components。
 */

import React from 'react';
import {
  Table, Tag, Button, Space, Typography,
  Modal, Form, Select, Switch, message,
  Popconfirm, Input,
} from 'antd';
import {
  UserOutlined, PlusOutlined, DeleteOutlined, EditOutlined,
} from '@ant-design/icons';
import { deleteUser } from '../../../services/api';
import type { UserInfo } from '../../../types/admin-types';
import { useUserManage } from '../hooks';

const { Title } = Typography;

const UserManageTab: React.FC = () => {
  const {
    users, loading, modalOpen, editingUser, roleFilter, statusFilter, filteredUsers,
    setModalOpen, setEditingUser, setRoleFilter, setStatusFilter,
    load, handleCreate, handleUpdate,
  } = useUserManage();
  const [form] = Form.useForm();

  const openCreate = () => {
    setEditingUser(null);
    form.resetFields();
    form.setFieldsValue({ role: 'user', is_active: true });
    setModalOpen(true);
  };

  const openEdit = (u: UserInfo) => {
    setEditingUser(u);
    form.setFieldsValue({
      role: u.role, company: u.company, email: u.email,
      is_active: u.is_active, password: undefined,
    });
    setModalOpen(true);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Title level={4}><UserOutlined /> 用户管理 ({filteredUsers.length}/{users.length})</Title>
        <Space size={8}>
          <Select allowClear placeholder="角色筛选" style={{ width: 110 }} size="small"
            value={roleFilter} onChange={(v) => setRoleFilter(v || null)}
            options={[{ value: 'admin', label: '管理员' }, { value: 'user', label: '普通用户' }]} />
          <Select allowClear placeholder="状态筛选" style={{ width: 110 }} size="small"
            value={statusFilter} onChange={(v) => setStatusFilter(v || null)}
            options={[{ value: 'active', label: '启用' }, { value: 'disabled', label: '停用' }]} />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
        </Space>
      </div>
      <Table dataSource={filteredUsers} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 20 }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 60 },
          { title: '用户名', dataIndex: 'username' },
          { title: '角色', dataIndex: 'role', width: 80,
            render: (v: string) => <Tag color={v === 'admin' ? 'red' : 'blue'}>{v}</Tag> },
          { title: '单位', dataIndex: 'company', ellipsis: true },
          { title: '邮箱', dataIndex: 'email', ellipsis: true },
          { title: '状态', dataIndex: 'is_active', width: 70,
            render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag> },
          { title: '创建时间', dataIndex: 'created_at', width: 180,
            render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
          { title: '操作', width: 120,
            render: (_: unknown, r: UserInfo) => (
              <Space size={4}>
                <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
                <Popconfirm title="确定删除此用户？" onConfirm={async () => {
                  await deleteUser(r.id); message.success('已删除'); load();
                }}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ) },
        ]} />
      <Modal title={editingUser ? `编辑用户: ${editingUser.username}` : '新建用户'} open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditingUser(null); }}
        onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={editingUser ? handleUpdate : handleCreate}>
          {!editingUser && (
            <>
              <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input placeholder="登录用户名" />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}>
                <Input.Password placeholder="登录密码" />
              </Form.Item>
            </>
          )}
          {editingUser && (
            <Form.Item name="password" label="新密码（留空不修改）">
              <Input.Password placeholder="留空则不修改密码" />
            </Form.Item>
          )}
          <Form.Item name="role" label="角色">
            <Select options={[{ value: 'user', label: '普通用户' }, { value: 'admin', label: '管理员' }]} />
          </Form.Item>
          <Form.Item name="company" label="单位"><Input placeholder="所属单位" /></Form.Item>
          <Form.Item name="email" label="邮箱"><Input placeholder="电子邮箱" /></Form.Item>
          {editingUser && (
            <Form.Item name="is_active" label="启用状态" valuePropName="checked"><Switch /></Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
};

export default UserManageTab;
