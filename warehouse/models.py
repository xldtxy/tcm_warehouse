"""中药仓储库位管理系统数据模型。

覆盖课程五个功能包：
* 学生 1：用户、仓库/库位、角色菜单与接口权限；
* 学生 2：药材与库存批次管理；
* 学生 3：入库单与入库明细；
* 学生 4：移库单、出库单、审核执行与异常附件；
* 学生 5：库存流水、操作轨迹与查询统计。
"""
from __future__ import annotations

import secrets
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class UserProfile(models.Model):
    """扩展 Django 用户，标记仓储岗位角色。"""

    class Role(models.TextChoices):
        ADMIN = "admin", "系统管理员"
        KEEPER = "keeper", "仓管员"
        MANAGER = "manager", "仓库主管"
        VIEWER = "viewer", "只读访客"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="用户",
    )
    role = models.CharField(
        "岗位角色", max_length=16, choices=Role.choices, default=Role.VIEWER
    )
    phone = models.CharField("联系电话", max_length=20, blank=True)
    department = models.CharField("所属部门", max_length=50, blank=True)

    class Meta:
        verbose_name = "用户档案"
        verbose_name_plural = "用户档案"

    def __str__(self):
        return f"{self.display_name}（{self.get_role_display()}）"

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def effective_role(self):
        if self.user.is_superuser:
            return self.Role.ADMIN
        return self.role

    @property
    def can_create(self):
        return self.effective_role in {self.Role.ADMIN, self.Role.KEEPER}

    @property
    def can_audit(self):
        return self.effective_role in {self.Role.ADMIN, self.Role.MANAGER}

    @property
    def can_execute(self):
        return self.effective_role in {self.Role.ADMIN, self.Role.KEEPER}

    @property
    def can_view(self):
        return True


class RolePermission(models.Model):
    """可配置的角色菜单与操作权限。

    角色仍是四种固定岗位，但管理员可以在前端调整每种角色可见菜单、
    可调用的接口/动作。超级管理员的权限始终视为全部开启，避免系统被锁死。
    """

    role = models.CharField(
        "角色", max_length=16, choices=UserProfile.Role.choices, unique=True
    )
    menus = models.JSONField("可见菜单", default=list, blank=True)
    permissions = models.JSONField("接口/操作权限", default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="最后修改人",
    )
    updated_at = models.DateTimeField("最后修改时间", auto_now=True)

    class Meta:
        verbose_name = "角色权限"
        verbose_name_plural = "角色权限"
        ordering = ["role"]

    def __str__(self):
        return self.get_role_display()


class Supplier(models.Model):
    """入库单的供货/调拨来源。"""

    name = models.CharField("供应商名称", max_length=120, unique=True)
    contact = models.CharField("联系人", max_length=40, blank=True)
    phone = models.CharField("联系电话", max_length=30, blank=True)
    address = models.CharField("地址", max_length=200, blank=True)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "供应商"
        verbose_name_plural = "供应商"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Warehouse(models.Model):
    code = models.CharField("仓库编码", max_length=20, unique=True)
    name = models.CharField("仓库名称", max_length=80)
    address = models.CharField("地址", max_length=200, blank=True)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "仓库"
        verbose_name_plural = "仓库"
        ordering = ["code"]

    def __str__(self):
        return f"{self.name}（{self.code}）"


class StorageLocation(models.Model):
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="locations",
        verbose_name="所属仓库",
    )
    code = models.CharField("库位编码", max_length=30)
    name = models.CharField("库位名称", max_length=80, blank=True)
    zone = models.CharField("库区", max_length=30, blank=True)
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "库位"
        verbose_name_plural = "库位"
        ordering = ["warehouse__code", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "code"], name="uniq_location_warehouse_code"
            )
        ]

    def __str__(self):
        return f"{self.warehouse.code}-{self.code}"

    @property
    def full_name(self):
        return f"{self.warehouse.name} / {self.code} {self.name}".strip()


