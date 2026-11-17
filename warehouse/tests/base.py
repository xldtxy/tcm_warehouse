from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from warehouse.models import (
    Herb,
    OutboundOrder,
    StockBatch,
    StorageLocation,
    TransferOrder,
    UserProfile,
    Warehouse,
)


class WarehouseTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.keeper = User.objects.create_user(
            username="keeper", password="keeper123", first_name="陈远志"
        )
        cls.keeper.profile.role = UserProfile.Role.KEEPER
        cls.keeper.profile.save()

        cls.keeper2 = User.objects.create_user(
            username="keeper2", password="keeper123", first_name="李时珍"
        )
        cls.keeper2.profile.role = UserProfile.Role.KEEPER
        cls.keeper2.profile.save()

        cls.manager = User.objects.create_user(
            username="manager", password="manager123", first_name="周厚朴"
        )
        cls.manager.profile.role = UserProfile.Role.MANAGER
        cls.manager.profile.save()

        cls.viewer = User.objects.create_user(
            username="viewer", password="viewer123", first_name="访客"
        )
        cls.viewer.profile.role = UserProfile.Role.VIEWER
        cls.viewer.profile.save()

        cls.admin = User.objects.create_superuser(
            username="admin", password="admin123", first_name="系统管理员"
        )
        cls.admin.profile.role = UserProfile.Role.ADMIN
        cls.admin.profile.save()

        cls.warehouse = Warehouse.objects.create(code="WH01", name="中心饮片仓")
        cls.loc_a = StorageLocation.objects.create(
            warehouse=cls.warehouse, code="A-01", name="阴凉区 A 架", zone="阴凉区"
        )
        cls.loc_b = StorageLocation.objects.create(
            warehouse=cls.warehouse, code="B-01", name="常温区 A 架", zone="常温区"
        )
        cls.loc_c = StorageLocation.objects.create(
            warehouse=cls.warehouse, code="C-01", name="空库位", zone="常温区"
        )
        cls.herb = Herb.objects.create(
            code="H001",
            name="黄芪",
            spec="统片",
            unit="kg",
            safety_stock=Decimal("20"),
        )
        cls.batch = StockBatch.objects.create(
            herb=cls.herb,
            location=cls.loc_a,
            batch_no="HQ20260901",
            quantity=Decimal("100"),
            production_date=date(2026, 9, 1),
            expiry_date=date(2028, 9, 1),
        )
        cls.batch_b = StockBatch.objects.create(
            herb=cls.herb,
            location=cls.loc_b,
            batch_no="HQ20260901",
            quantity=Decimal("10"),
        )

    def make_transfer(self, quantity="10", status="draft", applicant=None, to_location=None):
        return TransferOrder.objects.create(
            herb=self.herb,
            batch_no="HQ20260901",
            from_location=self.loc_a,
            to_location=to_location or self.loc_b,
            quantity=Decimal(quantity),
            reason="货架调整",
            applicant=applicant or self.keeper,
            status=status,
        )

    def make_outbound(self, quantity="10", status="draft", applicant=None, location=None):
        return OutboundOrder.objects.create(
            outbound_type=OutboundOrder.OutboundType.PICK,
            herb=self.herb,
            batch_no="HQ20260901",
            location=location or self.loc_a,
            quantity=Decimal(quantity),
            recipient="制剂室",
            purpose="生产试制",
            applicant=applicant or self.keeper,
            status=status,
        )
