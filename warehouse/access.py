"""菜单与接口权限的唯一配置来源。

角色仍是四种固定岗位，但每种角色能看到哪些菜单、能调用哪些业务动作，
由数据库中的 :class:`warehouse.models.RolePermission` 配置。没有配置记录时
使用下文的默认值，保证初始化、测试和演示环境开箱即用。
"""
from __future__ import annotations

MENU_GROUPS = [
    {
        "label": "业务工作台",
        "items": [("dashboard", "工作台")],
    },
    {
        "label": "基础资料",
        "items": [
            ("herbs", "药材资料"),
            ("stock", "库存批次"),
            ("warehouses", "仓库与库位"),
            ("suppliers", "供应商"),
        ],
    },
    {
        "label": "业务办理",
        "items": [
            ("inbound", "入库管理"),
            ("transfer", "移库管理"),
            ("outbound", "出库管理"),
        ],
    },
    {
        "label": "查询与审计",
        "items": [
            ("query", "库存查询"),
            ("logs", "操作日志"),
        ],
    },
    {
        "label": "系统管理",
        "items": [
            ("users", "用户管理"),
            ("roles", "角色权限"),
        ],
    },
]

MENU_LABELS = {
    key: label for group in MENU_GROUPS for key, label in group["items"]
}
ALL_MENUS = list(MENU_LABELS)

PERMISSION_GROUPS = [
    {
        "label": "基础资料",
        "items": [
            ("herb.view", "查看药材"),
            ("herb.manage", "维护药材"),
            ("stock.view", "查看库存"),
            ("stock.manage", "维护库存/盘点调整"),
            ("warehouse.manage", "维护仓库与库位"),
            ("supplier.manage", "维护供应商"),
        ],
    },
    {
        "label": "入库管理",
        "items": [
            ("inbound.view", "查看入库单"),
            ("inbound.create", "创建/编辑入库单"),
            ("inbound.audit", "验收入库单"),
            ("inbound.execute", "确认入库"),
        ],
    },
    {
        "label": "移库管理",
        "items": [
            ("transfer.view", "查看移库单"),
            ("transfer.create", "创建/编辑移库单"),
            ("transfer.audit", "审核移库单"),
            ("transfer.execute", "执行移库"),
        ],
    },
    {
        "label": "出库管理",
        "items": [
            ("outbound.view", "查看出库单"),
            ("outbound.create", "创建/编辑出库单"),
            ("outbound.audit", "审核出库单"),
            ("outbound.execute", "执行出库"),
        ],
    },
    {
        "label": "查询与审计",
        "items": [
            ("query.view", "库存查询/统计"),
            ("log.view", "查看操作日志"),
            ("export.data", "导出 CSV / 打印"),
        ],
    },
    {
        "label": "协同操作",
        "items": [
            ("note.manage", "异常备注与附件"),
        ],
    },
    {
        "label": "系统管理",
        "items": [
            ("user.manage", "用户管理"),
            ("role.manage", "角色与权限配置"),
        ],
    },
]

PERMISSION_LABELS = {
    code: label for group in PERMISSION_GROUPS for code, label in group["items"]
}
ALL_PERMISSIONS = list(PERMISSION_LABELS)

_VIEW_PERMISSIONS = {
    "dashboard": [],
    "herbs": ["herb.view"],
    "stock": ["stock.view"],
    "warehouses": ["warehouse.manage"],
    "suppliers": ["supplier.manage"],
    "inbound": ["inbound.view"],
    "transfer": ["transfer.view"],
    "outbound": ["outbound.view"],
    "query": ["query.view"],
    "logs": ["log.view"],
    "users": ["user.manage"],
    "roles": ["role.manage"],
}

MENU_REQUIRED_PERMISSIONS = {
    "dashboard": None,
    "herbs": "herb.view",
    "stock": "stock.view",
    "warehouses": "warehouse.manage",
    "suppliers": "supplier.manage",
    "inbound": "inbound.view",
    "transfer": "transfer.view",
    "outbound": "outbound.view",
    "query": "query.view",
    "logs": "log.view",
    "users": "user.manage",
    "roles": "role.manage",
}


def _all_permissions():
    return {code: True for code in ALL_PERMISSIONS}


DEFAULT_ROLE_CONFIG = {
    "admin": {
        "menus": ALL_MENUS,
        "permissions": _all_permissions(),
    },
    "manager": {
        "menus": [
            "dashboard",
            "herbs",
            "stock",
            "inbound",
            "transfer",
            "outbound",
            "query",
            "logs",
        ],
        "permissions": {
            "herb.view": True,
            "stock.view": True,
            "inbound.view": True,
            "inbound.audit": True,
            "transfer.view": True,
            "transfer.audit": True,
            "outbound.view": True,
            "outbound.audit": True,
            "query.view": True,
            "log.view": True,
            "export.data": True,
            "note.manage": True,
        },
    },
    "keeper": {
        "menus": [
            "dashboard",
            "herbs",
            "stock",
            "warehouses",
            "suppliers",
            "inbound",
            "transfer",
            "outbound",
            "query",
            "logs",
        ],
        "permissions": {
            "herb.view": True,
            "herb.manage": True,
            "stock.view": True,
            "stock.manage": True,
            "warehouse.manage": True,
            "supplier.manage": True,
            "inbound.view": True,
            "inbound.create": True,
            "inbound.execute": True,
            "transfer.view": True,
            "transfer.create": True,
            "transfer.execute": True,
            "outbound.view": True,
            "outbound.create": True,
            "outbound.execute": True,
            "query.view": True,
            "log.view": True,
            "export.data": True,
            "note.manage": True,
        },
    },
    "viewer": {
        "menus": [
            "dashboard",
            "herbs",
            "stock",
            "inbound",
            "transfer",
            "outbound",
            "query",
            "logs",
        ],
        "permissions": {
            "herb.view": True,
            "stock.view": True,
            "inbound.view": True,
            "transfer.view": True,
            "outbound.view": True,
            "query.view": True,
            "log.view": True,
        },
    },
}


def normalize_menu_keys(values):
    return [key for key in ALL_MENUS if key in set(values or [])]


def normalize_permissions(values):
    values = values or {}
    return {code: bool(values.get(code)) for code in ALL_PERMISSIONS}


def default_for_role(role):
    config = DEFAULT_ROLE_CONFIG.get(role, DEFAULT_ROLE_CONFIG["viewer"])
    return {
        "menus": normalize_menu_keys(config["menus"]),
        "permissions": normalize_permissions(config["permissions"]),
    }
