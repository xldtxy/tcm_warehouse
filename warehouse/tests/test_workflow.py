from decimal import Decimal

from warehouse.models import (
    OrderAttachment,
    OrderStatus,
    OrderStatusLog,
    StockBatch,
    StockMovement,
)
from warehouse.services import (
    WorkflowError,
    approve_order,
    cancel_order,
    complete_outbound,
    complete_transfer,
    record_exception,
    reject_order,
    submit_order,
)

from .base import WarehouseTestBase


class SubmitAndReviewTests(WarehouseTestBase):
    def test_submit_moves_draft_to_pending_and_records_log(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        order.refresh_from_db()

        self.assertEqual(order.status, OrderStatus.PENDING)
        self.assertIsNotNone(order.submitted_at)
        self.assertTrue(
            OrderStatusLog.for_order(order)
            .filter(action=OrderStatusLog.Action.SUBMIT)
            .exists()
        )

    def test_submit_blocks_when_stock_is_insufficient(self):
        order = self.make_transfer(quantity="101")
        with self.assertRaisesMessage(WorkflowError, "可用库存不足"):
            submit_order(order, self.keeper)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DRAFT)

    def test_submit_blocks_same_source_and_target(self):
        order = self.make_transfer(to_location=self.loc_a)
        with self.assertRaisesMessage(WorkflowError, "不能相同"):
            submit_order(order, self.keeper)

    def test_submit_blocks_cross_warehouse_transfer(self):
        from warehouse.models import StorageLocation, Warehouse

        other_warehouse = Warehouse.objects.create(code="WH02", name="城南分仓")
        other_location = StorageLocation.objects.create(
            warehouse=other_warehouse, code="E-01", name="分仓库位"
        )
        order = self.make_transfer(to_location=other_location)
        with self.assertRaisesMessage(WorkflowError, "同一个仓库"):
            submit_order(order, self.keeper)

    def test_approve_by_manager(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        approve_order(order, self.manager, "核对无误，同意执行。")
        order.refresh_from_db()

        self.assertEqual(order.status, OrderStatus.APPROVED)
        self.assertEqual(order.auditor, self.manager)
        self.assertEqual(order.review_comment, "核对无误，同意执行。")
        self.assertIsNotNone(order.audited_at)

    def test_self_review_is_rejected(self):
        order = self.make_transfer(applicant=self.manager)
        submit_order(order, self.manager)
        with self.assertRaisesMessage(WorkflowError, "不能为同一人"):
            approve_order(order, self.manager, "自己审自己")

    def test_reject_requires_reason_and_sets_status(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        with self.assertRaises(WorkflowError):
            reject_order(order, self.manager, " ")
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PENDING)

        reject_order(order, self.manager, "批次与实物不一致，请核对。")
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertIn("批次", order.review_comment)

    def test_cannot_approve_twice(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        approve_order(order, self.manager)
        with self.assertRaises(WorkflowError):
            approve_order(order, self.manager)


class CompleteTransferTests(WarehouseTestBase):
    def _approved_transfer(self, quantity="10", to_location=None):
        order = self.make_transfer(quantity=quantity, to_location=to_location)
        submit_order(order, self.keeper)
        approve_order(order, self.manager)
        return order

    def test_complete_transfer_moves_stock_and_keeps_total(self):
        source = StockBatch.objects.get(pk=self.batch.pk)
        destination = StockBatch.objects.get(pk=self.batch_b.pk)
        total_before = source.quantity + destination.quantity
        order = self._approved_transfer("15")

        complete_transfer(order, self.keeper, "实物核对无误")
        order.refresh_from_db()
        source.refresh_from_db()
        destination.refresh_from_db()

        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertIsNotNone(order.completed_at)
        self.assertEqual(source.quantity, Decimal("85"))
        self.assertEqual(destination.quantity, Decimal("25"))
        self.assertEqual(source.quantity + destination.quantity, total_before)
        self.assertEqual(
            StockMovement.objects.filter(order_no=order.transfer_no).count(), 2
        )
        self.assertTrue(
            OrderStatusLog.for_order(order)
            .filter(action=OrderStatusLog.Action.COMPLETE)
            .exists()
        )

    def test_complete_transfer_creates_destination_batch_with_dates(self):
        order = self._approved_transfer("7", to_location=self.loc_c)
        complete_transfer(order, self.keeper)

        destination = StockBatch.objects.get(
            herb=self.herb, location=self.loc_c, batch_no="HQ20260901"
        )
        self.assertEqual(destination.quantity, Decimal("7"))
        self.assertEqual(destination.production_date, self.batch.production_date)
        self.assertEqual(destination.expiry_date, self.batch.expiry_date)

    def test_complete_transfer_rolls_back_when_stock_changed(self):
        order = self._approved_transfer("80")
        StockBatch.objects.filter(pk=self.batch.pk).update(quantity=Decimal("5"))

        with self.assertRaisesMessage(WorkflowError, "源库位库存不足"):
            complete_transfer(order, self.keeper)

        order.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.APPROVED)
        self.assertEqual(self.batch.quantity, Decimal("5"))
        self.assertFalse(
            StockMovement.objects.filter(order_no=order.transfer_no).exists()
        )

    def test_complete_transfer_is_idempotent_guarded(self):
        order = self._approved_transfer("10")
        complete_transfer(order, self.keeper)
        with self.assertRaises(WorkflowError):
            complete_transfer(order, self.keeper)
        self.assertEqual(
            StockMovement.objects.filter(order_no=order.transfer_no).count(), 2
        )

    def test_stock_cannot_go_negative(self):
        order = self._approved_transfer("100")
        complete_transfer(order, self.keeper)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, Decimal("0"))

        second = self.make_transfer(quantity="1", status=OrderStatus.APPROVED)
        with self.assertRaises(WorkflowError):
            complete_transfer(second, self.keeper)