class Herb(models.Model):
    code = models.CharField("药材编码", max_length=30, unique=True)
    name = models.CharField("药材名称", max_length=80)
    spec = models.CharField("规格", max_length=80, blank=True)
    unit = models.CharField("单位", max_length=10, default="kg")
    category = models.CharField("类别", max_length=40, blank=True)
    safety_stock = models.DecimalField(
        "安全库存", max_digits=12, decimal_places=3, default=Decimal("0")
    )
    is_active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "药材"
        verbose_name_plural = "药材"
        ordering = ["code"]

    def __str__(self):
        return f"{self.name}（{self.code}）"


class StockBatchQuerySet(models.QuerySet):
    def available(self):
        return self.filter(quantity__gt=0)


class StockBatch(models.Model):
    """库存按“药材 + 库位 + 批次”维度记录，是库存联动的唯一事实来源。"""

    herb = models.ForeignKey(
        Herb, on_delete=models.PROTECT, related_name="stock_batches", verbose_name="药材"
    )
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="stock_batches",
        verbose_name="库位",
    )
    batch_no = models.CharField("批次号", max_length=50)
    quantity = models.DecimalField(
        "当前库存",
        max_digits=12,
        decimal_places=3,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    production_date = models.DateField("生产日期", null=True, blank=True)
    expiry_date = models.DateField("有效期至", null=True, blank=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects = StockBatchQuerySet.as_manager()

    class Meta:
        verbose_name = "库存批次"
        verbose_name_plural = "库存批次"
        ordering = ["herb__code", "location__code", "batch_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["herb", "location", "batch_no"],
                name="uniq_stock_herb_location_batch",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="stock_quantity_non_negative"
            ),
        ]
        indexes = [
            models.Index(fields=["herb", "location", "batch_no"]),
        ]

    def __str__(self):
        return f"{self.herb.name} / {self.location.code} / {self.batch_no}"

    @property
    def is_low_stock(self):
        return self.quantity <= self.herb.safety_stock


class StockMovement(models.Model):
    """库存流水：每一次库存变化都能回溯到业务单据。"""

    class MovementType(models.TextChoices):
        OPENING = "opening", "期初入库"
        INBOUND = "inbound", "采购入库"
        OUTBOUND = "outbound", "出库扣减"
        TRANSFER_OUT = "transfer_out", "移库移出"
        TRANSFER_IN = "transfer_in", "移库移入"
        ADJUST = "adjust", "盘点调整"

    class OrderType(models.TextChoices):
        INBOUND = "inbound", "入库单"
        TRANSFER = "transfer", "移库单"
        OUTBOUND = "outbound", "出库单"
        MANUAL = "manual", "手工/期初"

    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name="库存批次",
    )
    movement_type = models.CharField(
        "变动类型", max_length=20, choices=MovementType.choices
    )
    quantity = models.DecimalField(
        "变动数量",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    before_quantity = models.DecimalField(
        "变动前", max_digits=12, decimal_places=3
    )
    after_quantity = models.DecimalField("变动后", max_digits=12, decimal_places=3)
    order_type = models.CharField(
        "关联单据类型",
        max_length=16,
        choices=OrderType.choices,
        default=OrderType.MANUAL,
    )
    order_no = models.CharField("关联单号", max_length=24, blank=True)
    order_id = models.PositiveBigIntegerField("关联单据 ID", null=True, blank=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name="操作人",
        null=True,
        blank=True,
    )
    remark = models.CharField("备注", max_length=300, blank=True)
    created_at = models.DateTimeField("发生时间", auto_now_add=True)

    class Meta:
        verbose_name = "库存流水"
        verbose_name_plural = "库存流水"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["batch", "-created_at"]),
            models.Index(fields=["order_type", "order_no"]),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity}"

    @property
    def is_increase(self):
        return self.movement_type in {
            self.MovementType.OPENING,
            self.MovementType.INBOUND,
            self.MovementType.TRANSFER_IN,
        }

    @property
    def signed_quantity(self):
        return self.quantity if self.is_increase else -self.quantity


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    PENDING = "pending", "待审核"
    APPROVED = "approved", "已审核"
    COMPLETED = "completed", "已完成"
    REJECTED = "rejected", "已驳回"
    CANCELLED = "cancelled", "已取消"


