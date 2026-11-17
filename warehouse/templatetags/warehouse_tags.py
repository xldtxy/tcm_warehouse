from decimal import Decimal, InvalidOperation

from django import template
from django.urls import NoReverseMatch, reverse

from ..models import OrderStatus

register = template.Library()

STATUS_LABELS = {choice.value: choice.label for choice in OrderStatus}

MENU_URL_NAMES = {
    "dashboard": "dashboard",
    "herbs": "herb_list",
    "stock": "stock_list",
    "warehouses": "warehouse_list",
    "suppliers": "supplier_list",
    "inbound": "inbound_list",
    "transfer": "transfer_list",
    "outbound": "outbound_list",
    "query": "stock_query",
    "logs": "operation_logs",
    "users": "user_list",
    "roles": "role_permissions",
}


@register.simple_tag
def menu_url(key):
    name = MENU_URL_NAMES.get(key)
    if not name:
        return "#"
    try:
        return reverse(name)
    except NoReverseMatch:
        return "#"


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """在保留当前筛选条件的前提下替换 querystring 参数。"""
    request = context.get("request")
    query = request.GET.copy() if request else {}
    for key, value in kwargs.items():
        if value is None or value == "":
            query.pop(key, None)
        else:
            query[key] = value
    try:
        return query.urlencode()
    except AttributeError:
        return ""


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        try:
            return mapping[key]
        except (KeyError, IndexError, TypeError):
            return None


@register.filter
def status_label(value):
    return STATUS_LABELS.get(value, value or "—")


@register.filter
def qty(value, digits=3):
    """去掉无意义的小数零：10.500 → 10.5。"""
    try:
        number = Decimal(value)
    except (TypeError, ValueError, InvalidOperation):
        return value
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


@register.filter
def signed(value):
    try:
        number = Decimal(value)
    except (TypeError, ValueError, InvalidOperation):
        return value
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.3f}".rstrip("0").rstrip(".")


@register.filter
def divide(value, divisor):
    try:
        return Decimal(value) / Decimal(divisor)
    except (TypeError, ValueError, ZeroDivisionError, InvalidOperation):
        return 0


@register.filter
def percent(value, total):
    try:
        return round(Decimal(value) / Decimal(total) * 100)
    except (TypeError, ValueError, ZeroDivisionError, InvalidOperation):
        return 0
