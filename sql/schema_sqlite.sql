-- 本草仓 · 中药仓储库位管理系统（学生 1-5 完整版）
-- SQLite 参考建表脚本（由实际迁移后的数据库导出，仅用于课程报告/结构核对）
-- 正式初始化请执行：python manage.py migrate
-- MySQL 初始化请先执行 sql/init_mysql.sql，再执行 Django migrate。
PRAGMA foreign_keys = ON;

-- table: auth_group
CREATE TABLE "auth_group" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(150) NOT NULL UNIQUE);

-- table: auth_group_permissions
CREATE TABLE "auth_group_permissions" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED, "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: auth_permission
CREATE TABLE "auth_permission" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "content_type_id" integer NOT NULL REFERENCES "django_content_type" ("id") DEFERRABLE INITIALLY DEFERRED, "codename" varchar(100) NOT NULL, "name" varchar(255) NOT NULL);

-- table: auth_user
CREATE TABLE "auth_user" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "password" varchar(128) NOT NULL, "last_login" datetime NULL, "is_superuser" bool NOT NULL, "username" varchar(150) NOT NULL UNIQUE, "last_name" varchar(150) NOT NULL, "email" varchar(254) NOT NULL, "is_staff" bool NOT NULL, "is_active" bool NOT NULL, "date_joined" datetime NOT NULL, "first_name" varchar(150) NOT NULL);

-- table: auth_user_groups
CREATE TABLE "auth_user_groups" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "user_id" integer NOT NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: auth_user_user_permissions
CREATE TABLE "auth_user_user_permissions" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "user_id" integer NOT NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_herb
CREATE TABLE "warehouse_herb" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "code" varchar(30) NOT NULL UNIQUE, "name" varchar(80) NOT NULL, "spec" varchar(80) NOT NULL, "unit" varchar(10) NOT NULL, "category" varchar(40) NOT NULL, "safety_stock" decimal NOT NULL, "is_active" bool NOT NULL);

-- table: warehouse_inbounditem
CREATE TABLE "warehouse_inbounditem" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "batch_no" varchar(50) NOT NULL, "quantity" decimal NOT NULL, "unit_price" decimal NOT NULL, "production_date" date NULL, "expiry_date" date NULL, "remark" varchar(200) NOT NULL, "herb_id" bigint NOT NULL REFERENCES "warehouse_herb" ("id") DEFERRABLE INITIALLY DEFERRED, "location_id" bigint NOT NULL REFERENCES "warehouse_storagelocation" ("id") DEFERRABLE INITIALLY DEFERRED, "order_id" bigint NOT NULL REFERENCES "warehouse_inboundorder" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "uniq_inbound_item_herb_batch_location" UNIQUE ("order_id", "herb_id", "batch_no", "location_id"));