STATUS_TONE = {
    OrderStatus.DRAFT: "neutral",
    OrderStatus.PENDING: "warning",
    OrderStatus.APPROVED: "info",
    OrderStatus.COMPLETED: "success",
    OrderStatus.REJECTED: "danger",
    OrderStatus.CANCELLED: "muted",
}


def generate_order_no(prefix: str) -> str:
    """生成人可读且足够唯一的业务单号，例如 YK20261030153201A3F9。"""
    stamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    return f"{prefix}{stamp}{secrets.token_hex(2).upper()}"


class OrderBase(models.Model):
    status = models.CharField(
        "单据状态",
        max_length=16,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
        db_index=True,
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="申请人",
    )
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="审核人",
        null=True,
        blank=True,
    )
    review_comment = models.CharField("审核意见", max_length=300, blank=True)
    exception_note = models.TextField("异常备注", blank=True)
    submitted_at = models.DateTimeField("提交时间", null=True, blank=True)
    audited_at = models.DateTimeField("审核时间", null=True, blank=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True

    @property
    def status_tone(self):
        return STATUS_TONE.get(self.status, "neutral")

    @property
    def is_editable(self):
        return self.status in {OrderStatus.DRAFT, OrderStatus.REJECTED}

    @property
    def is_open(self):
        return self.status in {
            OrderStatus.DRAFT,
            OrderStatus.PENDING,
            OrderStatus.APPROVED,
        }

    @property
    def can_submit(self):
        return self.status in {OrderStatus.DRAFT, OrderStatus.REJECTED}

    @property
    def can_audit(self):
        return self.status == OrderStatus.PENDING

    @property
    def can_complete(self):
        return self.status == OrderStatus.APPROVED

    @property
    def can_cancel(self):
        return self.status in {
            OrderStatus.DRAFT,
            OrderStatus.PENDING,
            OrderStatus.APPROVED,
        }


class TransferOrder(OrderBase):
    """移库单：库位到库位，不改变总库存。"""

    transfer_no = models.CharField(
        "移库单号", max_length=24, unique=True, db_index=True, editable=False
    )
    herb = models.ForeignKey(
        Herb, on_delete=models.PROTECT, related_name="transfers", verbose_name="药材"
    )
    batch_no = models.CharField("批次号", max_length=50)
    from_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="transfers_out",
        verbose_name="移出库位",
    )
    to_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="transfers_in",
        verbose_name="移入库位",
    )
    quantity = models.DecimalField(
        "移库数量",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    reason = models.CharField("移库原因", max_length=300)

    class Meta:
        verbose_name = "移库单"
        verbose_name_plural = "移库单"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["herb", "batch_no"]),
        ]

    def __str__(self):
        return self.transfer_no

    def save(self, *args, **kwargs):
        if not self.transfer_no:
            self.transfer_no = generate_order_no("YK")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("transfer_detail", args=[self.pk])

    @property
    def available_quantity(self):
        batch = StockBatch.objects.filter(
            herb=self.herb, location=self.from_location, batch_no=self.batch_no
        ).first()
        return batch.quantity if batch else Decimal("0")

    @property
    def order_type(self):
        return "transfer"

    @property
    def order_no(self):
        return self.transfer_no


class OutboundOrder(OrderBase):
    """出库单：从指定库位扣减库存并离开仓库。"""

    class OutboundType(models.TextChoices):
        PICK = "pick", "领用出库"
        LOSS = "loss", "报损出库"
        ALLOCATE = "allocate", "调拨出库"
        OTHER = "other", "其他出库"

    outbound_no = models.CharField(
        "出库单号", max_length=24, unique=True, db_index=True, editable=False
    )
    outbound_type = models.CharField(
        "出库类型",
        max_length=16,
        choices=OutboundType.choices,
        default=OutboundType.PICK,
    )
    herb = models.ForeignKey(
        Herb, on_delete=models.PROTECT, related_name="outbounds", verbose_name="药材"
    )
    batch_no = models.CharField("批次号", max_length=50)
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="outbounds",
        verbose_name="出库库位",
    )
    quantity = models.DecimalField(
        "出库数量",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    recipient = models.CharField("领用人 / 去向", max_length=80)
    purpose = models.CharField("出库用途", max_length=300)

    class Meta:
        verbose_name = "出库单"
        verbose_name_plural = "出库单"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["herb", "batch_no"]),
        ]

    def __str__(self):
        return self.outbound_no

    def save(self, *args, **kwargs):
        if not self.outbound_no:
            self.outbound_no = generate_order_no("CK")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("outbound_detail", args=[self.pk])

    @property
    def available_quantity(self):
        batch = StockBatch.objects.filter(
            herb=self.herb, location=self.location, batch_no=self.batch_no
        ).first()
        return batch.quantity if batch else Decimal("0")

    @property
    def order_type(self):
        return "outbound"

    @property
    def order_no(self):
        return self.outbound_no


