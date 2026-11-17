"""生成学生 1-5 全模块的可演示数据。

默认只在数据库为空时执行；使用 ``--reset`` 会清空业务数据后用演示数据重建。
"""
from __future__ import annotations

import shutil
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from warehouse.access import default_for_role
from warehouse.models import (
    Herb,
    InboundItem,
    InboundOrder,
    OrderAttachment,
    OrderStatus,
    OrderStatusLog,
    OutboundOrder,
    RolePermission,
    StockBatch,
    StockMovement,
    StorageLocation,
    Supplier,
    TransferOrder,
    UserProfile,
    Warehouse,
)
from warehouse.services import (
    approve_order,
    cancel_order,
    complete_inbound,
    complete_transfer,
    complete_outbound,
    record_exception,
    reject_order,
    submit_inbound,
    submit_order,
)

DEMO_USERNAMES = ["admin", "keeper", "manager", "viewer"]


class Command(BaseCommand):
    help = "创建全模块演示账号、基础资料、入库/移库/出库单与权限配置。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="清空已有业务单据与基础数据后重新生成演示数据",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if Warehouse.objects.exists() and not options["reset"]:
            self.stdout.write(
                self.style.WARNING(
                    "数据库中已有业务数据，已跳过。需要重建请执行：python manage.py seed_demo --reset"
                )
            )
            return

        self._reset()
        users = self._create_users()
        self._create_role_permissions(users)
        warehouse = self._create_warehouse()
        locations = self._create_locations(warehouse)
        herbs = self._create_herbs()
        suppliers = self._create_suppliers()
        batches = self._create_stock(herbs, locations, users["keeper"])

        inbounds = self._create_inbounds(users, herbs, locations, suppliers)
        transfers = self._create_transfers(users, herbs, locations, batches)
        outbounds = self._create_outbounds(users, herbs, locations, batches)

        self._attach_demo_file(transfers["t2"], users["keeper"], "当归移库交接单（示例）")
        self._attach_demo_file(transfers["t4"], users["keeper"], "茯苓移库交接与复核单")
        self._attach_demo_file(outbounds["o3"], users["keeper"], "金银花出库复核单")
        record_exception(
            outbounds["o1"],
            users["keeper"],
            "领用人要求分两次领取，已与主管口头确认，待补书面说明。",
        )

        # 统一倒推时间，让工作台的近 7 日图表、列表和轨迹更真实。
        self._backdate(inbounds["i1"], 0)
        self._backdate(inbounds["i2"], 1)
        self._backdate(inbounds["i3"], 2)
        self._backdate(inbounds["i4"], 3)
        self._backdate(inbounds["i5"], 4)
        self._backdate(transfers["t1"], 0)
        self._backdate(transfers["t2"], 1)
        self._backdate(transfers["t3"], 2)
        self._backdate(transfers["t4"], 3)
        self._backdate(transfers["t5"], 4)
        self._backdate(transfers["t6"], 6)
        self._backdate(transfers["t7"], 1)
        self._backdate(outbounds["o1"], 0)
        self._backdate(outbounds["o2"], 1)
        self._backdate(outbounds["o3"], 2)
        self._backdate(outbounds["o4"], 5)
        self._backdate(outbounds["o5"], 4)
        self._backdate(outbounds["o6"], 0)
        self._backdate(outbounds["o7"], 6)
        self._backdate(outbounds["o8"], 0)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("演示数据已生成："))
        self.stdout.write("  仓库：中心饮片仓 WH01（7 个库位）；城南分仓 WH02（1 个库位）")
        self.stdout.write("  基础：8 味药材、3 家供应商、10 个初始库存批次")
        self.stdout.write("  入库：6 张（草稿/待验收/验收通过/已入库/已驳回/已取消）")
        self.stdout.write("  移库：7 张；出库：8 张，覆盖全部状态")
        self.stdout.write("  权限：4 种角色的菜单与接口权限已写入数据库")
        self.stdout.write("  账号：keeper / keeper123（仓管员）")
        self.stdout.write("        manager / manager123（仓库主管）")
        self.stdout.write("        admin / admin123（管理员）")
        self.stdout.write("        viewer / viewer123（只读访客）")
        self.stdout.write("  启动：python manage.py runserver")

    # ------------------------------------------------------------------
    # 基础数据
    # ------------------------------------------------------------------
    def _reset(self):
        self.stdout.write("正在清理旧业务数据…")
        for attachment in OrderAttachment.objects.all():
            if attachment.file:
                attachment.file.delete(save=False)
        OrderStatusLog.objects.all().delete()
        StockMovement.objects.all().delete()
        OrderAttachment.objects.all().delete()
        InboundItem.objects.all().delete()
        InboundOrder.objects.all().delete()
        TransferOrder.objects.all().delete()
        OutboundOrder.objects.all().delete()
        StockBatch.objects.all().delete()
        StorageLocation.objects.all().delete()
        Warehouse.objects.all().delete()
        Supplier.objects.all().delete()
        Herb.objects.all().delete()
        RolePermission.objects.all().delete()
        get_user_model().objects.filter(username__in=DEMO_USERNAMES).delete()
        demo_media = Path(settings.MEDIA_ROOT) / "demo"
        if demo_media.exists():
            shutil.rmtree(demo_media, ignore_errors=True)

    def _create_users(self):
        User = get_user_model()
        specs = [
            ("admin", "admin123", "系统管理员", "信息中心", UserProfile.Role.ADMIN, True),
            ("keeper", "keeper123", "陈远志", "仓储部", UserProfile.Role.KEEPER, False),
            ("manager", "manager123", "周厚朴", "仓储部", UserProfile.Role.MANAGER, False),
            ("viewer", "viewer123", "验收访客", "教学组", UserProfile.Role.VIEWER, False),
        ]
        groups = {
            UserProfile.Role.KEEPER: Group.objects.get_or_create(name="仓管员")[0],
            UserProfile.Role.MANAGER: Group.objects.get_or_create(name="仓库主管")[0],
            UserProfile.Role.ADMIN: Group.objects.get_or_create(name="系统管理员")[0],
        }
        users = {}
        for username, password, display_name, department, role, is_admin in specs:
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=display_name,
                is_staff=is_admin,
                is_superuser=is_admin,
            )
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = role
            profile.department = department
            profile.phone = "1380000000" + str(len(users))
            profile.save()
            if role in groups:
                user.groups.add(groups[role])
            users[username] = user
        return users

    def _create_role_permissions(self, users):
        for role, _label in UserProfile.Role.choices:
            config = default_for_role(role)
            RolePermission.objects.update_or_create(
                role=role,
                defaults={
                    "menus": config["menus"],
                    "permissions": config["permissions"],
                    "updated_by": users["admin"],
                },
            )

    def _create_warehouse(self):
        return Warehouse.objects.create(
            code="WH01",
            name="中心饮片仓",
            address="教学实训楼 B1 层 · 中药仓储区",
        )

    def _create_locations(self, warehouse):
        data = [
            ("A-01", "阴凉区 A 架", "阴凉区"),
            ("A-02", "阴凉区 B 架", "阴凉区"),
            ("B-01", "常温区 A 架", "常温区"),
            ("B-02", "常温区 B 架", "常温区"),
            ("C-01", "易串味药材柜", "隔离区"),
            ("D-01", "待验区", "待验区"),
            ("D-02", "退货暂存区", "退货区"),
        ]
        locations = {}
        for code, name, zone in data:
            locations[code] = StorageLocation.objects.create(
                warehouse=warehouse, code=code, name=name, zone=zone
            )
        branch = Warehouse.objects.create(
            code="WH02", name="城南分仓", address="城南实训点 · 常温库"
        )
        StorageLocation.objects.create(
            warehouse=branch, code="E-01", name="分仓常温区", zone="常温区"
        )
        return locations

    def _create_herbs(self):
        data = [
            ("H001", "黄芪", "统片", "kg", "补气类", "30"),
            ("H002", "当归", "全归片", "kg", "补血类", "20"),
            ("H003", "白术", "麸炒片", "kg", "健脾类", "15"),
            ("H004", "枸杞子", "宁夏统货", "kg", "滋补类", "25"),
            ("H005", "陈皮", "新会陈皮", "kg", "理气类", "10"),
            ("H006", "金银花", "山东统货", "kg", "清热类", "8"),
            ("H007", "丹参", "山东统片", "kg", "活血类", "12"),
            ("H008", "茯苓", "白茯苓块", "kg", "利水类", "18"),
        ]
        herbs = {}
        for code, name, spec, unit, category, safety in data:
            herbs[code] = Herb.objects.create(
                code=code,
                name=name,
                spec=spec,
                unit=unit,
                category=category,
                safety_stock=Decimal(safety),
            )
        return herbs

    def _create_suppliers(self):
        data = [
            ("安徽亳州药材合作社", "王经理", "13905580001", "安徽省亳州市药材市场"),
            ("甘肃岷县当归基地", "李场长", "13893280002", "甘肃省定西市岷县"),
            ("山东平邑金银花供应商", "孙经理", "13953980003", "山东省临沂市平邑县"),
        ]
        suppliers = {}
        for name, contact, phone, address in data:
            suppliers[name] = Supplier.objects.create(
                name=name, contact=contact, phone=phone, address=address
            )
        return suppliers

    def _create_stock(self, herbs, locations, keeper):
        data = [
            ("H001", "A-01", "HQ20260901", "120", "2026-09-01", "2028-09-01"),
            ("H001", "A-02", "HQ20260715", "45", "2026-07-15", "2028-07-15"),
            ("H001", "B-01", "HQ20260901", "25", "2026-09-01", "2028-09-01"),
            ("H002", "A-02", "DG20260915", "48", "2026-09-15", "2028-09-15"),
            ("H003", "B-01", "BZ20260820", "12", "2026-08-20", "2028-08-20"),
            ("H004", "B-01", "GQ20260801", "60", "2026-08-01", "2028-08-01"),
            ("H005", "B-02", "CP20260710", "6", "2026-07-10", "2028-07-10"),
            ("H006", "B-02", "JYH20260905", "22", "2026-09-05", "2028-09-05"),
            ("H007", "A-01", "DS20260812", "35", "2026-08-12", "2028-08-12"),
            ("H008", "D-01", "FL20260820", "80", "2026-08-20", "2028-08-20"),
        ]
        batches = {}
        for code, loc, batch_no, qty, prod, expiry in data:
            batch = StockBatch.objects.create(
                herb=herbs[code],
                location=locations[loc],
                batch_no=batch_no,
                quantity=Decimal(qty),
                production_date=prod,
                expiry_date=expiry,
            )
            batches[(code, loc, batch_no)] = batch
            StockMovement.objects.create(
                batch=batch,
                movement_type=StockMovement.MovementType.OPENING,
                quantity=Decimal(qty),
                before_quantity=Decimal("0"),
                after_quantity=Decimal(qty),
                order_type=StockMovement.OrderType.MANUAL,
                order_no="",
                operator=keeper,
                remark="期初建账（演示数据）",
            )
        return batches

    # ------------------------------------------------------------------
    # 单据
    # ------------------------------------------------------------------
    def _walk_transfer(self, order, status, keeper, manager, review="", cancel_reason=""):
        if status == OrderStatus.DRAFT:
            return
        submit_order(order, keeper)
        if status == OrderStatus.PENDING:
            return
        if status == OrderStatus.REJECTED:
            reject_order(order, manager, review or "资料不完整，请修改后重新提交。")
            return
        if status == OrderStatus.CANCELLED:
            cancel_order(order, keeper, cancel_reason or "业务取消。")
            return
        approve_order(order, manager, review)
        if status == OrderStatus.COMPLETED:
            complete_transfer(order, keeper, "实物与批次核对无误。")

    def _walk_outbound(self, order, status, keeper, manager, review="", cancel_reason=""):
        if status == OrderStatus.DRAFT:
            return
        submit_order(order, keeper)
        if status == OrderStatus.PENDING:
            return
        if status == OrderStatus.REJECTED:
            reject_order(order, manager, review or "资料不完整，请修改后重新提交。")
            return
        if status == OrderStatus.CANCELLED:
            cancel_order(order, keeper, cancel_reason or "业务取消。")
            return
        approve_order(order, manager, review)
        if status == OrderStatus.COMPLETED:
            complete_outbound(order, keeper, "实物与批次核对无误。")

    def _create_transfer(
        self, users, herb, batch_no, from_loc, to_loc, qty, reason, status
    ):
        order = TransferOrder.objects.create(
            herb=herb,
            batch_no=batch_no,
            from_location=from_loc,
            to_location=to_loc,
            quantity=Decimal(qty),
            reason=reason,
            applicant=users["keeper"],
            status=OrderStatus.DRAFT,
        )
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.CREATE,
            users["keeper"],
            comment="创建移库单草稿。",
            from_status="",
            to_status=order.status,
        )
        self._walk_transfer(
            order,
            status,
            users["keeper"],
            users["manager"],
            review="数量、批次与库位核对无误，同意执行。"
            if status in {OrderStatus.APPROVED, OrderStatus.COMPLETED}
            else "",
            cancel_reason="业务需求取消，暂不移库。" if status == OrderStatus.CANCELLED else "",
        )
        return order

    def _create_inbound(
        self, users, supplier, warehouse, inbound_date, item_data, status,
        review="", cancel_reason=""
    ):
        order = InboundOrder.objects.create(
            supplier=supplier,
            warehouse=warehouse,
            inbound_date=inbound_date,
            invoice_no=f"SH{inbound_date:%Y%m%d}01",
            remark="课程演示入库单",
            applicant=users["keeper"],
            status=OrderStatus.DRAFT,
        )
        for herb, batch_no, location, qty, price, production, expiry in item_data:
            InboundItem.objects.create(
                order=order,
                herb=herb,
                batch_no=batch_no,
                location=location,
                quantity=Decimal(qty),
                unit_price=Decimal(price),
                production_date=production,
                expiry_date=expiry,
            )
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.CREATE,
            users["keeper"],
            comment="创建入库单草稿。",
            from_status="",
            to_status=order.status,
        )
        if status == OrderStatus.DRAFT:
            return order
        submit_inbound(order, users["keeper"])
        if status == OrderStatus.PENDING:
            return order
        if status == OrderStatus.REJECTED:
            reject_order(order, users["manager"], review or "随货资料不完整，请补充。")
            return order
        if status == OrderStatus.CANCELLED:
            cancel_order(order, users["keeper"], cancel_reason or "供应商取消发货。")
            return order
        approve_order(order, users["manager"], review or "验收通过，同意入库。")
        if status == OrderStatus.COMPLETED:
            complete_inbound(order, users["keeper"], "实物与随货单核对无误。")
        return order

    def _create_inbounds(self, users, herbs, locations, suppliers):
        from datetime import date

        result = {}
        result["i1"] = self._create_inbound(
            users,
            suppliers["安徽亳州药材合作社"],
            Warehouse.objects.get(code="WH01"),
            date(2026, 10, 30),
            [
                (herbs["H001"], "HQ20261020", locations["A-01"], "20", "58.00", date(2026, 10, 20), date(2028, 10, 20)),
                (herbs["H003"], "BZ20261020", locations["B-01"], "8", "42.00", date(2026, 10, 20), date(2028, 10, 20)),
            ],
            OrderStatus.DRAFT,
        )
        result["i2"] = self._create_inbound(
            users,
            suppliers["甘肃岷县当归基地"],
            Warehouse.objects.get(code="WH01"),
            date(2026, 10, 29),
            [(herbs["H002"], "DG20261010", locations["A-02"], "15", "76.00", date(2026, 10, 10), date(2028, 10, 10))],
            OrderStatus.PENDING,
        )
        result["i3"] = self._create_inbound(
            users,
            suppliers["山东平邑金银花供应商"],
            Warehouse.objects.get(code="WH01"),
            date(2026, 10, 28),
            [(herbs["H006"], "JYH20261001", locations["B-02"], "12", "128.00", date(2026, 10, 1), date(2028, 10, 1))],
            OrderStatus.APPROVED,
            review="质检报告齐全，同意入库。",
        )
        result["i4"] = self._create_inbound(
            users,
            suppliers["安徽亳州药材合作社"],
            Warehouse.objects.get(code="WH01"),
            date(2026, 10, 27),
            [(herbs["H004"], "GQ20261005", locations["B-01"], "18", "52.00", date(2026, 10, 5), date(2028, 10, 5))],
            OrderStatus.COMPLETED,
            review="数量与质检单一致，同意入库。",
        )
        result["i5"] = self._create_inbound(
            users,
            suppliers["山东平邑金银花供应商"],
            Warehouse.objects.get(code="WH01"),
            date(2026, 10, 26),
            [(herbs["H007"], "DS20261018", locations["A-01"], "10", "36.00", date(2026, 10, 18), date(2028, 10, 18))],
            OrderStatus.REJECTED,
            review="缺少批次质检报告，请补齐后重新提交。",
        )
        result["i6"] = self._create_inbound(
            users,
            suppliers["甘肃岷县当归基地"],
            Warehouse.objects.get(code="WH01"),
            date(2026, 10, 25),
            [(herbs["H008"], "FL20261022", locations["D-01"], "6", "45.00", date(2026, 10, 22), date(2028, 10, 22))],
            OrderStatus.CANCELLED,
            cancel_reason="供应商临时取消发货。",
        )
        return result

    def _create_transfers(self, users, herbs, locations, batches):
        result = {}
        result["t1"] = self._create_transfer(
            users,
            herbs["H001"],
            "HQ20260901",
            locations["A-01"],
            locations["B-02"],
            "10",
            "货架调整，靠近复核台",
            OrderStatus.DRAFT,
        )
        result["t2"] = self._create_transfer(
            users,
            herbs["H002"],
            "DG20260915",
            locations["A-02"],
            locations["B-02"],
            "8",
            "批次合并存放，腾出阴凉区货位",
            OrderStatus.PENDING,
        )
        result["t3"] = self._create_transfer(
            users,
            herbs["H005"],
            "CP20260710",
            locations["B-02"],
            locations["A-02"],
            "4",
            "陈皮移入阴凉区，降低串味风险",
            OrderStatus.APPROVED,
        )
        result["t4"] = self._create_transfer(
            users,
            herbs["H008"],
            "FL20260820",
            locations["D-01"],
            locations["A-01"],
            "15",
            "待验合格，转入阴凉区正式货位",
            OrderStatus.COMPLETED,
        )
        result["t5"] = self._create_transfer(
            users,
            herbs["H006"],
            "JYH20260905",
            locations["B-02"],
            locations["A-02"],
            "20",
            "金银花调整至阴凉区",
            OrderStatus.REJECTED,
        )
        result["t6"] = self._create_transfer(
            users,
            herbs["H001"],
            "HQ20260901",
            locations["A-01"],
            locations["B-01"],
            "12",
            "货架调整，就近存放",
            OrderStatus.COMPLETED,
        )
        result["t7"] = self._create_transfer(
            users,
            herbs["H003"],
            "BZ20260820",
            locations["B-01"],
            locations["A-01"],
            "3",
            "临时调整库位",
            OrderStatus.CANCELLED,
        )
        # 驳回报文使用更贴合业务的原因
        rejected = result["t5"]
        rejected.review_comment = "A-02 阴凉区货架已满，请改移至 A-01 后重新提交。"
        rejected.save(update_fields=["review_comment"])
        OrderStatusLog.objects.filter(
            order_type=OrderStatusLog.OrderType.TRANSFER,
            order_id=rejected.pk,
            action=OrderStatusLog.Action.REJECT,
        ).update(comment=rejected.review_comment)
        return result

    def _create_outbound(
        self, users, herb, batch_no, location, qty, recipient, purpose, status
    ):
        order = OutboundOrder.objects.create(
            outbound_type=OutboundOrder.OutboundType.PICK
            if "调拨" not in purpose
            else OutboundOrder.OutboundType.ALLOCATE,
            herb=herb,
            batch_no=batch_no,
            location=location,
            quantity=Decimal(qty),
            recipient=recipient,
            purpose=purpose,
            applicant=users["keeper"],
            status=OrderStatus.DRAFT,
        )
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.CREATE,
            users["keeper"],
            comment="创建出库单草稿。",
            from_status="",
            to_status=order.status,
        )
        self._walk_outbound(
            order,
            status,
            users["keeper"],
            users["manager"],
            review="领用手续与批次核对无误，同意出库。"
            if status in {OrderStatus.APPROVED, OrderStatus.COMPLETED}
            else "",
            cancel_reason="领用计划调整，取消出库。" if status == OrderStatus.CANCELLED else "",
        )
        return order

    def _create_outbounds(self, users, herbs, locations, batches):
        result = {}
        result["o1"] = self._create_outbound(
            users,
            herbs["H001"],
            "HQ20260901",
            locations["A-01"],
            "15",
            "制剂室",
            "生产黄芪颗粒",
            OrderStatus.PENDING,
        )
        result["o2"] = self._create_outbound(
            users,
            herbs["H004"],
            "GQ20260801",
            locations["B-01"],
            "10",
            "门诊中药房",
            "门诊调剂使用",
            OrderStatus.APPROVED,
        )
        result["o3"] = self._create_outbound(
            users,
            herbs["H006"],
            "JYH20260905",
            locations["B-02"],
            "5",
            "制剂室",
            "夏季清凉饮生产",
            OrderStatus.COMPLETED,
        )
        result["o4"] = self._create_outbound(
            users,
            herbs["H007"],
            "DS20260812",
            locations["A-01"],
            "20",
            "外部合作单位",
            "跨机构调拨",
            OrderStatus.REJECTED,
        )
        result["o5"] = self._create_outbound(
            users,
            herbs["H008"],
            "FL20260820",
            locations["D-01"],
            "8",
            "门诊中药房",
            "门诊调剂使用",
            OrderStatus.COMPLETED,
        )
        result["o6"] = self._create_outbound(
            users,
            herbs["H005"],
            "CP20260710",
            locations["B-02"],
            "2",
            "国医堂",
            "饮片调剂",
            OrderStatus.DRAFT,
        )
        result["o7"] = self._create_outbound(
            users,
            herbs["H001"],
            "HQ20260901",
            locations["A-01"],
            "6",
            "制剂室",
            "小批量试制",
            OrderStatus.COMPLETED,
        )
        result["o8"] = self._create_outbound(
            users,
            herbs["H001"],
            "HQ20260901",
            locations["A-01"],
            "4",
            "治未病中心",
            "健康调理饮片",
            OrderStatus.COMPLETED,
        )
        rejected = result["o4"]
        rejected.review_comment = "外部调拨审批单缺失，请补齐审批材料后重新提交。"
        rejected.save(update_fields=["review_comment"])
        OrderStatusLog.objects.filter(
            order_type=OrderStatusLog.OrderType.OUTBOUND,
            order_id=rejected.pk,
            action=OrderStatusLog.Action.REJECT,
        ).update(comment=rejected.review_comment)
        return result

    # ------------------------------------------------------------------
    # 附件 / 时间线
    # ------------------------------------------------------------------
    def _attach_demo_file(self, order, uploader, note):
        source = Path(settings.BASE_DIR) / "demo_assets" / "handover.png"
        if not source.exists():
            return
        relative = f"demo/handover-{order.order_type}-{order.pk}.png"
        target = Path(settings.MEDIA_ROOT) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        attachment = OrderAttachment(
            transfer=order if isinstance(order, TransferOrder) else None,
            outbound=order if isinstance(order, OutboundOrder) else None,
            file=relative,
            original_name="移库交接单示例.png",
            note=note,
            uploaded_by=uploader,
        )
        attachment.full_clean()
        attachment.save()
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.ATTACH,
            uploader,
            comment=f"上传附件：{attachment.original_name}",
            from_status=order.status,
            to_status=order.status,
        )

    def _backdate(self, order, days_ago):
        order.refresh_from_db()
        base = timezone.now() - timedelta(days=days_ago, hours=8, minutes=17)
        submitted = base + timedelta(hours=1)
        audited = base + timedelta(hours=3)
        completed = base + timedelta(hours=5)
        attach_time = (
            completed + timedelta(minutes=30)
            if order.status == OrderStatus.COMPLETED
            else base + timedelta(hours=2, minutes=20)
        )
        action_time = {
            OrderStatusLog.Action.CREATE: base,
            OrderStatusLog.Action.SUBMIT: submitted,
            OrderStatusLog.Action.APPROVE: audited,
            OrderStatusLog.Action.REJECT: audited,
            OrderStatusLog.Action.ATTACH: attach_time,
            OrderStatusLog.Action.EXCEPTION: base + timedelta(hours=4, minutes=10),
            OrderStatusLog.Action.COMPLETE: completed,
        }
        seen = {}
        log_times = []
        logs = list(OrderStatusLog.for_order(order))
        for log in logs:
            count = seen.get(log.action, 0)
            stamp = action_time.get(log.action, base + timedelta(hours=2))
            stamp += timedelta(minutes=count * 3)
            seen[log.action] = count + 1
            log_times.append(stamp)
            OrderStatusLog.objects.filter(pk=log.pk).update(created_at=stamp)

        updates = {
            "created_at": base,
            "updated_at": max(log_times) if log_times else base,
        }
        if order.submitted_at:
            updates["submitted_at"] = submitted
        if order.audited_at:
            updates["audited_at"] = audited
        if order.completed_at:
            updates["completed_at"] = completed
        type(order).objects.filter(pk=order.pk).update(**updates)
        if order.status == OrderStatus.COMPLETED:
            StockMovement.objects.filter(order_no=order.order_no).update(created_at=completed)
        if hasattr(order, "attachments"):
            for attachment in order.attachments.all():
                OrderAttachment.objects.filter(pk=attachment.pk).update(created_at=attach_time)
        order.refresh_from_db()

