"""导航、权限与待办数量的模板上下文。"""
from .access import MENU_GROUPS
from .models import InboundOrder, OrderStatus, OutboundOrder, TransferOrder
from .permissions import (
    allowed_menus,
    can_audit,
    can_create,
    can_execute,
    get_access_config,
    has_perm,
)


def workbench(request):
    """给侧边栏、顶栏和操作按钮提供菜单/权限/待办数。"""
    if not request.user.is_authenticated:
        return {}

    menus = allowed_menus(request.user)
    perms = get_access_config(request.user)["permissions"]

    visible_groups = []
    for group in MENU_GROUPS:
        items = [(key, label) for key, label in group["items"] if key in menus]
        if items:
            visible_groups.append({"label": group["label"], "items": items})

    pending_transfers = pending_outbounds = pending_inbounds = 0
    if has_perm(request.user, "transfer.view"):
        pending_transfers = TransferOrder.objects.filter(
            status=OrderStatus.PENDING
        ).count()
    if has_perm(request.user, "outbound.view"):
        pending_outbounds = OutboundOrder.objects.filter(
            status=OrderStatus.PENDING
        ).count()
    if has_perm(request.user, "inbound.view"):
        pending_inbounds = InboundOrder.objects.filter(
            status=OrderStatus.PENDING
        ).count()

    return {
        "allowed_menus": menus,
        "role_permissions": perms,
        "nav_groups": visible_groups,
        "nav_pending_transfers": pending_transfers,
        "nav_pending_outbounds": pending_outbounds,
        "nav_pending_inbounds": pending_inbounds,
        "can_any_create": can_create(request.user),
        "can_any_audit": can_audit(request.user),
        "can_any_execute": can_execute(request.user),
    }
