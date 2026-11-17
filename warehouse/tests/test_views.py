import shutil
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from warehouse.models import (
    OrderAttachment,
    OrderStatus,
    OrderStatusLog,
    OutboundOrder,
    TransferOrder,
)

from .base import WarehouseTestBase

TEST_MEDIA_ROOT = Path(settings.BASE_DIR) / "test_media"


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ViewPermissionTests(WarehouseTestBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("transfer_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_keeper_can_open_create_form(self):
        self.client.force_login(self.keeper)
        response = self.client.get(reverse("transfer_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新建移库单")

    def test_manager_cannot_create_order(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("transfer_create"))
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_create_order(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("outbound_create"))
        self.assertEqual(response.status_code, 403)

    def test_keeper_can_create_draft_then_submit_from_detail(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("transfer_create"),
            {
                "action": "draft",
                "herb": self.herb.pk,
                "batch_no": "HQ20260901",
                "from_location": self.loc_a.pk,
                "to_location": self.loc_b.pk,
                "quantity": "10",
                "reason": "货架调整",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = TransferOrder.objects.get()
        self.assertEqual(order.status, OrderStatus.DRAFT)
        self.assertEqual(order.applicant, self.keeper)

        response = self.client.post(reverse("transfer_submit", args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PENDING)

    def test_create_and_submit_in_one_action(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("outbound_create"),
            {
                "action": "submit",
                "outbound_type": OutboundOrder.OutboundType.PICK,
                "herb": self.herb.pk,
                "batch_no": "HQ20260901",
                "location": self.loc_a.pk,
                "quantity": "5",
                "recipient": "制剂室",
                "purpose": "试制",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = OutboundOrder.objects.get()
        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertIsNotNone(order.submitted_at)

    def test_other_keeper_cannot_submit_someone_elses_draft(self):
        order = self.make_transfer(applicant=self.keeper2)
        self.client.force_login(self.keeper)
        response = self.client.post(reverse("transfer_submit", args=[order.pk]))
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DRAFT)

    def test_manager_can_approve_and_keeper_cannot(self):
        order = self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("transfer_approve", args=[order.pk]), {"comment": "同意"}
        )
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("transfer_approve", args=[order.pk]), {"comment": "同意执行"}
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.APPROVED)
        self.assertEqual(order.auditor, self.manager)

    def test_reject_without_comment_does_not_change_status(self):
        order = self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("transfer_reject", args=[order.pk]), {"comment": ""}
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertFalse(
            OrderStatusLog.for_order(order)
            .filter(action=OrderStatusLog.Action.REJECT)
            .exists()
        )

    def test_keeper_completes_approved_transfer(self):
        order = self.make_transfer(status=OrderStatus.APPROVED)
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("transfer_complete", args=[order.pk]), {"comment": "已核对"}
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertEqual(self.batch.quantity, Decimal("90"))

    def test_manager_cannot_execute_stock_operation(self):
        order = self.make_transfer(status=OrderStatus.APPROVED)
        self.client.force_login(self.manager)
        response = self.client.post(reverse("transfer_complete", args=[order.pk]))
        self.assertEqual(response.status_code, 403)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, Decimal("100"))

    def test_viewer_cannot_annotate_or_upload(self):
        order = self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.viewer)
        response = self.client.post(
            reverse("transfer_exception", args=[order.pk]), {"note": "越权备注"}
        )
        self.assertEqual(response.status_code, 403)

        upload = SimpleUploadedFile("x.png", b"fake-image", content_type="image/png")
        response = self.client.post(
            reverse("transfer_attachment_upload", args=[order.pk]),
            {"file": upload, "note": "越权附件"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(OrderAttachment.objects.count(), 0)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AttachmentTests(WarehouseTestBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_valid_attachment_upload_creates_log(self):
        order = self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.keeper)
        upload = SimpleUploadedFile(
            "handover.png",
            b"\x89PNG\r\n\x1a\n" + b"0" * 128,
            content_type="image/png",
        )
        response = self.client.post(
            reverse("transfer_attachment_upload", args=[order.pk]),
            {"file": upload, "note": "交接单"},
        )
        self.assertEqual(response.status_code, 302)
        attachment = OrderAttachment.objects.get()
        self.assertEqual(attachment.transfer, order)
        self.assertEqual(attachment.original_name, "handover.png")
        self.assertTrue(
            OrderStatusLog.for_order(order)
            .filter(action=OrderStatusLog.Action.ATTACH)
            .exists()
        )

    def test_invalid_extension_is_rejected(self):
        order = self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.keeper)
        upload = SimpleUploadedFile(
            "payload.exe", b"MZ" + b"0" * 64, content_type="application/octet-stream"
        )
        response = self.client.post(
            reverse("transfer_attachment_upload", args=[order.pk]),
            {"file": upload, "note": "非法文件"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(OrderAttachment.objects.count(), 0)

    def test_attachment_upload_on_other_order_type(self):
        order = self.make_outbound(status=OrderStatus.APPROVED)
        self.client.force_login(self.keeper)
        upload = SimpleUploadedFile(
            "outbound.pdf", b"%PDF-1.4 test", content_type="application/pdf"
        )
        response = self.client.post(
            reverse("outbound_attachment_upload", args=[order.pk]),
            {"file": upload, "note": "出库复核单"},
        )
        self.assertEqual(response.status_code, 302)
        attachment = OrderAttachment.objects.get()
        self.assertEqual(attachment.outbound, order)
        self.assertIsNone(attachment.transfer)

    def test_completed_order_attachment_delete_is_manager_only(self):
        order = self.make_transfer(status=OrderStatus.COMPLETED)
        attachment = OrderAttachment.objects.create(
            transfer=order,
            file="demo/old.png",
            original_name="old.png",
            uploaded_by=self.keeper,
        )
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("attachment_delete", args=[attachment.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(OrderAttachment.objects.filter(pk=attachment.pk).exists())

        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("attachment_delete", args=[attachment.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(OrderAttachment.objects.filter(pk=attachment.pk).exists())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ListFilterAndDetailTests(WarehouseTestBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_dashboard_counts_and_content(self):
        self.make_transfer(status=OrderStatus.PENDING)
        self.make_outbound(status=OrderStatus.APPROVED)
        self.client.force_login(self.manager)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pending_total"], 1)
        self.assertEqual(response.context["approved_total"], 1)
        self.assertContains(response, "入库有验，移出有据")

    def test_status_filter_and_keyword_search(self):
        pending = self.make_transfer(status=OrderStatus.PENDING)
        draft = self.make_transfer(status=OrderStatus.DRAFT)
        self.client.force_login(self.keeper)

        response = self.client.get(reverse("transfer_list"), {"status": "pending"})
        self.assertEqual(list(response.context["orders"]), [pending])

        response = self.client.get(reverse("transfer_list"), {"q": "黄芪"})
        self.assertEqual(len(response.context["orders"]), 2)

        response = self.client.get(reverse("transfer_list"), {"q": "不存在的药材"})
        self.assertEqual(len(response.context["orders"]), 0)

    def test_date_filter(self):
        order = self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.keeper)
        today = order.created_at.date().isoformat()
        response = self.client.get(
            reverse("transfer_list"),
            {"date_from": today, "date_to": today},
        )
        self.assertEqual(len(response.context["orders"]), 1)

        response = self.client.get(
            reverse("transfer_list"),
            {"date_from": "2099-01-01", "date_to": "2099-12-31"},
        )
        self.assertEqual(len(response.context["orders"]), 0)

    def test_detail_flags_by_role(self):
        order = self.make_transfer(status=OrderStatus.PENDING)
        self.client.force_login(self.manager)
        response = self.client.get(reverse("transfer_detail", args=[order.pk]))
        self.assertTrue(response.context["can_review"])
        self.assertFalse(response.context["can_complete"])

        self.client.force_login(self.keeper)
        response = self.client.get(reverse("transfer_detail", args=[order.pk]))
        self.assertFalse(response.context["can_review"])
        self.assertFalse(response.context["can_complete"])

    def test_keeper_can_delete_own_draft_only(self):
        order = self.make_transfer(status=OrderStatus.DRAFT)
        self.client.force_login(self.keeper)
        response = self.client.post(reverse("transfer_delete", args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TransferOrder.objects.filter(pk=order.pk).exists())

        submitted = self.make_transfer(status=OrderStatus.PENDING)
        response = self.client.post(reverse("transfer_delete", args=[submitted.pk]))
        self.assertEqual(response.status_code, 403)

    def test_stock_batches_api_returns_available_batches(self):
        self.client.force_login(self.keeper)
        response = self.client.get(
            reverse("stock_batches_api"),
            {"herb": self.herb.pk, "location": self.loc_a.pk},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], "100.000")
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["batch_no"], "HQ20260901")

    def test_stock_batches_api_requires_login(self):
        response = self.client.get(reverse("stock_batches_api"))
        self.assertEqual(response.status_code, 302)

    def test_not_found_order_returns_404(self):
        self.client.force_login(self.keeper)
        response = self.client.get(reverse("transfer_detail", args=[99999]))
        self.assertEqual(response.status_code, 404)
