"""学生 4 模块视图：移库/出库处理、审核、执行、附件与轨迹。"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AttachmentForm,
    CancelForm,
    ExceptionForm,
    OutboundOrderForm,
    RejectForm,
    ReviewForm,
    TransferOrderForm,
)
from .models import (
    Herb,
    InboundOrder,
    OrderAttachment,
    OrderStatus,
    OrderStatusLog,
    OutboundOrder,
    StockBatch,
    StockMovement,
    Supplier,
    TransferOrder,
    Warehouse,
)
from .permissions import (
    can_annotate as user_can_annotate,
    can_cancel as user_can_cancel,
    can_edit as user_can_edit,
    has_perm,
    is_admin,
)
from .services import (
    WorkflowError,
    approve_order,
    cancel_order,
    complete_outbound,
    complete_transfer,
    record_exception,
    reject_order,
    submit_order,
)

PAGE_SIZE = 10
STATUS_CHOICES = list(OrderStatus.choices)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _profile(user):
    profile = getattr(user, "profile", None)
    if profile is None:
        from .models import UserProfile

        profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def _can_annotate(user):
    return user_can_annotate(user)


def _can_edit(user, order):
    return user_can_edit(user, order)


def _status_counts(queryset):
    counts = {key: 0 for key, _label in STATUS_CHOICES}
    for row in queryset.values("status").annotate(total=Count("id")):
        counts[row["status"]] = row["total"]
    return counts


def _status_tabs(counts, current=""):
    return [
        {
            "value": value,
            "label": label,
            "count": counts.get(value, 0),
            "active": current == value,
        }
        for value, label in STATUS_CHOICES
    ]


def _pagination(request, queryset):
    paginator = Paginator(queryset, PAGE_SIZE)
    return paginator.get_page(request.GET.get("page"))


def _parse_date(raw, field_label, errors):
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        errors.append(f"{field_label}格式不正确，应为 YYYY-MM-DD。")
        return None


def _apply_common_filters(request, queryset, kind):
    """列表页的关键字、状态、药材、日期筛选，返回筛选上下文。"""
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    herb_id = (request.GET.get("herb") or "").strip()
    date_from_raw = (request.GET.get("date_from") or "").strip()
    date_to_raw = (request.GET.get("date_to") or "").strip()
    errors = []
    date_from = _parse_date(date_from_raw, "开始日期", errors)
    date_to = _parse_date(date_to_raw, "结束日期", errors)
    if date_from and date_to and date_from > date_to:
        errors.append("开始日期不能晚于结束日期。")
    if status and status not in dict(STATUS_CHOICES):
        status = ""

    if q:
        if kind == "transfer":
            queryset = queryset.filter(
                Q(transfer_no__icontains=q)
                | Q(herb__name__icontains=q)
                | Q(herb__code__icontains=q)
                | Q(batch_no__icontains=q)
                | Q(reason__icontains=q)
                | Q(applicant__username__icontains=q)
            )
        else:
            queryset = queryset.filter(
                Q(outbound_no__icontains=q)
                | Q(herb__name__icontains=q)
                | Q(herb__code__icontains=q)
                | Q(batch_no__icontains=q)
                | Q(recipient__icontains=q)
                | Q(purpose__icontains=q)
                | Q(applicant__username__icontains=q)
            )
    if status:
        queryset = queryset.filter(status=status)
    if herb_id.isdigit():
        queryset = queryset.filter(herb_id=int(herb_id))
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    filters = {
        "q": q,
        "status": status,
        "herb": herb_id,
        "date_from": date_from_raw,
        "date_to": date_to_raw,
        "has_filters": bool(q or status or herb_id or date_from_raw or date_to_raw),
        "errors": errors,
    }
    return queryset, filters


def _base_order_queryset(kind):
    model = TransferOrder if kind == "transfer" else OutboundOrder
    qs = model.objects.select_related(
        "herb", "applicant", "applicant__profile", "auditor", "auditor__profile"
    )
    if kind == "transfer":
        qs = qs.select_related("from_location", "from_location__warehouse", "to_location", "to_location__warehouse")
    else:
        qs = qs.select_related("location", "location__warehouse")
    return qs


# ---------------------------------------------------------------------------
# 工作台
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    profile = _profile(request.user)
    transfer_counts = _status_counts(TransferOrder.objects.all())
    outbound_counts = _status_counts(OutboundOrder.objects.all())
    inbound_counts = _status_counts(InboundOrder.objects.all())
    today = timezone.localdate()

    pending_total = (
        transfer_counts.get(OrderStatus.PENDING, 0)
        + outbound_counts.get(OrderStatus.PENDING, 0)
        + inbound_counts.get(OrderStatus.PENDING, 0)
    )
    approved_total = (
        transfer_counts.get(OrderStatus.APPROVED, 0)
        + outbound_counts.get(OrderStatus.APPROVED, 0)
        + inbound_counts.get(OrderStatus.APPROVED, 0)
    )
    completed_today = (
        TransferOrder.objects.filter(completed_at__date=today).count()
        + OutboundOrder.objects.filter(completed_at__date=today).count()
        + InboundOrder.objects.filter(completed_at__date=today).count()
    )
    exception_total = (
        TransferOrder.objects.exclude(exception_note="")
        .exclude(status=OrderStatus.CANCELLED)
        .count()
        + OutboundOrder.objects.exclude(exception_note="")
        .exclude(status=OrderStatus.CANCELLED)
        .count()
        + InboundOrder.objects.exclude(exception_note="")
        .exclude(status=OrderStatus.CANCELLED)
        .count()
    )

    recent_transfers = list(_base_order_queryset("transfer").order_by("-created_at")[:3])
    recent_outbounds = list(_base_order_queryset("outbound").order_by("-created_at")[:3])
    recent_inbounds = list(
        InboundOrder.objects.select_related(
            "supplier", "warehouse", "applicant", "applicant__profile"
        ).order_by("-created_at")[:3]
    )
    recent_orders = sorted(
        [("inbound", obj) for obj in recent_inbounds]
        + [("transfer", obj) for obj in recent_transfers]
        + [("outbound", obj) for obj in recent_outbounds],
        key=lambda pair: pair[1].created_at,
        reverse=True,
    )[:7]

    logs = OrderStatusLog.objects.select_related(
        "operator", "operator__profile"
    ).order_by("-created_at", "-id")[:8]

    low_stock = (
        StockBatch.objects.filter(quantity__lte=F("herb__safety_stock"))
        .select_related("herb", "location", "location__warehouse")
        .order_by("quantity")[:5]
    )
    stock_total = StockBatch.objects.aggregate(total=Sum("quantity"))["total"] or Decimal(
        "0"
    )
    batch_count = StockBatch.objects.count()
    herb_count = Herb.objects.filter(is_active=True).count()

    start_day = today - timedelta(days=6)
    daily_map = {}
    for model in (InboundOrder, TransferOrder, OutboundOrder):
        rows = (
            model.objects.filter(completed_at__date__gte=start_day)
            .values("completed_at__date")
            .annotate(total=Count("id"))
        )
        for row in rows:
            key = row["completed_at__date"]
            daily_map[key] = daily_map.get(key, 0) + row["total"]
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    daily = []
    max_daily = max(daily_map.values(), default=1)
    for offset in range(7):
        day = start_day + timedelta(days=offset)
        count = daily_map.get(day, 0)
        daily.append(
            {
                "date": day,
                "label": f"周{weekdays[day.weekday()]}",
                "count": count,
                "height": max(8, round(count / max_daily * 100)) if count else 8,
            }
        )

    context = {
        "profile": profile,
        "pending_total": pending_total,
        "approved_total": approved_total,
        "completed_today": completed_today,
        "exception_total": exception_total,
        "recent_orders": [
            {
                "kind": kind,
                "order": order,
                "kind_label": {
                    "inbound": "入库",
                    "transfer": "移库",
                    "outbound": "出库",
                }[kind],
            }
            for kind, order in recent_orders
        ],
        "logs": logs,
        "low_stock": low_stock,
        "stock_total": stock_total,
        "batch_count": batch_count,
        "herb_count": herb_count,
        "warehouse_count": Warehouse.objects.filter(is_active=True).count(),
        "supplier_count": Supplier.objects.filter(is_active=True).count(),
        "daily": daily,
        "transfer_counts": transfer_counts,
        "outbound_counts": outbound_counts,
        "inbound_counts": inbound_counts,
        "active_nav": "dashboard",
    }
    return render(request, "warehouse/dashboard.html", context)


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------
@login_required
def transfer_list(request):
    base = _base_order_queryset("transfer")
    counts = _status_counts(base)
    queryset, filters = _apply_common_filters(request, base, "transfer")
    page_obj = _pagination(request, queryset)
    context = {
        "page_obj": page_obj,
        "orders": page_obj.object_list,
        "counts": counts,
        "total_count": sum(counts.values()),
        "status_tabs": _status_tabs(counts, filters["status"]),
        "filters": filters,
        "herbs": Herb.objects.filter(is_active=True),
        "kind": "transfer",
        "kind_label": "移库单",
        "list_title": "移库管理",
        "list_sub": "同一仓库内库位到库位的移动，确认完成后源库位扣减、目标库位增加。",
        "detail_url_name": "transfer_detail",
        "create_url_name": "transfer_create",
        "active_nav": "transfer",
        "can_create": has_perm(request.user, "transfer.create"),
    }
    return render(request, "warehouse/order_list.html", context)


@login_required
def outbound_list(request):
    base = _base_order_queryset("outbound")
    counts = _status_counts(base)
    queryset, filters = _apply_common_filters(request, base, "outbound")
    page_obj = _pagination(request, queryset)
    context = {
        "page_obj": page_obj,
        "orders": page_obj.object_list,
        "counts": counts,
        "total_count": sum(counts.values()),
        "status_tabs": _status_tabs(counts, filters["status"]),
        "filters": filters,
        "herbs": Herb.objects.filter(is_active=True),
        "kind": "outbound",
        "kind_label": "出库单",
        "list_title": "出库管理",
        "list_sub": "药材从库位离开仓库，审核后凭单执行，库存扣减与流水同步完成。",
        "detail_url_name": "outbound_detail",
        "create_url_name": "outbound_create",
        "active_nav": "outbound",
        "can_create": has_perm(request.user, "outbound.create"),
    }
    return render(request, "warehouse/order_list.html", context)


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------
def _detail_context(request, order, kind):
    attachments = order.attachments.select_related("uploaded_by", "uploaded_by__profile")
    logs = OrderStatusLog.for_order(order)
    if kind == "transfer":
        stock = (
            StockBatch.objects.filter(
                herb=order.herb, location=order.from_location, batch_no=order.batch_no
            )
            .select_related("herb", "location")
            .first()
        )
        destination_stock = (
            StockBatch.objects.filter(
                herb=order.herb, location=order.to_location, batch_no=order.batch_no
            ).first()
        )
        movements = StockMovement.objects.filter(
            order_type=StockMovement.OrderType.TRANSFER, order_no=order.transfer_no
        ).select_related("batch", "batch__location", "operator")
    else:
        stock = (
            StockBatch.objects.filter(
                herb=order.herb, location=order.location, batch_no=order.batch_no
            )
            .select_related("herb", "location")
            .first()
        )
        destination_stock = None
        movements = StockMovement.objects.filter(
            order_type=StockMovement.OrderType.OUTBOUND, order_no=order.outbound_no
        ).select_related("batch", "batch__location", "operator")

    return {
        "order": order,
        "kind": kind,
        "kind_label": "移库单" if kind == "transfer" else "出库单",
        "attachments": attachments,
        "logs": logs,
        "stock": stock,
        "destination_stock": destination_stock,
        "movements": movements,
        "review_form": ReviewForm(),
        "reject_form": RejectForm(),
        "cancel_form": CancelForm(),
        "exception_form": ExceptionForm(),
        "attachment_form": AttachmentForm(),
        "can_edit": _can_edit(request.user, order),
        "can_submit": order.can_submit and _can_edit(request.user, order),
        "can_review": order.can_audit and has_perm(request.user, f"{kind}.audit"),
        "can_complete": order.can_complete
        and has_perm(request.user, f"{kind}.execute"),
        "can_cancel": user_can_cancel(request.user, order),
        "can_annotate": _can_annotate(request.user),
        "can_add_attachment": _can_annotate(request.user),
        "can_manage_attachments": is_admin(request.user)
        or has_perm(request.user, f"{kind}.audit"),
        "is_self_review": order.applicant_id == request.user.id and not request.user.is_superuser,
        "active_nav": "transfer" if kind == "transfer" else "outbound",
    }


@login_required
def transfer_detail(request, pk):
    order = get_object_or_404(_base_order_queryset("transfer"), pk=pk)
    return render(
        request, "warehouse/order_detail.html", _detail_context(request, order, "transfer")
    )


@login_required
def outbound_detail(request, pk):
    order = get_object_or_404(_base_order_queryset("outbound"), pk=pk)
    return render(
        request, "warehouse/order_detail.html", _detail_context(request, order, "outbound")
    )


# ---------------------------------------------------------------------------
# 新建 / 编辑 / 删除
# ---------------------------------------------------------------------------
def _after_save(request, order, noun, edited=False):
    if request.POST.get("action") == "submit":
        try:
            submit_order(order, request.user)
            messages.success(request, f"{noun}已保存并提交审核，等待仓库主管处理。")
        except WorkflowError as exc:
            messages.warning(request, f"{noun}草稿已保存，但提交审核未通过：{exc}")
    elif edited:
        messages.success(request, f"{noun}已更新，请核对后提交审核。")
    else:
        messages.success(request, f"{noun}已保存为草稿。")


@login_required
def transfer_create(request):
    if not has_perm(request.user, "transfer.create"):
        raise PermissionDenied("当前岗位没有创建移库单的权限。")
    form = TransferOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        order = form.save(commit=False)
        order.applicant = request.user
        order.status = OrderStatus.DRAFT
        order.save()
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.CREATE,
            request.user,
            comment="创建移库单草稿。",
            from_status="",
            to_status=order.status,
        )
        _after_save(request, order, "移库单")
        return redirect(order.get_absolute_url())
    return render(
        request,
        "warehouse/order_form.html",
        {
            "form": form,
            "kind": "transfer",
            "active_nav": "transfer",
            "is_create": True,
        },
    )


@login_required
def transfer_edit(request, pk):
    order = get_object_or_404(_base_order_queryset("transfer"), pk=pk)
    if not _can_edit(request.user, order):
        raise PermissionDenied("只能编辑本人创建的草稿或已驳回单据。")
    form = TransferOrderForm(request.POST or None, instance=order)
    if request.method == "POST" and form.is_valid():
        old_status = order.status
        order = form.save(commit=False)
        if order.status == OrderStatus.REJECTED:
            order.status = OrderStatus.DRAFT
        order.save()
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.UPDATE,
            request.user,
            comment="编辑单据内容，状态重置为草稿。"
            if old_status == OrderStatus.REJECTED
            else "编辑单据内容。",
            from_status=old_status,
            to_status=order.status,
        )
        _after_save(request, order, "移库单", edited=True)
        return redirect(order.get_absolute_url())
    return render(
        request,
        "warehouse/order_form.html",
        {
            "form": form,
            "order": order,
            "kind": "transfer",
            "active_nav": "transfer",
            "is_create": False,
        },
    )


@login_required
def outbound_create(request):
    if not has_perm(request.user, "outbound.create"):
        raise PermissionDenied("当前岗位没有创建出库单的权限。")
    form = OutboundOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        order = form.save(commit=False)
        order.applicant = request.user
        order.status = OrderStatus.DRAFT
        order.save()
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.CREATE,
            request.user,
            comment="创建出库单草稿。",
            from_status="",
            to_status=order.status,
        )
        _after_save(request, order, "出库单")
        return redirect(order.get_absolute_url())
    return render(
        request,
        "warehouse/order_form.html",
        {
            "form": form,
            "kind": "outbound",
            "active_nav": "outbound",
            "is_create": True,
        },
    )


@login_required
def outbound_edit(request, pk):
    order = get_object_or_404(_base_order_queryset("outbound"), pk=pk)
    if not _can_edit(request.user, order):
        raise PermissionDenied("只能编辑本人创建的草稿或已驳回单据。")
    form = OutboundOrderForm(request.POST or None, instance=order)
    if request.method == "POST" and form.is_valid():
        old_status = order.status
        order = form.save(commit=False)
        if order.status == OrderStatus.REJECTED:
            order.status = OrderStatus.DRAFT
        order.save()
        OrderStatusLog.record(
            order,
            OrderStatusLog.Action.UPDATE,
            request.user,
            comment="编辑单据内容，状态重置为草稿。"
            if old_status == OrderStatus.REJECTED
            else "编辑单据内容。",
            from_status=old_status,
            to_status=order.status,
        )
        _after_save(request, order, "出库单", edited=True)
        return redirect(order.get_absolute_url())
    return render(
        request,
        "warehouse/order_form.html",
        {
            "form": form,
            "order": order,
            "kind": "outbound",
            "active_nav": "outbound",
            "is_create": False,
        },
    )


@login_required
@require_POST
def transfer_delete(request, pk):
    order = get_object_or_404(TransferOrder, pk=pk)
    if not _can_edit(request.user, order) or order.status != OrderStatus.DRAFT:
        raise PermissionDenied("只能删除本人创建且尚未提交的草稿。")
    no = order.transfer_no
    with transaction.atomic():
        for attachment in order.attachments.all():
            attachment.file.delete(save=False)
        OrderStatusLog.for_order(order).delete()
        order.delete()
    messages.success(request, f"草稿 {no} 已删除。")
    return redirect("transfer_list")


@login_required
@require_POST
def outbound_delete(request, pk):
    order = get_object_or_404(OutboundOrder, pk=pk)
    if not _can_edit(request.user, order) or order.status != OrderStatus.DRAFT:
        raise PermissionDenied("只能删除本人创建且尚未提交的草稿。")
    no = order.outbound_no
    with transaction.atomic():
        for attachment in order.attachments.all():
            attachment.file.delete(save=False)
        OrderStatusLog.for_order(order).delete()
        order.delete()
    messages.success(request, f"草稿 {no} 已删除。")
    return redirect("outbound_list")


# ---------------------------------------------------------------------------
# 状态流转动作
# ---------------------------------------------------------------------------
def _order_or_404(kind, pk):
    model = TransferOrder if kind == "transfer" else OutboundOrder
    return get_object_or_404(model, pk=pk)


def _back(order):
    return redirect(order.get_absolute_url())


@login_required
@require_POST
def transfer_submit(request, pk):
    order = _order_or_404("transfer", pk)
    if not _can_edit(request.user, order):
        raise PermissionDenied("只能提交本人创建的草稿或已驳回单据。")
    try:
        submit_order(order, request.user)
        messages.success(request, "已提交审核，等待仓库主管处理。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def outbound_submit(request, pk):
    order = _order_or_404("outbound", pk)
    if not _can_edit(request.user, order):
        raise PermissionDenied("只能提交本人创建的草稿或已驳回单据。")
    try:
        submit_order(order, request.user)
        messages.success(request, "已提交审核，等待仓库主管处理。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def transfer_approve(request, pk):
    if not has_perm(request.user, "transfer.audit"):
        raise PermissionDenied("当前岗位没有审核移库单的权限。")
    order = _order_or_404("transfer", pk)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "审核意见格式不正确。")
        return _back(order)
    try:
        approve_order(order, request.user, form.cleaned_data["comment"])
        messages.success(request, "审核通过，已进入待执行队列。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def outbound_approve(request, pk):
    if not has_perm(request.user, "outbound.audit"):
        raise PermissionDenied("当前岗位没有审核出库单的权限。")
    order = _order_or_404("outbound", pk)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "审核意见格式不正确。")
        return _back(order)
    try:
        approve_order(order, request.user, form.cleaned_data["comment"])
        messages.success(request, "审核通过，已进入待执行队列。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def transfer_reject(request, pk):
    if not has_perm(request.user, "transfer.audit"):
        raise PermissionDenied("当前岗位没有驳回移库单的权限。")
    order = _order_or_404("transfer", pk)
    form = RejectForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写至少 2 个字的驳回原因。")
        return _back(order)
    try:
        reject_order(order, request.user, form.cleaned_data["comment"])
        messages.warning(request, "移库单已驳回，申请人可修改后重新提交。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def outbound_reject(request, pk):
    if not has_perm(request.user, "outbound.audit"):
        raise PermissionDenied("当前岗位没有驳回出库单的权限。")
    order = _order_or_404("outbound", pk)
    form = RejectForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请填写至少 2 个字的驳回原因。")
        return _back(order)
    try:
        reject_order(order, request.user, form.cleaned_data["comment"])
        messages.warning(request, "出库单已驳回，申请人可修改后重新提交。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def transfer_complete(request, pk):
    if not has_perm(request.user, "transfer.execute"):
        raise PermissionDenied("当前岗位没有执行移库的权限。")
    order = _order_or_404("transfer", pk)
    comment = (request.POST.get("comment") or "").strip()
    try:
        complete_transfer(order, request.user, comment)
        messages.success(request, "移库完成，源库位与目标库位库存已同步更新。")
    except WorkflowError as exc:
        messages.error(request, f"移库执行失败：{exc}")
        order.refresh_from_db()
        if order.status == OrderStatus.APPROVED:
            try:
                record_exception(order, request.user, f"移库执行失败：{exc}")
            except WorkflowError:
                pass
    return _back(order)


@login_required
@require_POST
def outbound_complete(request, pk):
    if not has_perm(request.user, "outbound.execute"):
        raise PermissionDenied("当前岗位没有执行出库的权限。")
    order = _order_or_404("outbound", pk)
    comment = (request.POST.get("comment") or "").strip()
    try:
        complete_outbound(order, request.user, comment)
        messages.success(request, "出库完成，库存已扣减并生成库存流水。")
    except WorkflowError as exc:
        messages.error(request, f"出库执行失败：{exc}")
        order.refresh_from_db()
        if order.status == OrderStatus.APPROVED:
            try:
                record_exception(order, request.user, f"出库执行失败：{exc}")
            except WorkflowError:
                pass
    return _back(order)


@login_required
@require_POST
def transfer_cancel(request, pk):
    order = _order_or_404("transfer", pk)
    if not user_can_cancel(request.user, order):
        raise PermissionDenied("当前岗位无权取消该移库单。")
    form = CancelForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else ""
    try:
        cancel_order(order, request.user, reason)
        messages.info(request, "移库单已取消。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def outbound_cancel(request, pk):
    order = _order_or_404("outbound", pk)
    if not user_can_cancel(request.user, order):
        raise PermissionDenied("当前岗位无权取消该出库单。")
    form = CancelForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else ""
    try:
        cancel_order(order, request.user, reason)
        messages.info(request, "出库单已取消。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


# ---------------------------------------------------------------------------
# 异常备注与附件
# ---------------------------------------------------------------------------
@login_required
@require_POST
def transfer_exception(request, pk):
    if not _can_annotate(request.user):
        raise PermissionDenied("只读访客不能修改异常备注。")
    order = _order_or_404("transfer", pk)
    form = ExceptionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "异常备注至少填写 2 个字，且不超过 500 字。")
        return _back(order)
    try:
        record_exception(order, request.user, form.cleaned_data["note"])
        messages.success(request, "异常备注已追加到执行档案。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


@login_required
@require_POST
def outbound_exception(request, pk):
    if not _can_annotate(request.user):
        raise PermissionDenied("只读访客不能修改异常备注。")
    order = _order_or_404("outbound", pk)
    form = ExceptionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "异常备注至少填写 2 个字，且不超过 500 字。")
        return _back(order)
    try:
        record_exception(order, request.user, form.cleaned_data["note"])
        messages.success(request, "异常备注已追加到执行档案。")
    except WorkflowError as exc:
        messages.error(request, str(exc))
    return _back(order)


def _handle_attachment(request, order, kind):
    if not _can_annotate(request.user):
        raise PermissionDenied("只读访客不能上传附件。")
    instance = OrderAttachment(
        transfer=order if kind == "transfer" else None,
        outbound=order if kind == "outbound" else None,
    )
    form = AttachmentForm(request.POST, request.FILES, instance=instance)
    if not form.is_valid():
        errors = "；".join(
            f"{field}: {'，'.join(messages)}" for field, messages in form.errors.items()
        )
        messages.error(request, f"附件上传失败：{errors}")
        return _back(order)
    attachment = form.save(commit=False)
    attachment.uploaded_by = request.user
    attachment.original_name = form.cleaned_data["file"].name[:255]
    if kind == "transfer":
        attachment.transfer = order
    else:
        attachment.outbound = order
    attachment.full_clean()
    attachment.save()
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.ATTACH,
        request.user,
        comment=f"上传附件：{attachment.original_name}"[:500],
        from_status=order.status,
        to_status=order.status,
    )
    messages.success(request, "附件已上传，可在执行档案中查看。")
    return _back(order)


@login_required
@require_POST
def transfer_attachment_upload(request, pk):
    return _handle_attachment(request, _order_or_404("transfer", pk), "transfer")


@login_required
@require_POST
def outbound_attachment_upload(request, pk):
    return _handle_attachment(request, _order_or_404("outbound", pk), "outbound")


@login_required
@require_POST
def attachment_delete(request, pk):
    attachment = get_object_or_404(
        OrderAttachment.objects.select_related("transfer", "outbound", "uploaded_by"), pk=pk
    )
    order = attachment.transfer or attachment.outbound
    if order is None:
        raise PermissionDenied("附件未关联单据。")
    allowed = is_admin(request.user) or has_perm(
        request.user, f"{order.order_type}.audit"
    ) or (
        attachment.uploaded_by_id == request.user.id
        and order.status != OrderStatus.COMPLETED
    )
    if not allowed:
        raise PermissionDenied("已完成单据的附件仅主管或管理员可删除。")
    name = attachment.original_name
    attachment.file.delete(save=False)
    attachment.delete()
    OrderStatusLog.record(
        order,
        OrderStatusLog.Action.DELETE_ATTACH,
        request.user,
        comment=f"删除附件：{name}"[:500],
        from_status=order.status,
        to_status=order.status,
    )
    messages.info(request, "附件已删除。")
    return _back(order)


# ---------------------------------------------------------------------------
# 库存批次接口（供表单联动）
# ---------------------------------------------------------------------------
@login_required
def stock_batches_api(request):
    if not has_perm(request.user, "stock.view"):
        return JsonResponse({"error": "permission denied"}, status=403)
    herb_id = request.GET.get("herb")
    location_id = request.GET.get("location")
    if not (str(herb_id).isdigit() and str(location_id).isdigit()):
        return JsonResponse({"results": [], "total": "0"})
    batches = (
        StockBatch.objects.filter(
            herb_id=int(herb_id),
            location_id=int(location_id),
            quantity__gt=0,
        )
        .select_related("herb", "location")
        .order_by("batch_no")
    )
    results = [
        {
            "batch_no": batch.batch_no,
            "quantity": f"{batch.quantity:.3f}",
            "unit": batch.herb.unit,
            "production_date": batch.production_date.isoformat()
            if batch.production_date
            else "",
            "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else "",
        }
        for batch in batches
    ]
    total = sum((batch.quantity for batch in batches), Decimal("0"))
    return JsonResponse(
        {
            "results": results,
            "total": f"{total:.3f}",
            "herb_name": batches[0].herb.name if len(batches) else "",
            "location": str(batches[0].location) if len(batches) else "",
        }
    )


def permission_denied_view(request, exception=None):
    return render(request, "403.html", status=403)