-- table: warehouse_inboundorder
CREATE TABLE "warehouse_inboundorder" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "status" varchar(16) NOT NULL, "review_comment" varchar(300) NOT NULL, "exception_note" text NOT NULL, "submitted_at" datetime NULL, "audited_at" datetime NULL, "completed_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "inbound_no" varchar(24) NOT NULL UNIQUE, "inbound_date" date NOT NULL, "invoice_no" varchar(60) NOT NULL, "remark" text NOT NULL, "applicant_id" integer NOT NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "auditor_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "warehouse_id" bigint NOT NULL REFERENCES "warehouse_warehouse" ("id") DEFERRABLE INITIALLY DEFERRED, "supplier_id" bigint NOT NULL REFERENCES "warehouse_supplier" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_orderattachment
CREATE TABLE "warehouse_orderattachment" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "file" varchar(100) NOT NULL, "original_name" varchar(255) NOT NULL, "note" varchar(200) NOT NULL, "created_at" datetime NOT NULL, "uploaded_by_id" integer NOT NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "outbound_id" bigint NULL REFERENCES "warehouse_outboundorder" ("id") DEFERRABLE INITIALLY DEFERRED, "transfer_id" bigint NULL REFERENCES "warehouse_transferorder" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_orderstatuslog
CREATE TABLE "warehouse_orderstatuslog" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "order_type" varchar(16) NOT NULL, "order_id" bigint unsigned NOT NULL CHECK ("order_id" >= 0), "order_no" varchar(24) NOT NULL, "action" varchar(20) NOT NULL, "from_status" varchar(16) NOT NULL, "to_status" varchar(16) NOT NULL, "comment" varchar(500) NOT NULL, "created_at" datetime NOT NULL, "operator_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_outboundorder
CREATE TABLE "warehouse_outboundorder" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "status" varchar(16) NOT NULL, "review_comment" varchar(300) NOT NULL, "exception_note" text NOT NULL, "submitted_at" datetime NULL, "audited_at" datetime NULL, "completed_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "outbound_no" varchar(24) NOT NULL UNIQUE, "outbound_type" varchar(16) NOT NULL, "batch_no" varchar(50) NOT NULL, "quantity" decimal NOT NULL, "recipient" varchar(80) NOT NULL, "purpose" varchar(300) NOT NULL, "applicant_id" integer NOT NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "auditor_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "herb_id" bigint NOT NULL REFERENCES "warehouse_herb" ("id") DEFERRABLE INITIALLY DEFERRED, "location_id" bigint NOT NULL REFERENCES "warehouse_storagelocation" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_rolepermission
CREATE TABLE "warehouse_rolepermission" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "role" varchar(16) NOT NULL UNIQUE, "menus" text NOT NULL CHECK ((JSON_VALID("menus") OR "menus" IS NULL)), "permissions" text NOT NULL CHECK ((JSON_VALID("permissions") OR "permissions" IS NULL)), "updated_at" datetime NOT NULL, "updated_by_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_stockbatch
CREATE TABLE "warehouse_stockbatch" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "batch_no" varchar(50) NOT NULL, "quantity" decimal NOT NULL, "production_date" date NULL, "expiry_date" date NULL, "updated_at" datetime NOT NULL, "herb_id" bigint NOT NULL REFERENCES "warehouse_herb" ("id") DEFERRABLE INITIALLY DEFERRED, "location_id" bigint NOT NULL REFERENCES "warehouse_storagelocation" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "uniq_stock_herb_location_batch" UNIQUE ("herb_id", "location_id", "batch_no"), CONSTRAINT "stock_quantity_non_negative" CHECK ("quantity" >= '0'));

-- table: warehouse_stockmovement
CREATE TABLE "warehouse_stockmovement" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "movement_type" varchar(20) NOT NULL, "quantity" decimal NOT NULL, "before_quantity" decimal NOT NULL, "after_quantity" decimal NOT NULL, "order_type" varchar(16) NOT NULL, "order_no" varchar(24) NOT NULL, "remark" varchar(300) NOT NULL, "created_at" datetime NOT NULL, "batch_id" bigint NOT NULL REFERENCES "warehouse_stockbatch" ("id") DEFERRABLE INITIALLY DEFERRED, "operator_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "order_id" bigint unsigned NULL CHECK ("order_id" >= 0));

-- table: warehouse_storagelocation
CREATE TABLE "warehouse_storagelocation" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "code" varchar(30) NOT NULL, "name" varchar(80) NOT NULL, "zone" varchar(30) NOT NULL, "is_active" bool NOT NULL, "warehouse_id" bigint NOT NULL REFERENCES "warehouse_warehouse" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "uniq_location_warehouse_code" UNIQUE ("warehouse_id", "code"));

-- table: warehouse_supplier
CREATE TABLE "warehouse_supplier" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(120) NOT NULL UNIQUE, "contact" varchar(40) NOT NULL, "phone" varchar(30) NOT NULL, "address" varchar(200) NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL);

