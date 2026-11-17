from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from warehouse.models import (
    Herb,
    InboundOrder,
    OrderStatus,
    RolePermission,
    StockBatch,
    StockMovement,
    StorageLocation,
    Supplier,
    UserProfile,
    Warehouse,
)
from warehouse.permissions import has_perm

from .base import WarehouseTestBase


class AccountAndAccessTests(WarehouseTestBase):
    def test_registration_creates_viewer(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "newuser",
                "first_name": "新用户",
                "email": "new@example.com",
                "phone": "13800001111",
                "department": "仓储部",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="newuser")
        self.assertEqual(user.profile.role, UserProfile.Role.VIEWER)
        self.assertEqual(user.profile.phone, "13800001111")

    def test_admin_can_create_and_edit_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user_create"),
            {
                "username": "warehouse2",
                "first_name": "新仓管",
                "email": "",
                "role": UserProfile.Role.KEEPER,
                "phone": "13900000000",
                "department": "仓储部",
                "is_active": "on",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="warehouse2")
        self.assertEqual(user.profile.role, UserProfile.Role.KEEPER)
        self.assertTrue(user.is_active)

        response = self.client.post(
            reverse("user_edit", args=[user.pk]),
            {
                "username": "warehouse2",
                "first_name": "新仓管",
                "email": "",
                "role": UserProfile.Role.MANAGER,
                "phone": "13900000001",
                "department": "仓储部",
                "is_active": "on",
                "new_password1": "",
                "new_password2": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.profile.role, UserProfile.Role.MANAGER)

    def test_non_admin_cannot_manage_users(self):
        self.client.force_login(self.keeper)
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 403)

    def test_role_menu_and_api_permissions_are_configurable(self):
        RolePermission.objects.create(
            role=UserProfile.Role.VIEWER,
            menus=["dashboard"],
            permissions={"query.view": False},
        )
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("stock_list")).status_code, 403)
        self.assertFalse(
            has_perm(get_user_model().objects.get(pk=self.viewer.pk), "stock.view")
        )

    def test_role_configuration_saves_menus_and_view_permission(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("role_permissions"),
            {
                "role": "keeper",
                "menus": ["dashboard", "stock"],
                "perm_stock.view": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        record = RolePermission.objects.get(role="keeper")
        self.assertIn("stock", record.menus)
        self.assertTrue(record.permissions["stock.view"])

    def test_warehouse_and_location_crud(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("warehouse_create"),
            {"code": "wh03", "name": "新仓库", "address": "测试", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        warehouse = Warehouse.objects.get(code="WH03")
        response = self.client.post(
            reverse("location_create"),
            {
                "warehouse": warehouse.pk,
                "code": "a-01",
                "name": "新库位",
                "zone": "常温区",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(warehouse.locations.filter(code="A-01").exists())


class CatalogTests(WarehouseTestBase):
    def test_herb_create_and_detail(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("herb_create"),
            {
                "code": "h009",
                "name": "甘草",
                "spec": "圆片",
                "unit": "kg",
                "category": "补气类",
                "safety_stock": "5",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        herb = Herb.objects.get(code="H009")
        self.assertEqual(herb.name, "甘草")
        self.client.get(reverse("herb_detail", args=[herb.pk]))

    def test_stock_create_writes_opening_movement(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("stock_create"),
            {
                "herb": self.herb.pk,
                "location": self.loc_c.pk,
                "batch_no": "NEWBATCH",
                "quantity": "5",
                "production_date": "2026-10-01",
                "expiry_date": "2028-10-01",
            },
        )
        self.assertEqual(response.status_code, 302)
        batch = StockBatch.objects.get(batch_no="NEWBATCH")
        self.assertEqual(batch.quantity, Decimal("5"))
        movement = StockMovement.objects.get(batch=batch)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OPENING)

    def test_stock_adjustment_writes_adjust_movement(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("stock_edit", args=[self.batch.pk]),
            {
                "production_date": self.batch.production_date.isoformat(),
                "expiry_date": self.batch.expiry_date.isoformat(),
                "new_quantity": "90",
                "adjust_reason": "月度盘点差异",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, Decimal("90"))
        movement = StockMovement.objects.filter(
            batch=self.batch, movement_type=StockMovement.MovementType.ADJUST
        ).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.before_quantity, Decimal("100"))
        self.assertEqual(movement.after_quantity, Decimal("90"))


class InboundTests(WarehouseTestBase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name="测试供应商")
        self.inbound_payload = {
            "supplier": self.supplier.pk,
            "warehouse": self.warehouse.pk,
            "inbound_date": "2026-10-30",
            "invoice_no": "SH001",
            "remark": "测试入库",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-herb": self.herb.pk,
            "items-0-batch_no": "INBATCH01",
            "items-0-location": self.loc_b.pk,
            "items-0-quantity": "7",
            "items-0-unit_price": "12.50",
            "items-0-production_date": "2026-10-01",
            "items-0-expiry_date": "2028-10-01",
            "items-0-remark": "",
            "action": "submit",
        }

    def test_inbound_create_submit_approve_complete(self):
        self.client.force_login(self.keeper)
        response = self.client.post(reverse("inbound_create"), self.inbound_payload)
        self.assertEqual(response.status_code, 302)
        order = InboundOrder.objects.get()
        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertEqual(order.total_quantity, Decimal("7"))

        self.client.force_login(self.manager)
        self.client.post(
            reverse("inbound_approve", args=[order.pk]), {"comment": "验收通过"}
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.APPROVED)

        before = StockBatch.objects.filter(
            herb=self.herb, location=self.loc_b, batch_no="INBATCH01"
        ).first()
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("inbound_complete", args=[order.pk]), {"comment": "入库"}
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        batch = StockBatch.objects.get(
            herb=self.herb, location=self.loc_b, batch_no="INBATCH01"
        )
        self.assertEqual(batch.quantity, Decimal("7") if not before else Decimal("17"))
        movement = StockMovement.objects.get(
            order_type=StockMovement.OrderType.INBOUND, order_no=order.inbound_no
        )
        self.assertEqual(movement.order_id, order.pk)

    def test_inbound_rejects_location_from_other_warehouse(self):
        other = Warehouse.objects.create(code="WH99", name="外仓")
        other_loc = StorageLocation.objects.create(warehouse=other, code="Z-01")
        payload = dict(self.inbound_payload)
        payload["items-0-location"] = other_loc.pk
        payload["action"] = "draft"
        self.client.force_login(self.keeper)
        response = self.client.post(reverse("inbound_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(InboundOrder.objects.count(), 0)
        self.assertContains(response, "不属于所选入库仓库", status_code=200)

    def test_inbound_requires_at_least_one_item(self):
        payload = dict(self.inbound_payload)
        for key in list(payload):
            if key.startswith("items-0-"):
                payload.pop(key)
        payload["items-TOTAL_FORMS"] = "1"
        self.client.force_login(self.keeper)
        response = self.client.post(reverse("inbound_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(InboundOrder.objects.count(), 0)


class ReportTests(WarehouseTestBase):
    def test_stock_query_filters_and_print(self):
        self.client.force_login(self.keeper)
        response = self.client.get(
            reverse("stock_query"), {"q": "HQ20260901", "order_type": "manual"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HQ20260901")
        print_response = self.client.get(reverse("stock_query_print"))
        self.assertEqual(print_response.status_code, 200)
        self.assertContains(print_response, "库存流水查询单")

    def test_stock_export_csv(self):
        self.client.force_login(self.keeper)
        response = self.client.get(reverse("stock_query_export"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

    def test_viewer_can_view_reports_but_not_export(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("stock_query")).status_code, 200)
        self.assertEqual(self.client.get(reverse("stock_query_export")).status_code, 403)

    def test_operation_logs_filter(self):
        self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.manager)
        response = self.client.get(reverse("operation_logs"), {"action": "create"})
        self.assertEqual(response.status_code, 200)

    def test_operation_logs_export(self):
        self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.manager)
        response = self.client.get(reverse("operation_logs_export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("操作时间".encode("utf-8"), response.content)
