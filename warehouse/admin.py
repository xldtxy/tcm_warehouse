from django.contrib import admin

from .models import (
    Herb,
    InboundItem,
    InboundOrder,
    OrderAttachment,
    OrderStatusLog,
    OutboundOrder,
    RolePermission,
    StockBatch,
    StockMovement,
    StorageLocation,
    Supplier,
    TransferOrder,
    UserProfile,
    Warehouse,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "department", "phone")
    list_filter = ("role", "department")
    search_fields = ("user__username", "user__first_name", "phone")


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "address", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "warehouse", "zone", "is_active")
    list_filter = ("warehouse", "zone", "is_active")
    search_fields = ("code", "name")


@admin.register(Herb)
class HerbAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "spec", "unit", "safety_stock", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ("herb", "location", "batch_no", "quantity", "updated_at")
    list_filter = ("location__warehouse", "location")
    search_fields = ("herb__name", "herb__code", "batch_no")


class ImmutableAdminMixin:
    """业务单据与审计表只读，避免绕过前端状态机直接改库。"""

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "batch",
        "movement_type",
        "quantity",
        "before_quantity",
        "after_quantity",
        "order_no",
        "operator",
        "created_at",
    )
    list_filter = ("movement_type", "order_type")
    search_fields = ("order_no", "batch__herb__name", "batch__batch_no")


@admin.register(TransferOrder)
class TransferOrderAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "transfer_no",
        "herb",
        "batch_no",
        "from_location",
        "to_location",
        "quantity",
        "status",
        "applicant",
        "created_at",
    )
    list_filter = ("status", "from_location__warehouse")
    search_fields = ("transfer_no", "herb__name", "batch_no")


@admin.register(OutboundOrder)
class OutboundOrderAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "outbound_no",
        "outbound_type",
        "herb",
        "batch_no",
        "location",
        "quantity",
        "status",
        "applicant",
        "created_at",
    )
    list_filter = ("status", "outbound_type", "location__warehouse")
    search_fields = ("outbound_no", "herb__name", "batch_no", "recipient")


@admin.register(OrderStatusLog)
class OrderStatusLogAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "order_no",
        "order_type",
        "action",
        "from_status",
        "to_status",
        "operator",
        "created_at",
    )
    list_filter = ("order_type", "action")
    search_fields = ("order_no", "comment")


@admin.register(OrderAttachment)
class OrderAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "transfer", "outbound", "uploaded_by", "created_at")
    search_fields = ("original_name", "note")
    readonly_fields = ("created_at", "original_name", "uploaded_by")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact", "phone")


class InboundItemInline(admin.TabularInline):
    model = InboundItem
    extra = 0


@admin.register(InboundOrder)
class InboundOrderAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = (
        "inbound_no",
        "supplier",
        "warehouse",
        "inbound_date",
        "status",
        "applicant",
    )
    list_filter = ("status", "warehouse")
    search_fields = ("inbound_no", "supplier__name", "invoice_no")
    inlines = [InboundItemInline]


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "updated_by", "updated_at")
    readonly_fields = ("updated_at",)


admin.site.site_header = "中药仓储库位管理系统 · 后台"
admin.site.site_title = "中药仓储管理"
admin.site.index_title = "基础数据与业务单据"
