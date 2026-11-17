"""学生 1：注册、用户、仓库/库位、供应商与角色权限配置。"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from .access import (
    MENU_GROUPS,
    MENU_REQUIRED_PERMISSIONS,
    PERMISSION_GROUPS,
    default_for_role,
    normalize_menu_keys,
)
from .forms import (
    AdminUserCreateForm,
    AdminUserEditForm,
    RegistrationForm,
    StorageLocationForm,
    SupplierForm,
    WarehouseForm,
)
from .models import (
    InboundItem,
    InboundOrder,
    OutboundOrder,
    RolePermission,
    StorageLocation,
    StockBatch,
    Supplier,
    TransferOrder,
    UserProfile,
    Warehouse,
)
from .permissions import has_perm, is_admin


def _require(user, code):
    if not has_perm(user, code):
        raise PermissionDenied("当前岗位没有该功能权限。")


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(
            request, f"账号 {user.username} 注册成功，请登录后联系管理员分配岗位权限。"
        )
        return redirect("login")
    return render(request, "registration/signup.html", {"form": form})


# ---------------------------------------------------------------------------
# 用户管理
# ---------------------------------------------------------------------------
@login_required
def user_list(request):
    _require(request.user, "user.manage")
    qs = get_user_model().objects.select_related("profile").order_by("-date_joined")
    q = (request.GET.get("q") or "").strip()
    role = (request.GET.get("role") or "").strip()
    active = (request.GET.get("active") or "").strip()
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(email__icontains=q)
            | Q(profile__phone__icontains=q)
        )
    if role:
        qs = qs.filter(profile__role=role)
    if active == "1":
        qs = qs.filter(is_active=True)
    elif active == "0":
        qs = qs.filter(is_active=False)
    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))
    return render(
        request,
        "warehouse/user_list.html",
        {
            "page_obj": page_obj,
            "users": page_obj.object_list,
            "role_choices": UserProfile.Role.choices,
            "role_counts": {
                row["profile__role"]: row["total"]
                for row in get_user_model()
                .objects.values("profile__role")
                .annotate(total=Count("id"))
            },
            "filters": {"q": q, "role": role, "active": active},
            "active_nav": "users",
        },
    )


@login_required
def user_create(request):
    _require(request.user, "user.manage")
    form = AdminUserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"用户 {user.username} 已创建。")
        return redirect("user_list")
    return render(
        request,
        "warehouse/user_form.html",
        {
            "form": form,
            "title": "新建用户",
            "active_nav": "users",
            "is_create": True,
        },
    )


@login_required
def user_edit(request, pk):
    _require(request.user, "user.manage")
    user = get_object_or_404(get_user_model().objects.select_related("profile"), pk=pk)
    form = AdminUserEditForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        if user == request.user and not form.cleaned_data.get("is_active"):
            form.add_error("is_active", "不能停用当前正在登录的账号。")
        else:
            form.save()
            messages.success(request, f"用户 {user.username} 已更新。")
            return redirect("user_list")
    return render(
        request,
        "warehouse/user_form.html",
        {
            "form": form,
            "title": "编辑用户",
            "edit_user": user,
            "active_nav": "users",
            "is_create": False,
        },
    )


# ---------------------------------------------------------------------------
# 仓库与库位
# ---------------------------------------------------------------------------
@login_required
def warehouse_list(request):
    _require(request.user, "warehouse.manage")
    warehouses = Warehouse.objects.prefetch_related(
        "locations", "locations__stock_batches"
    ).order_by("code")
    return render(
        request,
        "warehouse/warehouse_list.html",
        {"warehouses": warehouses, "active_nav": "warehouses"},
    )


@login_required
def warehouse_create(request):
    _require(request.user, "warehouse.manage")
    form = WarehouseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        warehouse = form.save()
        messages.success(request, f"仓库 {warehouse.name} 已创建。")
        return redirect("warehouse_list")
    return render(
        request,
        "warehouse/simple_form.html",
        {
            "form": form,
            "title": "新建仓库",
            "subtitle": "仓库是库位、入库单和移库单的归属单位。",
            "active_nav": "warehouses",
        },
    )


@login_required
def warehouse_edit(request, pk):
    _require(request.user, "warehouse.manage")
    warehouse = get_object_or_404(Warehouse, pk=pk)
    form = WarehouseForm(request.POST or None, instance=warehouse)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "仓库信息已更新。")
        return redirect("warehouse_list")
    return render(
        request,
        "warehouse/simple_form.html",
        {
            "form": form,
            "title": f"编辑仓库 · {warehouse.name}",
            "subtitle": warehouse.code,
            "active_nav": "warehouses",
        },
    )


@login_required
def warehouse_delete(request, pk):
    _require(request.user, "warehouse.manage")
    if request.method != "POST":
        raise PermissionDenied("请通过页面按钮删除。")
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if (
        warehouse.locations.exists()
        or warehouse.inbound_orders.exists()
        or StockBatch.objects.filter(location__warehouse=warehouse).exists()
    ):
        messages.error(request, "仓库下还有库位、库存或入库单，请先处理后再删除。")
    else:
        warehouse.delete()
        messages.info(request, "仓库已删除。")
    return redirect("warehouse_list")


@login_required
def location_create(request):
    _require(request.user, "warehouse.manage")
    initial = {}
    warehouse_id = request.GET.get("warehouse")
    if warehouse_id and warehouse_id.isdigit():
        initial["warehouse"] = Warehouse.objects.filter(pk=warehouse_id).first()
    form = StorageLocationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        location = form.save()
        messages.success(request, f"库位 {location.code} 已创建。")
        return redirect("warehouse_list")
    return render(
        request,
        "warehouse/simple_form.html",
        {
            "form": form,
            "title": "新建库位",
            "subtitle": "库位编码在同一个仓库内唯一。",
            "active_nav": "warehouses",
        },
    )


@login_required
def location_edit(request, pk):
    _require(request.user, "warehouse.manage")
    location = get_object_or_404(StorageLocation, pk=pk)
    form = StorageLocationForm(request.POST or None, instance=location)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "库位信息已更新。")
        return redirect("warehouse_list")
    return render(
        request,
        "warehouse/simple_form.html",
        {
            "form": form,
            "title": f"编辑库位 · {location.full_name}",
            "subtitle": location.warehouse.name,
            "active_nav": "warehouses",
        },
    )


@login_required
def location_delete(request, pk):
    _require(request.user, "warehouse.manage")
    if request.method != "POST":
        raise PermissionDenied("请通过页面按钮删除。")
    location = get_object_or_404(StorageLocation, pk=pk)
    if (
        location.stock_batches.exists()
        or location.inbound_items.exists()
        or location.transfers_out.exists()
        or location.transfers_in.exists()
        or location.outbounds.exists()
    ):
        messages.error(request, "库位已关联库存或业务单据，不能删除，可改为停用。")
    else:
        location.delete()
        messages.info(request, "库位已删除。")
    return redirect("warehouse_list")


# ---------------------------------------------------------------------------
# 供应商
# ---------------------------------------------------------------------------
@login_required
def supplier_list(request):
    _require(request.user, "supplier.manage")
    qs = Supplier.objects.annotate(inbound_count=Count("inbound_orders")).order_by("name")
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(contact__icontains=q) | Q(phone__icontains=q)
        )
    page_obj = Paginator(qs, 12).get_page(request.GET.get("page"))
    return render(
        request,
        "warehouse/supplier_list.html",
        {
            "page_obj": page_obj,
            "suppliers": page_obj.object_list,
            "q": q,
            "active_nav": "suppliers",
        },
    )


@login_required
def supplier_create(request):
    _require(request.user, "supplier.manage")
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "供应商已创建。")
        return redirect("supplier_list")
    return render(
        request,
        "warehouse/simple_form.html",
        {
            "form": form,
            "title": "新建供应商",
            "subtitle": "供应商用于入库单的货源追溯。",
            "active_nav": "suppliers",
        },
    )


@login_required
def supplier_edit(request, pk):
    _require(request.user, "supplier.manage")
    supplier = get_object_or_404(Supplier, pk=pk)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "供应商信息已更新。")
        return redirect("supplier_list")
    return render(
        request,
        "warehouse/simple_form.html",
        {
            "form": form,
            "title": f"编辑供应商 · {supplier.name}",
            "subtitle": supplier.contact,
            "active_nav": "suppliers",
        },
    )


@login_required
def supplier_delete(request, pk):
    _require(request.user, "supplier.manage")
    if request.method != "POST":
        raise PermissionDenied("请通过页面按钮删除。")
    supplier = get_object_or_404(Supplier, pk=pk)
    if supplier.inbound_orders.exists():
        messages.error(request, "该供应商已有入库记录，不能删除，可改为停用。")
    else:
        supplier.delete()
        messages.info(request, "供应商已删除。")
    return redirect("supplier_list")


# ---------------------------------------------------------------------------
# 角色 / 菜单 / 接口权限
# ---------------------------------------------------------------------------
@login_required
def role_permissions(request):
    _require(request.user, "role.manage")
    selected_role = request.POST.get("role") or request.GET.get("role") or "keeper"
    if selected_role not in dict(UserProfile.Role.choices):
        selected_role = "keeper"

    if request.method == "POST":
        menus = normalize_menu_keys(request.POST.getlist("menus"))
        permissions = {
            code: bool(request.POST.get(f"perm_{code}"))
            for group in PERMISSION_GROUPS
            for code, _label in group["items"]
        }
        # 菜单必须至少具备可打开它的查看权限，避免配置出自相矛盾的入口。
        for menu in menus:
            required = MENU_REQUIRED_PERMISSIONS.get(menu)
            if required:
                permissions[required] = True
        RolePermission.objects.update_or_create(
            role=selected_role,
            defaults={
                "menus": menus,
                "permissions": permissions,
                "updated_by": request.user,
            },
        )
        messages.success(
            request, f"{dict(UserProfile.Role.choices)[selected_role]} 的权限配置已保存。"
        )
        return redirect(f"{request.path}?role={selected_role}")

    record = RolePermission.objects.filter(role=selected_role).first()
    if record:
        selected_menus = set(record.menus or [])
        selected_perms = record.permissions or {}
        updated_by = record.updated_by
        updated_at = record.updated_at
    else:
        default = default_for_role(selected_role)
        selected_menus = set(default["menus"])
        selected_perms = default["permissions"]
        updated_by = None
        updated_at = None

    role_stats = {
        row["profile__role"]: row["total"]
        for row in get_user_model()
        .objects.values("profile__role")
        .annotate(total=Count("id"))
    }
    return render(
        request,
        "warehouse/role_permissions.html",
        {
            "role_choices": UserProfile.Role.choices,
            "selected_role": selected_role,
            "selected_role_label": dict(UserProfile.Role.choices)[selected_role],
            "selected_menus": selected_menus,
            "selected_perms": selected_perms,
            "menu_groups": MENU_GROUPS,
            "permission_groups": PERMISSION_GROUPS,
            "role_stats": role_stats,
            "updated_by": updated_by,
            "updated_at": updated_at,
            "is_superuser_role": selected_role == "admin",
            "active_nav": "roles",
        },
    )