-- table: warehouse_transferorder
CREATE TABLE "warehouse_transferorder" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "status" varchar(16) NOT NULL, "review_comment" varchar(300) NOT NULL, "exception_note" text NOT NULL, "submitted_at" datetime NULL, "audited_at" datetime NULL, "completed_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "transfer_no" varchar(24) NOT NULL UNIQUE, "batch_no" varchar(50) NOT NULL, "quantity" decimal NOT NULL, "reason" varchar(300) NOT NULL, "applicant_id" integer NOT NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "auditor_id" integer NULL REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED, "from_location_id" bigint NOT NULL REFERENCES "warehouse_storagelocation" ("id") DEFERRABLE INITIALLY DEFERRED, "herb_id" bigint NOT NULL REFERENCES "warehouse_herb" ("id") DEFERRABLE INITIALLY DEFERRED, "to_location_id" bigint NOT NULL REFERENCES "warehouse_storagelocation" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_userprofile
CREATE TABLE "warehouse_userprofile" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "role" varchar(16) NOT NULL, "phone" varchar(20) NOT NULL, "department" varchar(50) NOT NULL, "user_id" integer NOT NULL UNIQUE REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED);

-- table: warehouse_warehouse
CREATE TABLE "warehouse_warehouse" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "code" varchar(20) NOT NULL UNIQUE, "name" varchar(80) NOT NULL, "address" varchar(200) NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL);

-- index: auth_group_permissions_group_id_b120cbf9
CREATE INDEX "auth_group_permissions_group_id_b120cbf9" ON "auth_group_permissions" ("group_id");

-- index: auth_group_permissions_group_id_permission_id_0cd325b0_uniq
CREATE UNIQUE INDEX "auth_group_permissions_group_id_permission_id_0cd325b0_uniq" ON "auth_group_permissions" ("group_id", "permission_id");

-- index: auth_group_permissions_permission_id_84c5c92e
CREATE INDEX "auth_group_permissions_permission_id_84c5c92e" ON "auth_group_permissions" ("permission_id");

-- index: auth_permission_content_type_id_2f476e4b
CREATE INDEX "auth_permission_content_type_id_2f476e4b" ON "auth_permission" ("content_type_id");

-- index: auth_permission_content_type_id_codename_01ab375a_uniq
CREATE UNIQUE INDEX "auth_permission_content_type_id_codename_01ab375a_uniq" ON "auth_permission" ("content_type_id", "codename");

-- index: auth_user_groups_group_id_97559544
CREATE INDEX "auth_user_groups_group_id_97559544" ON "auth_user_groups" ("group_id");

-- index: auth_user_groups_user_id_6a12ed8b
CREATE INDEX "auth_user_groups_user_id_6a12ed8b" ON "auth_user_groups" ("user_id");

-- index: auth_user_groups_user_id_group_id_94350c0c_uniq
CREATE UNIQUE INDEX "auth_user_groups_user_id_group_id_94350c0c_uniq" ON "auth_user_groups" ("user_id", "group_id");

-- index: auth_user_user_permissions_permission_id_1fbb5f2c
CREATE INDEX "auth_user_user_permissions_permission_id_1fbb5f2c" ON "auth_user_user_permissions" ("permission_id");

-- index: auth_user_user_permissions_user_id_a95ead1b
CREATE INDEX "auth_user_user_permissions_user_id_a95ead1b" ON "auth_user_user_permissions" ("user_id");

-- index: auth_user_user_permissions_user_id_permission_id_14a6b632_uniq
CREATE UNIQUE INDEX "auth_user_user_permissions_user_id_permission_id_14a6b632_uniq" ON "auth_user_user_permissions" ("user_id", "permission_id");

-- index: django_admin_log_content_type_id_c4bce8eb
CREATE INDEX "django_admin_log_content_type_id_c4bce8eb" ON "django_admin_log" ("content_type_id");

-- index: django_admin_log_user_id_c564eba6
CREATE INDEX "django_admin_log_user_id_c564eba6" ON "django_admin_log" ("user_id");

-- index: django_content_type_app_label_model_76bd3d3b_uniq
CREATE UNIQUE INDEX "django_content_type_app_label_model_76bd3d3b_uniq" ON "django_content_type" ("app_label", "model");

-- index: django_session_expire_date_a5c62663
CREATE INDEX "django_session_expire_date_a5c62663" ON "django_session" ("expire_date");

-- index: warehouse_i_batch_n_fce937_idx
CREATE INDEX "warehouse_i_batch_n_fce937_idx" ON "warehouse_inbounditem" ("batch_no");