class CompleteOutboundTests(WarehouseTestBase):
    def _approved_outbound(self, quantity="10"):
        order = self.make_outbound(quantity=quantity)
        submit_order(order, self.keeper)
        approve_order(order, self.manager)
        return order

    def test_complete_outbound_deducts_stock_and_writes_movement(self):
        order = self._approved_outbound("12")
        complete_outbound(order, self.keeper, "交接人张医师")
        order.refresh_from_db()
        self.batch.refresh_from_db()

        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertEqual(self.batch.quantity, Decimal("88"))
        movement = StockMovement.objects.get(order_no=order.outbound_no)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUTBOUND)
        self.assertEqual(movement.before_quantity, Decimal("100"))
        self.assertEqual(movement.after_quantity, Decimal("88"))
        complete_log = OrderStatusLog.for_order(order).get(
            action=OrderStatusLog.Action.COMPLETE
        )
        self.assertIn("张医师", complete_log.comment)

    def test_complete_outbound_insufficient_stock_rolls_back(self):
        order = self._approved_outbound("90")
        StockBatch.objects.filter(pk=self.batch.pk).update(quantity=Decimal("20"))
        with self.assertRaisesMessage(WorkflowError, "库存不足"):
            complete_outbound(order, self.keeper)
        order.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.APPROVED)
        self.assertEqual(self.batch.quantity, Decimal("20"))
        self.assertFalse(StockMovement.objects.filter(order_no=order.outbound_no).exists())


class CancelAndExceptionTests(WarehouseTestBase):
    def test_applicant_can_cancel_own_pending_order(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        cancel_order(order, self.keeper, "计划调整")
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertTrue(
            OrderStatusLog.for_order(order)
            .filter(action=OrderStatusLog.Action.CANCEL)
            .exists()
        )

    def test_other_keeper_cannot_cancel(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        with self.assertRaises(WorkflowError):
            cancel_order(order, self.keeper2, "越权取消")

    def test_manager_can_cancel_approved_order(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        approve_order(order, self.manager)
        cancel_order(order, self.manager, "需求取消")
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)

    def test_exception_note_appends_with_operator_and_log(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        record_exception(order, self.keeper, "库位临时占用，等待调整。")
        record_exception(order, self.manager, "已协调至 B-02，明日执行。")
        order.refresh_from_db()

        self.assertIn("库位临时占用", order.exception_note)
        self.assertIn("已协调至 B-02", order.exception_note)
        self.assertIn("陈远志", order.exception_note)
        self.assertEqual(
            OrderStatusLog.for_order(order)
            .filter(action=OrderStatusLog.Action.EXCEPTION)
            .count(),
            2,
        )

    def test_exception_on_cancelled_order_is_blocked(self):
        order = self.make_transfer()
        cancel_order(order, self.keeper)
        with self.assertRaises(WorkflowError):
            record_exception(order, self.keeper, "补充说明")

    def test_exception_allowed_after_completion(self):
        order = self.make_transfer()
        submit_order(order, self.keeper)
        approve_order(order, self.manager)
        complete_transfer(order, self.keeper)
        record_exception(order, self.manager, "事后发现外包装轻微破损，已登记。")
        order.refresh_from_db()
        self.assertIn("外包装", order.exception_note)


class AttachmentAndLogTests(WarehouseTestBase):
    def test_attachment_requires_exactly_one_parent(self):
        attachment = OrderAttachment(
            file="demo/test.pdf",
            original_name="test.pdf",
            uploaded_by=self.keeper,
        )
        with self.assertRaisesMessage(Exception, "必须且只能关联"):
            attachment.clean()

    def test_attachment_cannot_link_both_orders(self):
        transfer = self.make_transfer()
        outbound = self.make_outbound()
        attachment = OrderAttachment(
            transfer=transfer,
            outbound=outbound,
            file="demo/test.pdf",
            original_name="test.pdf",
            uploaded_by=self.keeper,
        )
        with self.assertRaisesMessage(Exception, "必须且只能关联"):
            attachment.clean()

    def test_logs_are_isolated_by_order_type(self):
        transfer = self.make_transfer()
        outbound = self.make_outbound()
        OrderStatusLog.record(
            transfer, OrderStatusLog.Action.CREATE, self.keeper, from_status="", to_status="draft"
        )
        OrderStatusLog.record(
            outbound, OrderStatusLog.Action.CREATE, self.keeper, from_status="", to_status="draft"
        )
        self.assertEqual(OrderStatusLog.for_order(transfer).count(), 1)
        self.assertEqual(OrderStatusLog.for_order(outbound).count(), 1)
        self.assertEqual(OrderStatusLog.objects.count(), 2)