class InboundOrder(OrderBase):
    """入库单：一次采购/调拨可包含多个药材批次明细。"""

    inbound_no = models.CharField(
        "入库单号", max_length=24, unique=True, db_index=True, editable=False
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="inbound_orders",
        verbose_name="供应来源",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="inbound_orders",
        verbose_name="入库仓库",
    )
    inbound_date = models.DateField("入库日期", default=timezone.localdate)
    invoice_no = models.CharField("随货同行单号", max_length=60, blank=True)
    remark = models.TextField("入库说明", blank=True)

    class Meta:
        verbose_name = "入库单"
        verbose_name_plural = "入库单"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["warehouse", "inbound_date"]),
        ]

    def __str__(self):
        return self.inbound_no

    def save(self, *args, **kwargs):
        if not self.inbound_no:
            self.inbound_no = generate_order_no("RK")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("inbound_detail", args=[self.pk])

    @property
    def order_type(self):
        return "inbound"

    @property
    def order_no(self):
        return self.inbound_no

    @property
    def total_quantity(self):
        return sum((item.quantity for item in self.items.all()), Decimal("0"))

    @property
    def total_amount(self):
        return sum((item.subtotal for item in self.items.all()), Decimal("0"))

    @property
    def status_label(self):
        if self.status == OrderStatus.PENDING:
            return "待验收"
        if self.status == OrderStatus.APPROVED:
            return "验收通过"
        return self.get_status_display()


