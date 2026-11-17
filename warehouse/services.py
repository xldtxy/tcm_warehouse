"""入库、移库、出库单的业务规则与库存联动。

所有会改变库存的动作都放在 transaction.atomic() 中，并用 select_for_update()
锁定库存行，避免并发确认时超卖、重复扣减或重复入库。
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    InboundOrder,
    OrderStatus,
    OrderStatusLog,
    OutboundOrder,
    StockBatch,
    StockMovement,
    TransferOrder,
)
from .permissions import can_cancel


class WorkflowError(Exception):
    """可直接展示给用户的业务规则错误。"""


def _now():
    return timezone.now()


def _qty(value):
    return f"{Decimal(value):.3f}".rstrip("0").rstrip(".")


def _reload_locked(order):
    return type(order).objects.select_for_update().get(pk=order.pk)


def _validate_stock_available(order):
    available = order.available_quantity
    if available < order.quantity:
        raise WorkflowError(
            f"可用库存不足：当前 {_qty(available)}，本单需要 {_qty(order.quantity)}。"
            "请先补货、调整数量，或在异常备注中说明处理方案。"
        )
    return available


@transaction.atomic
def submit_order(order, user):
    """草稿/已驳回 → 待审核。提交时先做一次库存预检。"""
    order = _reload_locked(order)
    if not order.can_submit:
        raise WorkflowError("只有草稿或已驳回的单据可以提交审核。")
    if order.quantity <= 0:
        raise WorkflowError("数量必须大于 0。")
    if isinstance(order, TransferOrder) and order.from_location_id == order.to_location_id:
        raise WorkflowError("移出库位和移入库位不能相同。")
    if (
        isinstance(order, TransferOrder)
        and order.from_location.warehouse_id != order.to_location.warehouse_id
    ):
        raise WorkflowError("移库单只能在同一个仓库内的库位之间移动。")
    _validate_stock_available(order)

    old_status = order.status
    order.status = OrderStatus.PENDING
    order.submitted_at = _now()
    order.review_comment = ""
    order.auditor = None
    order.audited_at = None
    order.save(
        update_fields=[
            "status",
            "submitted_at",
            "review_comment",
            "auditor",
            "audited_at",
            "updated_at",
        ]
    )
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.SUBMIT,
        user,
        comment="提交审核，库存预检通过。",
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def approve_order(order, user, comment=""):
    """待审核 → 已审核（表示允许执行，尚未扣减库存）。"""
    order = _reload_locked(order)
    if not order.can_audit:
        raise WorkflowError("当前单据不在待审核状态，不能重复审核。")
    if order.applicant_id == user.id and not user.is_superuser:
        raise WorkflowError("制单人与审核人不能为同一人。")

    old_status = order.status
    order.status = OrderStatus.APPROVED
    order.auditor = user
    order.audited_at = _now()
    order.review_comment = comment.strip()
    order.save(
        update_fields=[
            "status",
            "auditor",
            "audited_at",
            "review_comment",
            "updated_at",
        ]
    )
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.APPROVE,
        user,
        comment=comment or "审核通过。",
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def reject_order(order, user, comment):
    """待审核 → 已驳回，必须填写驳回原因。"""
    order = _reload_locked(order)
    if not order.can_audit:
        raise WorkflowError("当前单据不在待审核状态，不能驳回。")
    comment = (comment or "").strip()
    if len(comment) < 2:
        raise WorkflowError("驳回时必须填写至少 2 个字的审核意见。")

    old_status = order.status
    order.status = OrderStatus.REJECTED
    order.auditor = user
    order.audited_at = _now()
    order.review_comment = comment
    order.save(
        update_fields=[
            "status",
            "auditor",
            "audited_at",
            "review_comment",
            "updated_at",
        ]
    )
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.REJECT,
        user,
        comment=comment,
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def complete_transfer(order, user, comment=""):
    """已审核 → 已完成：锁定源库存，扣减源库位并增加目标库位。"""
    order = _reload_locked(order)
    if not order.can_complete:
        raise WorkflowError("只有已审核的移库单可以确认完成。")
    if order.from_location_id == order.to_location_id:
        raise WorkflowError("移出库位和移入库位相同，无法执行。")
    if order.from_location.warehouse_id != order.to_location.warehouse_id:
        raise WorkflowError("移库单只能在同一仓库内执行，请检查库位归属。")

    source = (
        StockBatch.objects.select_for_update()
        .filter(
            herb=order.herb,
            location=order.from_location,
            batch_no=order.batch_no,
        )
        .first()
    )
    if source is None or source.quantity < order.quantity:
        available = source.quantity if source else Decimal("0")
        raise WorkflowError(
            f"源库位库存不足：当前 {_qty(available)}，本单需要 {_qty(order.quantity)}。"
            "库存可能已被其他单据占用，请调整后重试。"
        )

    destination = (
        StockBatch.objects.select_for_update()
        .filter(
            herb=order.herb,
            location=order.to_location,
            batch_no=order.batch_no,
        )
        .first()
    )
    if destination is None:
        destination = StockBatch(
            herb=order.herb,
            location=order.to_location,
            batch_no=order.batch_no,
            quantity=Decimal("0"),
            production_date=source.production_date,
            expiry_date=source.expiry_date,
        )

    source_before = source.quantity
    source.quantity = source_before - order.quantity
    source.save(update_fields=["quantity", "updated_at"])
    StockMovement.objects.create(
        batch=source,
        movement_type=StockMovement.MovementType.TRANSFER_OUT,
        quantity=order.quantity,
        before_quantity=source_before,
        after_quantity=source.quantity,
        order_type=StockMovement.OrderType.TRANSFER,
        order_no=order.transfer_no,
        order_id=order.pk,
        operator=user,
        remark=f"移库至 {order.to_location.code}",
    )

    destination_before = destination.quantity
    destination.quantity = destination_before + order.quantity
    destination.save()
    StockMovement.objects.create(
        batch=destination,
        movement_type=StockMovement.MovementType.TRANSFER_IN,
        quantity=order.quantity,
        before_quantity=destination_before,
        after_quantity=destination.quantity,
        order_type=StockMovement.OrderType.TRANSFER,
        order_no=order.transfer_no,
        order_id=order.pk,
        operator=user,
        remark=f"由 {order.from_location.code} 移入",
    )

    old_status = order.status
    order.status = OrderStatus.COMPLETED
    order.completed_at = _now()
    order.save(update_fields=["status", "completed_at", "updated_at"])
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.COMPLETE,
        user,
        comment=(
            f"移库完成：{order.from_location.code} → {order.to_location.code}，"
            f"数量 {_qty(order.quantity)}。"
            + (f" 执行说明：{comment.strip()}" if (comment or "").strip() else "")
        )[:500],
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def complete_outbound(order, user, comment=""):
    """已审核 → 已完成：锁定库存并扣减，写库存流水。"""
    order = _reload_locked(order)
    if not order.can_complete:
        raise WorkflowError("只有已审核的出库单可以确认出库。")

    batch = (
        StockBatch.objects.select_for_update()
        .filter(
            herb=order.herb,
            location=order.location,
            batch_no=order.batch_no,
        )
        .first()
    )
    if batch is None or batch.quantity < order.quantity:
        available = batch.quantity if batch else Decimal("0")
        raise WorkflowError(
            f"出库库位库存不足：当前 {_qty(available)}，本单需要 {_qty(order.quantity)}。"
            "请联系主管调整单据或补充库存。"
        )

    before = batch.quantity
    batch.quantity = before - order.quantity
    batch.save(update_fields=["quantity", "updated_at"])
    StockMovement.objects.create(
        batch=batch,
        movement_type=StockMovement.MovementType.OUTBOUND,
        quantity=order.quantity,
        before_quantity=before,
        after_quantity=batch.quantity,
        order_type=StockMovement.OrderType.OUTBOUND,
        order_no=order.outbound_no,
        order_id=order.pk,
        operator=user,
        remark=f"{order.get_outbound_type_display()} / {order.recipient}",
    )

    old_status = order.status
    order.status = OrderStatus.COMPLETED
    order.completed_at = _now()
    order.save(update_fields=["status", "completed_at", "updated_at"])
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.COMPLETE,
        user,
        comment=(
            f"出库完成：{order.location.code} 扣减 {_qty(order.quantity)}，"
            f"领用/去向：{order.recipient}。"
            + (f" 执行说明：{comment.strip()}" if (comment or "").strip() else "")
        )[:500],
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def submit_inbound(order, user):
    """入库单草稿/驳回单 → 待验收，至少一条有效明细。"""
    order = _reload_locked(order)
    if not order.can_submit:
        raise WorkflowError("只有草稿或已驳回的入库单可以提交验收。")
    items = list(order.items.select_related("herb", "location", "location__warehouse"))
    if not items:
        raise WorkflowError("入库单至少需要一条明细。")
    for item in items:
        if item.quantity <= 0:
            raise WorkflowError(f"{item.herb.name} 的入库数量必须大于 0。")
        if item.location.warehouse_id != order.warehouse_id:
            raise WorkflowError(
                f"{item.herb.name} 的入库库位不属于所选仓库，请修正明细。"
            )
        if not item.batch_no.strip():
            raise WorkflowError(f"{item.herb.name} 缺少批次号。")

    old_status = order.status
    order.status = OrderStatus.PENDING
    order.submitted_at = _now()
    order.review_comment = ""
    order.auditor = None
    order.audited_at = None
    order.save(
        update_fields=[
            "status",
            "submitted_at",
            "review_comment",
            "auditor",
            "audited_at",
            "updated_at",
        ]
    )
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.SUBMIT,
        user,
        comment=f"提交验收，共 {len(items)} 条明细，合计 {_qty(order.total_quantity)}。",
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def complete_inbound(order, user, comment=""):
    """验收通过 → 已入库：逐条锁定/创建库存批次、增加库存并写入库流水。"""
    order = _reload_locked(order)
    if not order.can_complete:
        raise WorkflowError("只有验收通过的入库单可以确认入库。")
    items = list(order.items.select_related("herb", "location", "location__warehouse"))
    if not items:
        raise WorkflowError("入库单没有明细，无法入库。")

    for item in items:
        if item.location.warehouse_id != order.warehouse_id:
            raise WorkflowError("存在不属于入库仓库的库位，已阻止入库。")
        batch = (
            StockBatch.objects.select_for_update()
            .filter(
                herb=item.herb,
                location=item.location,
                batch_no=item.batch_no,
            )
            .first()
        )
        if batch is None:
            batch = StockBatch(
                herb=item.herb,
                location=item.location,
                batch_no=item.batch_no,
                quantity=Decimal("0"),
                production_date=item.production_date,
                expiry_date=item.expiry_date,
            )
        before = batch.quantity
        batch.quantity = before + item.quantity
        if item.production_date and not batch.production_date:
            batch.production_date = item.production_date
        if item.expiry_date:
            batch.expiry_date = item.expiry_date
        batch.save()
        StockMovement.objects.create(
            batch=batch,
            movement_type=StockMovement.MovementType.INBOUND,
            quantity=item.quantity,
            before_quantity=before,
            after_quantity=batch.quantity,
            order_type=StockMovement.OrderType.INBOUND,
            order_no=order.inbound_no,
            order_id=order.pk,
            operator=user,
            remark=f"{order.supplier.name} / {order.invoice_no or '随货同行'}",
        )

    old_status = order.status
    order.status = OrderStatus.COMPLETED
    order.completed_at = _now()
    order.save(update_fields=["status", "completed_at", "updated_at"])
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.COMPLETE,
        user,
        comment=(
            f"验收入库完成：{order.warehouse.name}，{len(items)} 条明细，"
            f"合计 {_qty(order.total_quantity)}。"
            + (f" 说明：{comment.strip()}" if (comment or "").strip() else "")
        )[:500],
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def cancel_order(order, user, reason=""):
    """未完成单据 → 已取消；主管和管理员可撤销，申请人仅可撤销自己的草稿/待审核单。"""
    order = _reload_locked(order)
    if not can_cancel(user, order):
        raise WorkflowError("当前岗位无权取消该单据，或单据已结束。")

    old_status = order.status
    order.status = OrderStatus.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.CANCEL,
        user,
        comment=(reason or "取消单据。").strip()[:500],
        from_status=old_status,
        to_status=order.status,
    )
    return order


@transaction.atomic
def adjust_stock(batch, user, new_quantity, reason):
    """库存盘点调整：不直接改数量，而是生成 ADJUST 流水保留差异。"""
    batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
    new_quantity = Decimal(new_quantity)
    if new_quantity < 0:
        raise WorkflowError("库存数量不能小于 0。")
    reason = (reason or "").strip()
    if len(reason) < 2:
        raise WorkflowError("库存调整必须填写至少 2 个字的调整原因。")
    if new_quantity == batch.quantity:
        raise WorkflowError("新库存与当前库存相同，无需调整。")

    before = batch.quantity
    diff = new_quantity - before
    batch.quantity = new_quantity
    batch.save(update_fields=["quantity", "updated_at"])
    StockMovement.objects.create(
        batch=batch,
        movement_type=StockMovement.MovementType.ADJUST,
        quantity=abs(diff),
        before_quantity=before,
        after_quantity=new_quantity,
        order_type=StockMovement.OrderType.MANUAL,
        order_no="",
        operator=user,
        remark=reason[:300],
    )
    return batch


@transaction.atomic
def record_exception(order, user, note):
    """追加异常备注，不改变单据状态。"""
    order = _reload_locked(order)
    note = (note or "").strip()
    if len(note) < 2:
        raise WorkflowError("异常备注至少填写 2 个字。")
    if order.status in {OrderStatus.CANCELLED}:
        raise WorkflowError("已取消的单据不再追加异常备注。")

    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    name = user.get_full_name() or user.username
    entry = f"[{stamp} {name}] {note}"
    order.exception_note = (
        f"{order.exception_note}\n{entry}".strip() if order.exception_note else entry
    )
    order.save(update_fields=["exception_note", "updated_at"])
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.EXCEPTION,
        user,
        comment=note[:500],
        from_status=order.status,
        to_status=order.status,
    )
    return order