-- index: warehouse_i_order_i_9c45de_idx
CREATE INDEX "warehouse_i_order_i_9c45de_idx" ON "warehouse_inbounditem" ("order_id", "herb_id");

-- index: warehouse_i_status_d65bab_idx
CREATE INDEX "warehouse_i_status_d65bab_idx" ON "warehouse_inboundorder" ("status", "created_at" DESC);

-- index: warehouse_i_warehou_168521_idx
CREATE INDEX "warehouse_i_warehou_168521_idx" ON "warehouse_inboundorder" ("warehouse_id", "inbound_date");

-- index: warehouse_inbounditem_herb_id_94dead3e
CREATE INDEX "warehouse_inbounditem_herb_id_94dead3e" ON "warehouse_inbounditem" ("herb_id");

-- index: warehouse_inbounditem_location_id_dcc02a2a
CREATE INDEX "warehouse_inbounditem_location_id_dcc02a2a" ON "warehouse_inbounditem" ("location_id");

-- index: warehouse_inbounditem_order_id_6ee7ad5c
CREATE INDEX "warehouse_inbounditem_order_id_6ee7ad5c" ON "warehouse_inbounditem" ("order_id");

-- index: warehouse_inboundorder_applicant_id_80498fac
CREATE INDEX "warehouse_inboundorder_applicant_id_80498fac" ON "warehouse_inboundorder" ("applicant_id");

-- index: warehouse_inboundorder_auditor_id_c9667047
CREATE INDEX "warehouse_inboundorder_auditor_id_c9667047" ON "warehouse_inboundorder" ("auditor_id");

-- index: warehouse_inboundorder_status_13607f4e
CREATE INDEX "warehouse_inboundorder_status_13607f4e" ON "warehouse_inboundorder" ("status");

-- index: warehouse_inboundorder_supplier_id_373fbf43
CREATE INDEX "warehouse_inboundorder_supplier_id_373fbf43" ON "warehouse_inboundorder" ("supplier_id");

-- index: warehouse_inboundorder_warehouse_id_37aceb24
CREATE INDEX "warehouse_inboundorder_warehouse_id_37aceb24" ON "warehouse_inboundorder" ("warehouse_id");

-- index: warehouse_o_herb_id_f29c9e_idx
CREATE INDEX "warehouse_o_herb_id_f29c9e_idx" ON "warehouse_outboundorder" ("herb_id", "batch_no");

-- index: warehouse_o_order_t_097f08_idx
CREATE INDEX "warehouse_o_order_t_097f08_idx" ON "warehouse_orderstatuslog" ("order_type", "order_id", "created_at");

-- index: warehouse_o_status_86f278_idx
CREATE INDEX "warehouse_o_status_86f278_idx" ON "warehouse_outboundorder" ("status", "created_at" DESC);

-- index: warehouse_orderattachment_outbound_id_5e81ecea
CREATE INDEX "warehouse_orderattachment_outbound_id_5e81ecea" ON "warehouse_orderattachment" ("outbound_id");

-- index: warehouse_orderattachment_transfer_id_37fdb915
CREATE INDEX "warehouse_orderattachment_transfer_id_37fdb915" ON "warehouse_orderattachment" ("transfer_id");

-- index: warehouse_orderattachment_uploaded_by_id_f5db2767
CREATE INDEX "warehouse_orderattachment_uploaded_by_id_f5db2767" ON "warehouse_orderattachment" ("uploaded_by_id");

-- index: warehouse_orderstatuslog_operator_id_75a0911e
CREATE INDEX "warehouse_orderstatuslog_operator_id_75a0911e" ON "warehouse_orderstatuslog" ("operator_id");

-- index: warehouse_outboundorder_applicant_id_d7315eed
CREATE INDEX "warehouse_outboundorder_applicant_id_d7315eed" ON "warehouse_outboundorder" ("applicant_id");

-- index: warehouse_outboundorder_auditor_id_7f3b3d9a
CREATE INDEX "warehouse_outboundorder_auditor_id_7f3b3d9a" ON "warehouse_outboundorder" ("auditor_id");

