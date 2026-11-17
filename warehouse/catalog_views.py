"""学生 2：药材资料与库存批次管理。"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import HerbForm, StockBatchCreateForm, StockBatchEditForm
from .models import (
    Herb,
    OrderStatus,
    StockBatch,
    StockMovement,
    StorageLocation,
    Warehouse,
)
from .permissions import has_perm
from .services import WorkflowError, adjust_stock


def _require(user, code):
    if not has_perm(user, code):
        raise PermissionDenied("当前岗位没有该功能权限。")


# ---------------------------------------------------------------------------
# 药材
# ---------------------------------------------------------------------------
@login_required
def herb_list(request):
    _require(request.user, "herb.view")
    qs = (
        Herb.objects.annotate(
            stock_total=Sum("stock_batches__quantity"),
            batch_count=Count("stock_batches", distinct=True),
        )
        .prefetch_related("stock_batches")
        .order_by("code")
    )
    q = (request.GET.get("q") or "").strip()
    category = (request.GET.get("category") or "").strip()
    status = (request.GET.get("active") or "").strip()
    if q:
        qs = qs.filter(
            Q(code__icontains=q) | Q(name__icontains=q) | Q(spec__icontains=q)
        )
    if category:
        qs = qs.filter(category=category)
    if status == "1":
        qs = qs.filter(is_active=True)
    elif status == "0":
        qs = qs.filter(is_active=False)
    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))
    return render(
        request,
        "warehouse/herb_list.html",
        {
            "page_obj": page_obj,
            "herbs": page_obj.object_list,
            "categories": Herb.objects.exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category"),
            "filters": {"q": q, "category": category, "active": status},
            "can_manage": has_perm(request.user, "herb.manage"),
            "stats": {
                "herbs": Herb.objects.count(),
                "active": Herb.objects.filter(is_active=True).count(),
                "low_batches": StockBatch.objects.filter(
                    quantity__lte=F("herb__safety_stock")
                ).count(),
            },
            "active_nav": "herbs",
        },
    )


@login_required
def herb_create(request):
    _require(request.user, "herb.manage")
    form = HerbForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        herb = form.save()
        messages.success(request, f"药材 {herb.name} 已创建。")
        return redirect("herb_detail", pk=herb.pk)
    return render(
        request,
        "warehouse/simple_form.html",
        {"form": form, "title": "新增药材", "active_nav": "herbs"},
    )


@login_required
def herb_edit(request, pk):
    _require(request.user, "herb.manage")
    herb = get_object_or_404(Herb, pk=pk)
    form = HerbForm(request.POST or None, instance=herb)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "药材信息已更新。")
        return redirect("herb_detail", pk=herb.pk)
    return render(
        request,
        "warehouse/simple_form.html",
        {"form": form, "herb": herb, "title": f"编辑药材 · {herb.name}", "active_nav": "herbs"},
    )


@login_required
def herb_detail(request, pk):
    _require(request.user, "herb.view")
    herb = get_object_or_404(Herb, pk=pk)
    batches = herb.stock_batches.select_related("location", "location__warehouse")
    movements = StockMovement.objects.filter(batch__herb=herb).select_related(
        "batch", "batch__location", "operator"
    )[:30]
    return render(
        request,
        "warehouse/herb_detail.html",
        {
            "herb": herb,
            "batches": batches,
            "movements": movements,
            "total_stock": herb.stock_batches.aggregate(total=Sum("quantity"))["total"]
            or Decimal("0"),
            "can_manage": has_perm(request.user, "herb.manage"),
            "active_nav": "herbs",
        },
    )


@login_required
def herb_delete(request, pk):
    _require(request.user, "herb.manage")
    if request.method != "POST":
        raise PermissionDenied("请通过页面按钮删除。")
    herb = get_object_or_404(Herb, pk=pk)
    has_business = (
        herb.stock_batches.exists()
        or herb.inbound_items.exists()
        or herb.transfers.exists()
        or herb.outbounds.exists()
    )
    if has_business:
        messages.error(request, "该药材已有库存或业务单据，不能删除，可编辑为停用。")
        return redirect("herb_detail", pk=herb.pk)
    name = herb.name
    herb.delete()
    messages.info(request, f"药材 {name} 已删除。")
    return redirect("herb_list")


# ---------------------------------------------------------------------------
# 库存批次
# ---------------------------------------------------------------------------
@login_required
def stock_list(request):
    _require(request.user, "stock.view")
    qs = StockBatch.objects.select_related(
        "herb", "location", "location__warehouse"
    ).order_by("herb__code", "location__code", "batch_no")
    q = (request.GET.get("q") or "").strip()
    warehouse_id = (request.GET.get("warehouse") or "").strip()
    herb_id = (request.GET.get("herb") or "").strip()
    low = request.GET.get("low") == "1"
    if q:
        qs = qs.filter(
            Q(herb__name__icontains=q)
            | Q(herb__code__icontains=q)
            | Q(batch_no__icontains=q)
            | Q(location__code__icontains=q)
        )
    if warehouse_id.isdigit():
        qs = qs.filter(location__warehouse_id=int(warehouse_id))
    if herb_id.isdigit():
        qs = qs.filter(herb_id=int(herb_id))
    if low:
        qs = qs.filter(quantity__lte=F("herb__safety_stock"))
    page_obj = Paginator(qs, 15).get_page(request.GET.get("page"))
    total = qs.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    return render(
        request,
        "warehouse/stock_list.html",
        {
            "page_obj": page_obj,
            "batches": page_obj.object_list,
            "warehouses": Warehouse.objects.filter(is_active=True),
            "herbs": Herb.objects.filter(is_active=True),
            "filters": {"q": q, "warehouse": warehouse_id, "herb": herb_id, "low": low},
            "total_stock": total,
            "can_manage": has_perm(request.user, "stock.manage"),
            "active_nav": "stock",
        },
    )


@login_required
def stock_create(request):
    _require(request.user, "stock.manage")
    form = StockBatchCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            batch = form.save()
            StockMovement.objects.create(
                batch=batch,
                movement_type=StockMovement.MovementType.OPENING,
                quantity=batch.quantity,
                before_quantity=Decimal("0"),
                after_quantity=batch.quantity,
                order_type=StockMovement.OrderType.MANUAL,
                order_no="",
                operator=request.user,
                remark="新建库存批次（期初入库）",
            )
        messages.success(request, f"库存批次 {batch.batch_no} 已创建并写期初流水。")
        return redirect("stock_detail", pk=batch.pk)
    return render(
        request,
        "warehouse/stock_form.html",
        {"form": form, "title": "新增库存批次", "is_create": True, "active_nav": "stock"},
    )


@login_required
def stock_detail(request, pk):
    _require(request.user, "stock.view")
    batch = get_object_or_404(
        StockBatch.objects.select_related("herb", "location", "location__warehouse"), pk=pk
    )
    movements = batch.movements.select_related("operator")[:50]
    return render(
        request,
        "warehouse/stock_detail.html",
        {
            "batch": batch,
            "movements": movements,
            "can_manage": has_perm(request.user, "stock.manage"),
            "active_nav": "stock",
        },
    )


@login_required
def stock_edit(request, pk):
    _require(request.user, "stock.manage")
    batch = get_object_or_404(StockBatch, pk=pk)
    form = StockBatchEditForm(request.POST or None, instance=batch)
    if request.method == "POST" and form.is_valid():
        new_quantity = form.cleaned_data["new_quantity"]
        reason = form.cleaned_data.get("adjust_reason", "")
        try:
            if new_quantity != batch.quantity:
                batch = adjust_stock(batch, request.user, new_quantity, reason)
            batch.production_date = form.cleaned_data.get("production_date")
            batch.expiry_date = form.cleaned_data.get("expiry_date")
            batch.save(update_fields=["production_date", "expiry_date", "updated_at"])
        except WorkflowError as exc:
            form.add_error("new_quantity", str(exc))
        else:
            messages.success(request, "库存批次已更新，数量变化已写入调整流水。")
            return redirect("stock_detail", pk=batch.pk)
    return render(
        request,
        "warehouse/stock_form.html",
        {
            "form": form,
            "batch": batch,
            "title": f"编辑库存 · {batch.herb.name} / {batch.batch_no}",
            "is_create": False,
            "active_nav": "stock",
        },
    )


@login_required
def stock_delete(request, pk):
    _require(request.user, "stock.manage")
    if request.method != "POST":
        raise PermissionDenied("请通过页面按钮删除。")
    batch = get_object_or_404(StockBatch, pk=pk)
    if batch.quantity != 0 or batch.movements.exists():
        messages.error(request, "批次仍有库存或已有流水，不能删除。库存差异请使用盘点调整。")
        return redirect("stock_detail", pk=batch.pk)
    no = batch.batch_no
    batch.delete()
    messages.info(request, f"空批次 {no} 已删除。")
    return redirect("stock_list")

