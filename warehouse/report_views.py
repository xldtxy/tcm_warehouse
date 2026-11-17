"""学生 5：库存流水查询、统计、操作日志、导出与打印。"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .models import (
    Herb,
    OrderStatus,
    OrderStatusLog,
    StockBatch,
    StockMovement,
)
from .permissions import has_perm

MOVEMENT_TYPES = StockMovement.MovementType.choices
ORDER_TYPES = StockMovement.OrderType.choices
LOG_ACTIONS = OrderStatusLog.Action.choices
LOG_ORDER_TYPES = OrderStatusLog.OrderType.choices


def _require(user, code):
    if not has_perm(user, code):
        raise PermissionDenied("当前岗位没有该功能权限。")


def _parse_date(raw):
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _movement_filters(request):
    qs = StockMovement.objects.select_related(
        "batch", "batch__herb", "batch__location", "batch__location__warehouse", "operator"
    )
    q = (request.GET.get("q") or "").strip()
    operator_id = (request.GET.get("operator") or "").strip()
    herb_id = (request.GET.get("herb") or "").strip()
    order_type = (request.GET.get("order_type") or "").strip()
    movement_type = (request.GET.get("movement_type") or "").strip()
    date_from_raw = (request.GET.get("date_from") or "").strip()
    date_to_raw = (request.GET.get("date_to") or "").strip()
    date_from = _parse_date(date_from_raw)
    date_to = _parse_date(date_to_raw)
    if q:
        qs = qs.filter(
            Q(batch__herb__name__icontains=q)
            | Q(batch__herb__code__icontains=q)
            | Q(batch__batch_no__icontains=q)
            | Q(batch__location__code__icontains=q)
            | Q(order_no__icontains=q)
            | Q(operator__username__icontains=q)
            | Q(remark__icontains=q)
        )
    if operator_id.isdigit():
        qs = qs.filter(operator_id=int(operator_id))
    if herb_id.isdigit():
        qs = qs.filter(batch__herb_id=int(herb_id))
    if order_type in dict(ORDER_TYPES):
        qs = qs.filter(order_type=order_type)
    if movement_type in dict(MOVEMENT_TYPES):
        qs = qs.filter(movement_type=movement_type)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs, {
        "q": q,
        "operator": operator_id,
        "herb": herb_id,
        "order_type": order_type,
        "movement_type": movement_type,
        "date_from": date_from_raw,
        "date_to": date_to_raw,
        "date_from_value": date_from,
        "date_to_value": date_to,
        "has_filters": bool(
            q
            or operator_id
            or herb_id
            or order_type
            or movement_type
            or date_from_raw
            or date_to_raw
        ),
    }


def _summarize_movements(qs):
    incoming = qs.filter(
        movement_type__in=[
            StockMovement.MovementType.OPENING,
            StockMovement.MovementType.INBOUND,
            StockMovement.MovementType.TRANSFER_IN,
        ]
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    outgoing = qs.filter(
        movement_type__in=[
            StockMovement.MovementType.OUTBOUND,
            StockMovement.MovementType.TRANSFER_OUT,
            StockMovement.MovementType.ADJUST,
        ]
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    return incoming, outgoing, qs.count()


def _daily_chart(qs, date_from=None, date_to=None):
    end = date_to or timezone.localdate()
    start = date_from or (end - timedelta(days=6))
    if start > end:
        start, end = end, start
    if (end - start).days > 60:
        start = end - timedelta(days=60)
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    in_map, out_map = {}, {}
    for row in (
        qs.filter(created_at__date__gte=start, created_at__date__lte=end)
        .exclude(order_type=StockMovement.OrderType.MANUAL)
        .values("created_at__date", "movement_type")
        .annotate(total=Sum("quantity"))
    ):
        day = row["created_at__date"]
        if row["movement_type"] in {
            StockMovement.MovementType.OPENING,
            StockMovement.MovementType.INBOUND,
            StockMovement.MovementType.TRANSFER_IN,
        }:
            in_map[day] = in_map.get(day, Decimal("0")) + row["total"]
        else:
            out_map[day] = out_map.get(day, Decimal("0")) + row["total"]
    maximum = max(
        [value for value in list(in_map.values()) + list(out_map.values())] or [Decimal("1")]
    )
    weekday_labels = ["一", "二", "三", "四", "五", "六", "日"]
    return [
        {
            "date": day,
            "label": f"{day.month}/{day.day}",
            "weekday": f"周{weekday_labels[day.weekday()]}",
            "incoming": in_map.get(day, Decimal("0")),
            "outgoing": out_map.get(day, Decimal("0")),
            "incoming_height": max(4, round(float(in_map.get(day, 0)) / float(maximum or 1) * 100)),
            "outgoing_height": max(4, round(float(out_map.get(day, 0)) / float(maximum or 1) * 100)),
        }
        for day in days
    ]


def _stock_snapshot():
    return {
        "batch_count": StockBatch.objects.count(),
        "stock_total": StockBatch.objects.aggregate(total=Sum("quantity"))["total"]
        or Decimal("0"),
        "low_count": StockBatch.objects.filter(
            quantity__lte=F("herb__safety_stock")
        ).count(),
        "herb_count": Herb.objects.filter(is_active=True).count(),
        "by_warehouse": StockBatch.objects.values("location__warehouse__name")
        .annotate(total=Sum("quantity"))
        .order_by("-total")[:6],
        "top_herbs": StockBatch.objects.values("herb__name", "herb__unit")
        .annotate(total=Sum("quantity"))
        .order_by("-total")[:6],
    }


@login_required
def stock_query(request):
    _require(request.user, "query.view")
    qs, filters = _movement_filters(request)
    incoming, outgoing, movement_count = _summarize_movements(qs)
    page_obj = Paginator(qs.order_by("-created_at", "-id"), 15).get_page(
        request.GET.get("page")
    )
    top_herbs = (
        qs.values("batch__herb__name", "batch__herb__unit")
        .annotate(total=Sum("quantity"))
        .order_by("-total")[:6]
    )
    chart = _daily_chart(
        qs, filters.get("date_from_value"), filters.get("date_to_value")
    )
    return render(
        request,
        "warehouse/stock_query.html",
        {
            "page_obj": page_obj,
            "movements": page_obj.object_list,
            "filters": filters,
            "incoming": incoming,
            "outgoing": outgoing,
            "movement_count": movement_count,
            "chart": chart,
            "top_herbs": top_herbs,
            "snapshot": _stock_snapshot(),
            "operators": get_user_model()
            .objects.filter(is_active=True)
            .order_by("username"),
            "herbs": Herb.objects.filter(is_active=True).order_by("code"),
            "movement_types": MOVEMENT_TYPES,
            "order_types": ORDER_TYPES,
            "active_nav": "query",
        },
    )


@login_required
def stock_query_export(request):
    _require(request.user, "export.data")
    qs, _filters = _movement_filters(request)
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(
        ["发生时间", "业务类型", "单号", "药材编码", "药材", "批次", "库位", "变动类型", "数量", "变动前", "变动后", "单位", "操作人", "备注"]
    )
    for movement in qs.order_by("-created_at", "-id"):
        writer.writerow(
            [
                timezone.localtime(movement.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                movement.get_order_type_display(),
                movement.order_no or "—",
                movement.batch.herb.code,
                movement.batch.herb.name,
                movement.batch.batch_no,
                movement.batch.location.code,
                movement.get_movement_type_display(),
                movement.quantity,
                movement.before_quantity,
                movement.after_quantity,
                movement.batch.herb.unit,
                movement.operator.get_full_name() if movement.operator else "",
                movement.remark,
            ]
        )
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="inventory-ledger-{timezone.localdate():%Y%m%d}.csv"'
    )
    return response


@login_required
def stock_query_print(request):
    _require(request.user, "query.view")
    qs, filters = _movement_filters(request)
    incoming, outgoing, movement_count = _summarize_movements(qs)
    return render(
        request,
        "warehouse/stock_query_print.html",
        {
            "movements": qs.order_by("-created_at", "-id")[:500],
            "filters": filters,
            "incoming": incoming,
            "outgoing": outgoing,
            "movement_count": movement_count,
            "generated_at": timezone.localtime(),
        },
    )


@login_required
def operation_logs(request):
    _require(request.user, "log.view")
    qs = OrderStatusLog.objects.select_related("operator", "operator__profile").order_by(
        "-created_at", "-id"
    )
    q = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()
    order_type = (request.GET.get("order_type") or "").strip()
    operator_id = (request.GET.get("operator") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    if q:
        qs = qs.filter(
            Q(order_no__icontains=q)
            | Q(comment__icontains=q)
            | Q(operator__username__icontains=q)
        )
    if action in dict(LOG_ACTIONS):
        qs = qs.filter(action=action)
    if order_type in dict(LOG_ORDER_TYPES):
        qs = qs.filter(order_type=order_type)
    if operator_id.isdigit():
        qs = qs.filter(operator_id=int(operator_id))
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)
    if parsed_from:
        qs = qs.filter(created_at__date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(created_at__date__lte=parsed_to)
    page_obj = Paginator(qs, 20).get_page(request.GET.get("page"))
    action_counts = {
        row["action"]: row["total"]
        for row in qs.values("action").annotate(total=Count("id"))
    }
    return render(
        request,
        "warehouse/operation_logs.html",
        {
            "page_obj": page_obj,
            "logs": page_obj.object_list,
            "filters": {
                "q": q,
                "action": action,
                "order_type": order_type,
                "operator": operator_id,
                "date_from": date_from,
                "date_to": date_to,
                "has_filters": bool(q or action or order_type or operator_id or date_from or date_to),
            },
            "actions": LOG_ACTIONS,
            "order_types": LOG_ORDER_TYPES,
            "operators": get_user_model().objects.filter(is_active=True).order_by("username"),
            "action_counts": action_counts,
            "active_nav": "logs",
        },
    )


@login_required
def operation_logs_export(request):
    _require(request.user, "export.data")
    # 复用日志页面同样的筛选逻辑（独立查询，避免分页影响）
    qs = OrderStatusLog.objects.select_related("operator").order_by("-created_at", "-id")
    q = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()
    order_type = (request.GET.get("order_type") or "").strip()
    operator_id = (request.GET.get("operator") or "").strip()
    if q:
        qs = qs.filter(
            Q(order_no__icontains=q)
            | Q(comment__icontains=q)
            | Q(operator__username__icontains=q)
        )
    if action in dict(LOG_ACTIONS):
        qs = qs.filter(action=action)
    if order_type in dict(LOG_ORDER_TYPES):
        qs = qs.filter(order_type=order_type)
    if operator_id.isdigit():
        qs = qs.filter(operator_id=int(operator_id))
    parsed_from = _parse_date((request.GET.get("date_from") or "").strip())
    parsed_to = _parse_date((request.GET.get("date_to") or "").strip())
    if parsed_from:
        qs = qs.filter(created_at__date__gte=parsed_from)
    if parsed_to:
        qs = qs.filter(created_at__date__lte=parsed_to)
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(["操作时间", "操作人", "动作", "单据类型", "单号", "原状态", "新状态", "说明"])
    for log in qs:
        writer.writerow(
            [
                timezone.localtime(log.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                log.operator.get_full_name() if log.operator else "系统",
                log.get_action_display(),
                log.get_order_type_display(),
                log.order_no,
                log.from_status_label,
                log.to_status_label,
                log.comment,
            ]
        )
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="operation-logs-{timezone.localdate():%Y%m%d}.csv"'
    )
    return response
