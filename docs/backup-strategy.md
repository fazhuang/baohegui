# 数据备份策略

## 备份内容

| 数据 | 存储位置 | 备份方式 |
|------|---------|---------|
| PostgreSQL 数据库 | `pgdata` 卷 | pg_dump + crontab |
| MinIO 对象存储 | `miniodata` 卷 | 全量复制 |
| 上传文件临时目录 | `uploads` 卷 | 文件复制 |

## 自动备份（生产环境）

生产环境使用 `docker-compose.prod.yml`，通过 `db-backup` 服务实现自动备份：

```bash
# 启动生产环境（含备份服务）
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

备份服务每天凌晨 3:00 自动执行：
1. `pg_dump -h db -U baohegui baohegui | gzip` → `./backups/db/baohegui_YYYYMMDDHHMMSS.sql.gz`
2. 保留最近 30 天的备份文件，超过的自动删除

## 手动备份

```bash
# 数据库
docker exec baohegui-db-1 pg_dump -U baohegui baohegui | gzip > backup_$(date +%Y%m%d).sql.gz

# MinIO 数据
docker run --rm -v baohegui_miniodata:/data -v $(pwd)/backups:/backups alpine \
  tar czf /backups/minio_$(date +%Y%m%d).tar.gz -C /data .

# 上传目录
docker run --rm -v baohegui_uploads:/data -v $(pwd)/backups:/backups alpine \
  tar czf /backups/uploads_$(date +%Y%m%d).tar.gz -C /data .
```

## 恢复

```bash
# 恢复数据库
gunzip -c backups/db/baohegui_20260601.sql.gz | docker exec -i baohegui-db-1 psql -U baohegui baohegui

# 恢复 MinIO 数据
docker run --rm -v baohegui_miniodata:/data -v $(pwd)/backups:/backups alpine \
  tar xzf /backups/minio_20260601.tar.gz -C /data
```

## 文件保留策略

| 环境 | 保留天数 | 存储位置 |
|------|---------|---------|
| 开发环境 | 7 天 | `./backups/db/` |
| 生产环境 | 30 天 | `./backups/db/` |
