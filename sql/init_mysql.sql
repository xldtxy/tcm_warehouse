-- =============================================================================
-- 本草仓 · 中药仓储库位管理系统
-- MySQL 初始化脚本（仅创建数据库与字符集，业务表由 Django 迁移生成）
-- =============================================================================
-- 使用方式：
--   mysql -u root -p < sql/init_mysql.sql
--   set DB_ENGINE=mysql & set DB_NAME=tcm_wms & set DB_USER=root & set DB_PASSWORD=你的密码
--   python manage.py migrate
--   python manage.py seed_demo
--
-- 之所以不在本文件里手写全部业务表：Django 迁移 warehouse/migrations/0001_initial.py
-- 才是与模型、索引、约束严格同步的“数据库脚本”，可重复执行且不会与代码漂移。
-- 本文件负责完成 MySQL 层面的建库、字符集和最小权限账号准备。
-- =============================================================================

CREATE DATABASE IF NOT EXISTS `tcm_wms`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

-- 可选：创建独立业务账号（请先修改密码，再取消注释执行）
-- CREATE USER IF NOT EXISTS 'tcm_wms'@'localhost' IDENTIFIED BY 'change-me';
-- GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
--   ON `tcm_wms`.* TO 'tcm_wms'@'localhost';
-- FLUSH PRIVILEGES;

USE `tcm_wms`;

-- 说明：
-- 1. 用户/角色权限、供应商、药材、库位、库存批次、入库单/明细、
--    移库单、出库单、附件、状态轨迹、库存流水等业务表，
--    由 Django 迁移统一创建，字段类型、外键、唯一约束、检查约束和索引均以模型为准。
-- 2. 生产部署建议：
--    python manage.py migrate --noinput
--    python manage.py collectstatic --noinput
--    python manage.py createsuperuser
-- 3. 本课程演示默认使用 SQLite，无需本文件；需要展示 MySQL 时按上方步骤切换即可。