-- index: warehouse_outboundorder_herb_id_e2e6f1df
CREATE INDEX "warehouse_outboundorder_herb_id_e2e6f1df" ON "warehouse_outboundorder" ("herb_id");

-- index: warehouse_outboundorder_location_id_cff37f4e
CREATE INDEX "warehouse_outboundorder_location_id_cff37f4e" ON "warehouse_outboundorder" ("location_id");

-- index: warehouse_outboundorder_status_3c42eea2
CREATE INDEX "warehouse_outboundorder_status_3c42eea2" ON "warehouse_outboundorder" ("status");

-- index: warehouse_rolepermission_updated_by_id_55f32e8e
CREATE INDEX "warehouse_rolepermission_updated_by_id_55f32e8e" ON "warehouse_rolepermission" ("updated_by_id");

-- index: warehouse_s_batch_i_a6aa0a_idx
CREATE INDEX "warehouse_s_batch_i_a6aa0a_idx" ON "warehouse_stockmovement" ("batch_id", "created_at" DESC);

-- index: warehouse_s_herb_id_92a4c1_idx
CREATE INDEX "warehouse_s_herb_id_92a4c1_idx" ON "warehouse_stockbatch" ("herb_id", "location_id", "batch_no");

-- index: warehouse_s_order_t_359b74_idx
CREATE INDEX "warehouse_s_order_t_359b74_idx" ON "warehouse_stockmovement" ("order_type", "order_no");

-- index: warehouse_stockbatch_herb_id_afa76dd8
CREATE INDEX "warehouse_stockbatch_herb_id_afa76dd8" ON "warehouse_stockbatch" ("herb_id");

-- index: warehouse_stockbatch_location_id_bd7fc763
CREATE INDEX "warehouse_stockbatch_location_id_bd7fc763" ON "warehouse_stockbatch" ("location_id");

-- index: warehouse_stockmovement_batch_id_3e455354
CREATE INDEX "warehouse_stockmovement_batch_id_3e455354" ON "warehouse_stockmovement" ("batch_id");

-- index: warehouse_stockmovement_operator_id_9567f4ac
CREATE INDEX "warehouse_stockmovement_operator_id_9567f4ac" ON "warehouse_stockmovement" ("operator_id");

-- index: warehouse_storagelocation_warehouse_id_096954d1
CREATE INDEX "warehouse_storagelocation_warehouse_id_096954d1" ON "warehouse_storagelocation" ("warehouse_id");

-- index: warehouse_t_herb_id_af5c8f_idx
CREATE INDEX "warehouse_t_herb_id_af5c8f_idx" ON "warehouse_transferorder" ("herb_id", "batch_no");

-- index: warehouse_t_status_db3656_idx
CREATE INDEX "warehouse_t_status_db3656_idx" ON "warehouse_transferorder" ("status", "created_at" DESC);

-- index: warehouse_transferorder_applicant_id_2f4abb4e
CREATE INDEX "warehouse_transferorder_applicant_id_2f4abb4e" ON "warehouse_transferorder" ("applicant_id");

-- index: warehouse_transferorder_auditor_id_fba2511e
CREATE INDEX "warehouse_transferorder_auditor_id_fba2511e" ON "warehouse_transferorder" ("auditor_id");

-- index: warehouse_transferorder_from_location_id_06e84b3f
CREATE INDEX "warehouse_transferorder_from_location_id_06e84b3f" ON "warehouse_transferorder" ("from_location_id");

-- index: warehouse_transferorder_herb_id_23b089dc
CREATE INDEX "warehouse_transferorder_herb_id_23b089dc" ON "warehouse_transferorder" ("herb_id");

-- index: warehouse_transferorder_status_b734ca26
CREATE INDEX "warehouse_transferorder_status_b734ca26" ON "warehouse_transferorder" ("status");

-- index: warehouse_transferorder_to_location_id_8c16a0e0
CREATE INDEX "warehouse_transferorder_to_location_id_8c16a0e0" ON "warehouse_transferorder" ("to_location_id");
