from decimal import Decimal

from warehouse.models import (
    OrderAttachment,
    OrderStatus,
    StockMovement,
)

from .base import WarehouseTestBase


class ModelBehaviorTests(WarehouseTestBase):
    def test_order_numbers_are_generated_with_prefix(self):
        transfer = self.make_transfer()
        outbound = self.make_outbound()
        self.assertTrue(transfer.transfer_no.startswith("YK"))
        self.assertTrue(outbound.outbound_no.startswith("CK"))
        self.assertGreater(len(transfer.transfer_no), 16)
        self.assertNotEqual(transfer.transfer_no, self.make_transfer().transfer_no)

    def test_status_tone_mapping(self):
        self.assertEqual(self.make_transfer(status=OrderStatus.PENDING).status_tone, "warning")
        self.assertEqual(self.make_transfer(status=OrderStatus.COMPLETED).status_tone, "success")
        self.assertEqual(self.make_transfer(status=OrderStatus.REJECTED).status_tone, "danger")

    def test_low_stock_flag_uses_safety_stock(self):
        self.batch.refresh_from_db()
        self.assertFalse(self.batch.is_low_stock)
        self.batch.quantity = Decimal("10")
        self.batch.save(update_fields=["quantity"])
        self.assertTrue(self.batch.is_low_stock)

    def test_stock_movement_signed_quantity(self):
        movement = StockMovement(
            movement_type=StockMovement.MovementType.TRANSFER_IN,
            quantity=Decimal("8"),
            before_quantity=Decimal("1"),
            after_quantity=Decimal("9"),
        )
        self.assertTrue(movement.is_increase)
        self.assertEqual(movement.signed_quantity, Decimal("8"))

        movement.movement_type = StockMovement.MovementType.TRANSFER_OUT
        self.assertFalse(movement.is_increase)
        self.assertEqual(movement.signed_quantity, Decimal("-8"))

    def test_role_flags(self):
        self.assertTrue(self.keeper.profile.can_create)
        self.assertTrue(self.keeper.profile.can_execute)
        self.assertFalse(self.keeper.profile.can_audit)
        self.assertTrue(self.manager.profile.can_audit)
        self.assertFalse(self.manager.profile.can_create)
        self.assertFalse(self.viewer.profile.can_create)
        self.assertFalse(self.viewer.profile.can_audit)
        self.assertFalse(self.viewer.profile.can_execute)

    def test_attachment_label_methods(self):
        attachment = OrderAttachment(
            transfer=self.make_transfer(),
            file="demo/handover.png",
            original_name="handover.png",
            uploaded_by=self.keeper,
        )
        self.assertTrue(attachment.is_image)
        self.assertEqual(attachment.original_name, "handover.png")
