"""学生 3：入库单、入库明细与验收入库状态流转。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import CancelForm, InboundItemFormSet, InboundOrderForm, RejectForm, ReviewForm
from .models import (
    InboundOrder,
    OrderStatus,
    OrderStatusLog,
    Supplier,
    UserProfile,
)
from .permissions import can_cancel, can_edit, has_perm
from .services import (
    WorkflowError,
    approve_order,
    cancel_order,
    complete_inbound,
    reject_order,
    submit_inbound,
)

STATUS_CHOICES = list(OrderStatus.choices)


def _require(user, code):
    if not has_perm(user, code):
        raise PermissionDenied("当前岗位没有该功能权限。")


def _base_queryset():
    return InboundOrder.objects.select_related(
        "supplier", "warehouse", "applicant", "applicant__profile", "auditor"
    )


def _status_counts(queryset):
    counts = {value: 0 for value, _label in STATUS_CHOICES}
    for row in queryset.values("status").annotate(total=Count("id")):
        counts[row["status"]] = row["total"]
    return counts


def _status_tabs(counts, current):
    labels = dict(STATUS_CHOICES)
    labels[OrderStatus.PENDING] = "待验收"
    labels[OrderStatus.APPROVED] = "验收通过"
    return [
        {
            "value": value,
            "label": labels[value],
            "count": counts.get(value, 0),
            "active": current == value,
        }
        for value, _label in STATUS_CHOICES
    ]


@login_required
def inbound_list(request):
    _require(request.user, "inbound.view")
    base = _base_queryset()
    counts = _status_counts(base)
    qs = base
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    supplier_id = (request.GET.get("supplier") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    errors = []
    if q:
        qs = qs.filter(
            Q(inbound_no__icontains=q)
            | Q(supplier__name__icontains=q)
            | Q(invoice_no__icontains=q)
            | Q(items__herb__name__icontains=q)
            | Q(items__batch_no__icontains=q)
        ).distinct()
    if status in dict(STATUS_CHOICES):
        qs = qs.filter(status=status)
    else:
        status = ""
    if supplier_id.isdigit():
        qs = qs.filter(supplier_id=int(supplier_id))
    try:
        if date_from:
            qs = qs.filter(inbound_date__gte=date.fromisoformat(date_from))
        if date_to:
            qs = qs.filter(inbound_date__lte=date.fromisoformat(date_to))
    except ValueError:
        errors.append("日期格式应为 YYYY-MM-DD。")
    page_obj = Paginator(qs.order_by("-created_at", "-id"), 12).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "warehouse/inbound_list.html",
        {
            "page_obj": page_obj,
            "orders": page_obj.object_list,
            "counts": counts,
            "total_count": sum(counts.values()),
            "status_tabs": _status_tabs(counts, status),
            "suppliers": Supplier.objects.filter(is_active=True),
            "filters": {
                "q": q,
                "status": status,
                "supplier": supplier_id,
                "date_from": date_from,
                "date_to": date_to,
                "errors": errors,
                "has_filters": bool(q or status or supplier_id or date_from or date_to),
            },
            "can_create": has_perm(request.user, "inbound.create"),
            "active_nav": "inbound",
        },
    )


def _save_order(request, form, formset, instance=None):
    """保存表头与明细，返回 (order, success)。"""
    order = form.save(commit=False)
    if instance is None:
        order.applicant = request.user
        order.status = OrderStatus.DRAFT
    elif order.status == OrderStatus.REJECTED:
        order.status = OrderStatus.DRAFT
    order.save()
    for item_form in formset.forms:
        if getattr(item_form, "instance", None) is not None:
            item_form.instance.order = order
    formset.instance = order
    formset.save()
    return order


@login_required
def inbound_create(request):
    _require(request.user, "inbound.create")
    instance = InboundOrder()
    form = InboundOrderForm(request.POST or None, instance=instance)
    formset = InboundItemFormSet(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        warehouse = form.cleaned_data["warehouse"]
        errors = False
        seen = set()
        for item_form in formset.forms:
            data = getattr(item_form, "cleaned_data", None)
            if not data or data.get("DELETE"):
                continue
            location = data.get("location")
            herb = data.get("herb")
            batch_no = (data.get("batch_no") or "").strip()
            if location and location.warehouse_id != warehouse.pk:
                item_form.add_error("location", "该库位不属于所选入库仓库。")
                errors = True
            key = (herb.pk if herb else None, batch_no, location.pk if location else None)
            if key in seen:
                item_form.add_error("batch_no", "同一药材/批次/库位在单据中重复。")
                errors = True
            seen.add(key)
        if not errors:
            with transaction.atomic():
                order = _save_order(request, form, formset)
                OrderStatusLog.record(
                    order,
                    OrderStatusLog.Action.CREATE,
                    request.user,
                    comment="创建入库单草稿。",
                    from_status="",
                    to_status=order.status,
                )
            if request.POST.get("action") == "submit":
                try:
                    submit_inbound(order, request.user)
                    messages.success(request, "入库单已保存并提交验收。")
                except WorkflowError as exc:
                    messages.warning(request, f"草稿已保存，但提交验收失败：{exc}")
            else:
                messages.success(request, f"入库单 {order.inbound_no} 已保存为草稿。")
            return redirect("inbound_detail", pk=order.pk)
    return render(
        request,
        "warehouse/inbound_form.html",
        {
            "form": form,
            "formset": formset,
            "is_create": True,
            "active_nav": "inbound",
        },
    )


@login_required
def inbound_edit(request, pk):
    _require(request.user, "inbound.create")
    order = get_object_or_404(_base_queryset(), pk=pk)
    if not can_edit(request.user, order):
        raise PermissionDenied("只能编辑本人创建且处于草稿/驳回状态的入库单。")
    form = InboundOrderForm(request.POST or None, instance=order)
    formset = InboundItemFormSet(request.POST or None, instance=order)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        warehouse = form.cleaned_data["warehouse"]
        errors = False
        seen = set()
        for item_form in formset.forms:
            data = getattr(item_form, "cleaned_data", None)
            if not data or data.get("DELETE"):
                continue
            location = data.get("location")
            herb = data.get("herb")
            batch_no = (data.get("batch_no") or "").strip()
            if location and location.warehouse_id != warehouse.pk:
                item_form.add_error("location", "该库位不属于所选入库仓库。")
                errors = True
            key = (herb.pk if herb else None, batch_no, location.pk if location else None)
            if key in seen:
                item_form.add_error("batch_no", "同一药材/批次/库位在单据中重复。")
                errors = True
            seen.add(key)
        if not errors:
            with transaction.atomic():
                old_status = order.status
                order = _save_order(request, form, formset, instance=order)
                OrderStatusLog.record(
                    order,
                    OrderStatusLog.Action.UPDATE,
                    request.user,
                    comment="编辑入库单与明细。",
                    from_status=old_status,
                    to_status=order.status,
                )
            if request.POST.get("action") == "submit":
                try:
                    submit_inbound(order, request.user)
                    messages.success(request, "入库单已更新并提交验收。")
                except WorkflowError as exc:
                    messages.warning(request, f"草稿已保存，但提交验收失败：{exc}")
            else:
                messages.success(request, "入库单与明细已更新。")
            return redirect("inbound_detail", pk=order.pk)
    return render(
        request,
        "warehouse/inbound_form.html",
        {
            "form": form,
            "formset": formset,
            "order": order,
            "is_create": False,
            "active_nav": "inbound",
        },
    )


def _detail_context(request, order):
    items = order.items.select_related("herb", "location", "location__warehouse")
    logs = OrderStatusLog.for_order(order)
    editable = can_edit(request.user, order)
    return {
        "order": order,
        "items": items,
        "logs": logs,
        "total_quantity": sum((item.quantity for item in items), Decimal("0")),
        "total_amount": sum((item.subtotal for item in items), Decimal("0")),
        "can_edit": editable,
        "can_submit": order.can_submit and editable,
        "can_review": order.can_audit and has_perm(request.user, "inbound.audit"),
        "can_complete": order.can_complete and has_perm(request.user, "inbound.execute"),
        "can_cancel": can_cancel(request.user, order),
        "is_self_review": order.applicant_id == request.user.id and not request.user.is_superuser,
        "review_form": ReviewForm(),
        "reject_form": RejectForm(),
        "cancel_form": CancelForm(),
        "active_nav": "inbound",
    }


@login_required
def inbound_detail(request, pk):
    _require(request.user, "inbound.view")
    order = get_object_or_404(_base_queryset(), pk=pk)
    return render(request, "warehouse/inbound_detail.html", _detail_context(request, order))


@login_required
@require_POST
def inbound_submit(request, pk):
    _require(request.user, "inbound.create")
    order = get_object_or_404(InboundOrder, pk=pk)
    if not can_edit(request.user, order):
        raise PermissionDenied("只能提交本人创建的入库单。")
    try:
        submit_inbound(order, request.user)
        messages.success(request, "入库单已提交验收。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("inbound_detail", pk=order.pk)


@login_required
@require_POST
def inbound_approve(request, pk):
    _require(request.user, "inbound.audit")
    order = get_object_or_404(InboundOrder, pk=pk)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "验收意见格式不正确。")
        return redirect("inbound_detail", pk=order.pk)
    try:
        approve_order(order, request.user, form.cleaned_data["comment"])
        messages.success(request, "验收通过，等待仓管员确认入库。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("inbound_detail", pk=order.pk)


@login_required
@require_POST
def inbound_reject(request, pk):
    _require(request.user, "inbound.audit")
    order = get_object_or_404(InboundOrder, pk=pk)
    form = RejectForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写至少 2 个字的驳回原因。")
        return redirect("inbound_detail", pk=order.pk)
    try:
        reject_order(order, request.user, form.cleaned_data["comment"])
        messages.warning(request, "入库单已驳回，可修改后重新提交。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("inbound_detail", pk=order.pk)


@login_required
@require_POST
def inbound_complete(request, pk):
    _require(request.user, "inbound.execute")
    order = get_object_or_404(InboundOrder, pk=pk)
    comment = (request.POST.get("comment") or "").strip()
    try:
        complete_inbound(order, request.user, comment)
        messages.success(request, "入库完成，库存与批次已增加。")
    except WorkflowError as exc:
        messages.error(request, f"入库失败：{exc}")
    return redirect("inbound_detail", pk=order.pk)


@login_required
@require_POST
def inbound_cancel(request, pk):
    order = get_object_or_404(InboundOrder, pk=pk)
    if not can_cancel(request.user, order):
        raise PermissionDenied("当前岗位无权取消该入库单。")
    form = CancelForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else ""
    try:
        cancel_order(order, request.user, reason)
        messages.info(request, "入库单已取消。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("inbound_detail", pk=order.pk)
