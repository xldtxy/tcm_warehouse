"""岗位、菜单与接口权限判定。

默认值来自 ``access.py``；管理员在“角色权限”页面保存后，以后每次请求读取
``RolePermission`` 中的配置。超级管理员的权限始终全部开启。
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .access import ALL_MENUS, ALL_PERMISSIONS, default_for_role


def is_admin(user):
    return user.is_authenticated and (
        user.is_superuser
        or getattr(getattr(user, "profile", None), "effective_role", "") == "admin"
    )


def get_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return "admin"
    profile = getattr(user, "profile", None)
    return profile.effective_role if profile else "viewer"


def get_access_config(user):
    """返回当前用户角色的菜单与权限；同一请求内缓存。"""
    if not user.is_authenticated:
        return {"menus": [], "permissions": {code: False for code in ALL_PERMISSIONS}}
    cached = getattr(user, "_access_config_cache", None)
    if cached is not None:
        return cached

    role = get_role(user)
    if role == "admin":
        config = {
            "menus": list(ALL_MENUS),
            "permissions": {code: True for code in ALL_PERMISSIONS},
        }
    else:
        from .models import RolePermission

        try:
            record = RolePermission.objects.get(role=role)
            config = {
                "menus": list(record.menus or []),
                "permissions": {
                    code: bool((record.permissions or {}).get(code)) for code in ALL_PERMISSIONS
                },
            }
        except Exception:
            config = default_for_role(role)
    user._access_config_cache = config
    return config


def has_perm(user, code):
    return bool(get_access_config(user)["permissions"].get(code))


def allowed_menus(user):
    return set(get_access_config(user)["menus"])


def can_view_menu(user, menu):
    return menu in allowed_menus(user)


def can_create(user):
    return has_perm(user, "transfer.create") or has_perm(user, "outbound.create")


def can_audit(user):
    return (
        has_perm(user, "transfer.audit")
        or has_perm(user, "outbound.audit")
        or has_perm(user, "inbound.audit")
    )


def can_execute(user):
    return (
        has_perm(user, "transfer.execute")
        or has_perm(user, "outbound.execute")
        or has_perm(user, "inbound.execute")
    )


def can_edit(user, order):
    if not user.is_authenticated:
        return False
    order_type = getattr(order, "order_type", "")
    if order_type and not has_perm(user, f"{order_type}.create"):
        return False
    if is_admin(user):
        return order.is_editable
    return order.is_editable and order.applicant_id == user.id


def can_cancel(user, order):
    if not user.is_authenticated or not order.can_cancel:
        return False
    if is_admin(user):
        return True
    if has_perm(user, f"{getattr(order, 'order_type', '')}.audit"):
        return True
    return order.applicant_id == user.id and order.status in {"draft", "pending"}


def can_annotate(user):
    return has_perm(user, "note.manage")


class WarehouseLoginMixin(LoginRequiredMixin):
    login_url = "login"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "请先登录后再访问业务单据。")
        return super().dispatch(request, *args, **kwargs)


def role_required(check, message="当前岗位无权执行此操作。"):
    """函数视图装饰器；不满足时跳回来源页并提示。"""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if not check(request.user):
                messages.error(request, message)
                return redirect(request.META.get("HTTP_REFERER") or "dashboard")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def permission_required(code, message="当前岗位无权执行此操作。"):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if not has_perm(request.user, code):
                raise PermissionDenied(message)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def require_create(user):
    if not can_create(user):
        raise PermissionDenied("当前岗位无权处理出入库任务。")


def require_audit(user):
    if not can_audit(user):
        raise PermissionDenied("当前岗位无权审核单据。")


def require_execute(user):
    if not can_execute(user):
        raise PermissionDenied("当前岗位无权执行库存操作。")