class InboundItem(models.Model):
    """入库单明细：药材 + 批次 + 目标库位 + 数量/单价。"""

    order = models.ForeignKey(
        InboundOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="入库单",
    )
    herb = models.ForeignKey(
        Herb, on_delete=models.PROTECT, related_name="inbound_items", verbose_name="药材"
    )
    batch_no = models.CharField("批次号", max_length=50)
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="inbound_items",
        verbose_name="入库库位",
    )
    quantity = models.DecimalField(
        "数量",
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    unit_price = models.DecimalField(
        "单价（元）",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    production_date = models.DateField("生产日期", null=True, blank=True)
    expiry_date = models.DateField("有效期至", null=True, blank=True)
    remark = models.CharField("明细备注", max_length=200, blank=True)

    class Meta:
        verbose_name = "入库明细"
        verbose_name_plural = "入库明细"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "herb", "batch_no", "location"],
                name="uniq_inbound_item_herb_batch_location",
            )
        ]
        indexes = [
            models.Index(fields=["order", "herb"]),
            models.Index(fields=["batch_no"]),
        ]

    def __str__(self):
        return f"{self.order.inbound_no} / {self.herb.name} / {self.batch_no}"

    @property
    def subtotal(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


class OrderStatusLog(models.Model):
    """跨入库、移库、出库单据统一记录操作轨迹。"""

    class OrderType(models.TextChoices):
        INBOUND = "inbound", "入库单"
        TRANSFER = "transfer", "移库单"
        OUTBOUND = "outbound", "出库单"

    class Action(models.TextChoices):
        CREATE = "create", "创建单据"
        SUBMIT = "submit", "提交审核"
        APPROVE = "approve", "审核通过"
        REJECT = "reject", "审核驳回"
        COMPLETE = "complete", "确认完成"
        CANCEL = "cancel", "取消单据"
        EXCEPTION = "exception", "记录异常"
        UPDATE = "update", "编辑单据"
        ATTACH = "attach", "上传附件"
        DELETE_ATTACH = "delete_attach", "删除附件"

    order_type = models.CharField("单据类型", max_length=16, choices=OrderType.choices)
    order_id = models.PositiveBigIntegerField("单据 ID")
    order_no = models.CharField("单据编号", max_length=24)
    action = models.CharField("操作", max_length=20, choices=Action.choices)
    from_status = models.CharField("原状态", max_length=16, blank=True)
    to_status = models.CharField("新状态", max_length=16, blank=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name="操作人",
        null=True,
        blank=True,
    )
    comment = models.CharField("说明", max_length=500, blank=True)
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        verbose_name = "单据操作记录"
        verbose_name_plural = "单据操作记录"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["order_type", "order_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.order_no} - {self.get_action_display()}"

    @property
    def from_status_label(self):
        if self.order_type == self.OrderType.INBOUND:
            labels = {
                OrderStatus.PENDING: "待验收",
                OrderStatus.APPROVED: "验收通过",
            }
        else:
            labels = {}
        return labels.get(self.from_status) or dict(OrderStatus.choices).get(
            self.from_status, self.from_status or "—"
        )

    @property
    def to_status_label(self):
        if self.order_type == self.OrderType.INBOUND:
            labels = {
                OrderStatus.PENDING: "待验收",
                OrderStatus.APPROVED: "验收通过",
            }
        else:
            labels = {}
        return labels.get(self.to_status) or dict(OrderStatus.choices).get(
            self.to_status, self.to_status or "—"
        )

    @classmethod
    def record(cls, order, action, operator, comment="", from_status="", to_status=""):
        if isinstance(order, InboundOrder):
            order_type = cls.OrderType.INBOUND
        elif isinstance(order, TransferOrder):
            order_type = cls.OrderType.TRANSFER
        else:
            order_type = cls.OrderType.OUTBOUND
        return cls.objects.create(
            order_type=order_type,
            order_id=order.pk,
            order_no=order.order_no,
            action=action,
            from_status=from_status,
            to_status=to_status or order.status,
            operator=operator,
            comment=comment,
        )

    @classmethod
    def for_order(cls, order):
        if isinstance(order, InboundOrder):
            order_type = cls.OrderType.INBOUND
        elif isinstance(order, TransferOrder):
            order_type = cls.OrderType.TRANSFER
        else:
            order_type = cls.OrderType.OUTBOUND
        return cls.objects.filter(order_type=order_type, order_id=order.pk).select_related(
            "operator", "operator__profile"
        )


def attachment_upload_to(instance, filename):
    suffix = Path(filename).suffix.lower()
    return (
        f"order_attachments/{timezone.localdate():%Y/%m}/"
        f"{secrets.token_hex(8)}{suffix}"
    )


def validate_attachment_size(value):
    if value.size > 5 * 1024 * 1024:
        raise ValidationError("附件不能超过 5 MB。")


class OrderAttachment(models.Model):
    """移库/出库单据共用的附件表，一条记录只属于其中一张单据。"""

    transfer = models.ForeignKey(
        TransferOrder,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="移库单",
        null=True,
        blank=True,
    )
    outbound = models.ForeignKey(
        OutboundOrder,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="出库单",
        null=True,
        blank=True,
    )
    file = models.FileField(
        "附件",
        upload_to=attachment_upload_to,
        validators=[
            FileExtensionValidator(
                ["pdf", "png", "jpg", "jpeg", "webp", "doc", "docx", "xls", "xlsx"]
            ),
            validate_attachment_size,
        ],
    )
    original_name = models.CharField("原始文件名", max_length=255)
    note = models.CharField("附件说明", max_length=200, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name="上传人",
        related_name="+",
    )
    created_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        verbose_name = "单据附件"
        verbose_name_plural = "单据附件"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.original_name

    def clean(self):
        if bool(self.transfer_id) == bool(self.outbound_id):
            raise ValidationError("附件必须且只能关联一张移库单或出库单。")

    @property
    def size_display(self):
        try:
            size = self.file.size
        except (OSError, ValueError):
            return "—"
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1024 / 1024:.1f} MB"

    @property
    def is_image(self):
        return Path(self.file.name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
