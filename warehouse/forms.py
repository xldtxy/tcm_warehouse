"""全系统表单与统一控件样式。"""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.forms import inlineformset_factory

from .models import (
    Herb,
    InboundItem,
    InboundOrder,
    OrderAttachment,
    OutboundOrder,
    StorageLocation,
    StockBatch,
    Supplier,
    TransferOrder,
    UserProfile,
    Warehouse,
)


class StyledFormMixin:
    """给所有字段统一加上前端样式，避免模板里逐个手写。"""

    def _style_fields(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault("class", "form-file")
            else:
                widget.attrs.setdefault("class", "form-input")
            if field.required:
                widget.attrs.setdefault("required", "required")


class TransferOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TransferOrder
        fields = ["herb", "batch_no", "from_location", "to_location", "quantity", "reason"]
        widgets = {
            "batch_no": forms.TextInput(
                attrs={
                    "placeholder": "输入或选择批次号",
                    "list": "transfer-batch-options",
                    "autocomplete": "off",
                }
            ),
            "quantity": forms.NumberInput(
                attrs={"step": "0.001", "min": "0.001", "placeholder": "例如 10.5"}
            ),
            "reason": forms.TextInput(
                attrs={"placeholder": "例如：货架调整、就近存放、批次合并"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["herb"].queryset = Herb.objects.filter(is_active=True)
        self.fields["from_location"].queryset = StorageLocation.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse")
        self.fields["to_location"].queryset = self.fields["from_location"].queryset
        self.fields["herb"].empty_label = "请选择药材"
        self.fields["from_location"].empty_label = "请选择移出库位"
        self.fields["to_location"].empty_label = "请选择移入库位"
        self.fields["quantity"].widget.attrs.update(
            {
                "data-stock-herb": "id_herb",
                "data-stock-location": "id_from_location",
            }
        )
        self._style_fields()

    def clean_batch_no(self):
        value = (self.cleaned_data.get("batch_no") or "").strip()
        if not value:
            raise forms.ValidationError("请填写批次号。")
        return value

    def clean(self):
        cleaned = super().clean()
        herb = cleaned.get("herb")
        batch_no = cleaned.get("batch_no")
        source = cleaned.get("from_location")
        target = cleaned.get("to_location")
        quantity = cleaned.get("quantity")

        if source and target and source.pk == target.pk:
            self.add_error("to_location", "移入库位不能与移出库位相同。")
        if source and target and source.warehouse_id != target.warehouse_id:
            self.add_error("to_location", "移库单只能在同一个仓库内的库位之间移动。")
        if quantity is not None and quantity <= 0:
            self.add_error("quantity", "移库数量必须大于 0。")

        if herb and batch_no and source and quantity:
            from .models import StockBatch

            stock = StockBatch.objects.filter(
                herb=herb, location=source, batch_no=batch_no
            ).first()
            if not stock:
                self.add_error(
                    "batch_no",
                    "该库位下没有这个批次的库存，请核对药材、库位和批次。",
                )
            elif stock.quantity < quantity:
                self.add_error(
                    "quantity",
                    f"源库位当前仅 {stock.quantity}，不能提交超过库存的数量。",
                )
        return cleaned


class OutboundOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OutboundOrder
        fields = [
            "outbound_type",
            "herb",
            "batch_no",
            "location",
            "quantity",
            "recipient",
            "purpose",
        ]
        widgets = {
            "batch_no": forms.TextInput(
                attrs={
                    "placeholder": "输入或选择批次号",
                    "list": "outbound-batch-options",
                    "autocomplete": "off",
                }
            ),
            "quantity": forms.NumberInput(
                attrs={"step": "0.001", "min": "0.001", "placeholder": "例如 5"}
            ),
            "recipient": forms.TextInput(
                attrs={"placeholder": "例如：制剂室 / 张医师 / 报损销毁"}
            ),
            "purpose": forms.TextInput(
                attrs={"placeholder": "说明出库用途，便于审计追溯"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["herb"].queryset = Herb.objects.filter(is_active=True)
        self.fields["location"].queryset = StorageLocation.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse")
        self.fields["herb"].empty_label = "请选择药材"
        self.fields["location"].empty_label = "请选择出库库位"
        self.fields["quantity"].widget.attrs.update(
            {
                "data-stock-herb": "id_herb",
                "data-stock-location": "id_location",
            }
        )
        self._style_fields()

    def clean_batch_no(self):
        value = (self.cleaned_data.get("batch_no") or "").strip()
        if not value:
            raise forms.ValidationError("请填写批次号。")
        return value

    def clean(self):
        cleaned = super().clean()
        herb = cleaned.get("herb")
        batch_no = cleaned.get("batch_no")
        location = cleaned.get("location")
        quantity = cleaned.get("quantity")
        if quantity is not None and quantity <= 0:
            self.add_error("quantity", "出库数量必须大于 0。")

        if herb and batch_no and location and quantity:
            from .models import StockBatch

            stock = StockBatch.objects.filter(
                herb=herb, location=location, batch_no=batch_no
            ).first()
            if not stock:
                self.add_error(
                    "batch_no", "该库位下没有这个批次的库存，请核对后重试。"
                )
            elif stock.quantity < quantity:
                self.add_error(
                    "quantity",
                    f"出库库位当前仅 {stock.quantity}，不能提交超过库存的数量。",
                )
        return cleaned


class ReviewForm(forms.Form):
    comment = forms.CharField(
        label="审核意见",
        required=False,
        max_length=300,
        widget=forms.Textarea(
            attrs={
                "class": "form-input",
                "rows": 3,
                "placeholder": "填写审核意见（驳回时必填）",
            }
        ),
    )


class RejectForm(forms.Form):
    comment = forms.CharField(
        label="驳回原因",
        required=True,
        min_length=2,
        max_length=300,
        widget=forms.Textarea(
            attrs={
                "class": "form-input",
                "rows": 3,
                "placeholder": "请说明数量、批次或手续存在的问题",
            }
        ),
    )


class CancelForm(forms.Form):
    reason = forms.CharField(
        label="取消原因",
        required=False,
        max_length=300,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "可选，记录取消原因"}
        ),
    )


class ExceptionForm(forms.Form):
    note = forms.CharField(
        label="异常备注",
        required=True,
        min_length=2,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "class": "form-input",
                "rows": 3,
                "placeholder": "例如：移入库位货架临时占用，已与主管确认暂缓执行。",
            }
        ),
    )


class AttachmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OrderAttachment
        fields = ["file", "note"]
        widgets = {
            "file": forms.ClearableFileInput(
                attrs={"accept": ".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx,.xls,.xlsx"}
            ),
            "note": forms.TextInput(
                attrs={"placeholder": "可选，例如：温湿度异常照片、交接单扫描件"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].required = True
        self._style_fields()

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError("附件不能超过 5 MB。")
        return upload

# ---------------------------------------------------------------------------
# 学生 1：注册 / 用户 / 仓库 / 供应商
# ---------------------------------------------------------------------------
class RegistrationForm(StyledFormMixin, UserCreationForm):
    first_name = forms.CharField(label="姓名", max_length=50, required=True)
    email = forms.EmailField(label="邮箱", required=False)
    phone = forms.CharField(label="联系电话", max_length=20, required=False)
    department = forms.CharField(label="部门", max_length=50, required=False)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "登录账号"
        self.fields["password1"].label = "密码"
        self.fields["password2"].label = "确认密码"
        self.fields["username"].help_text = "4-150 个字符，可使用字母、数字和 @/./+/-/_。"
        self.fields["password1"].help_text = "至少 8 位，不能是纯数字。"
        self.fields["password2"].help_text = "请再次输入密码。"
        self._style_fields()

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.Role.VIEWER
            profile.phone = self.cleaned_data.get("phone", "")
            profile.department = self.cleaned_data.get("department", "")
            profile.save()
        return user


class AdminUserCreateForm(StyledFormMixin, UserCreationForm):
    role = forms.ChoiceField(label="岗位角色", choices=UserProfile.Role.choices)
    phone = forms.CharField(label="联系电话", max_length=20, required=False)
    department = forms.CharField(label="部门", max_length=50, required=False)
    is_active = forms.BooleanField(label="启用账号", initial=True, required=False)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "first_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "登录账号"
        self.fields["first_name"].label = "姓名"
        self.fields["password1"].label = "初始密码"
        self.fields["password2"].label = "确认密码"
        self._style_fields()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = self.cleaned_data.get("is_active", True)
        user.is_staff = self.cleaned_data.get("role") == UserProfile.Role.ADMIN
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data["role"]
            profile.phone = self.cleaned_data.get("phone", "")
            profile.department = self.cleaned_data.get("department", "")
            profile.save()
        return user


class AdminUserEditForm(StyledFormMixin, forms.ModelForm):
    role = forms.ChoiceField(label="岗位角色", choices=UserProfile.Role.choices)
    phone = forms.CharField(label="联系电话", max_length=20, required=False)
    department = forms.CharField(label="部门", max_length=50, required=False)
    new_password1 = forms.CharField(
        label="重置密码（可选）",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    new_password2 = forms.CharField(
        label="确认新密码",
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "first_name", "email", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].disabled = True
        self.fields["first_name"].label = "姓名"
        profile = getattr(self.instance, "profile", None)
        if profile and not self.is_bound:
            self.initial.setdefault("role", profile.role)
            self.initial.setdefault("phone", profile.phone)
            self.initial.setdefault("department", profile.department)
        self._style_fields()

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", "两次输入的密码不一致。")
            elif len(p1) < 8:
                self.add_error("new_password1", "密码至少 8 位。")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            if self.cleaned_data.get("new_password1"):
                user.set_password(self.cleaned_data["new_password1"])
                user.save(update_fields=["password"])
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data["role"]
            profile.phone = self.cleaned_data.get("phone", "")
            profile.department = self.cleaned_data.get("department", "")
            profile.save()
            if not user.is_superuser:
                user.is_staff = profile.role == UserProfile.Role.ADMIN
                user.save(update_fields=["is_staff"])
        return user


class WarehouseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name", "address", "is_active"]
        widgets = {"address": forms.TextInput(attrs={"placeholder": "例如：教学实训楼 B1 层"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip().upper()


class StorageLocationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StorageLocation
        fields = ["warehouse", "code", "name", "zone", "is_active"]
        widgets = {"zone": forms.TextInput(attrs={"placeholder": "例如：阴凉区 / 常温区"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)
        self._style_fields()

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip().upper()


class SupplierForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact", "phone", "address", "is_active"]
        widgets = {"address": forms.TextInput(attrs={"placeholder": "可选"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


# ---------------------------------------------------------------------------
# 学生 2：药材 / 库存批次
# ---------------------------------------------------------------------------
class HerbForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Herb
        fields = ["code", "name", "spec", "unit", "category", "safety_stock", "is_active"]
        widgets = {
            "spec": forms.TextInput(attrs={"placeholder": "例如：统片 / 全归片"}),
            "unit": forms.TextInput(attrs={"placeholder": "kg"}),
            "category": forms.TextInput(attrs={"placeholder": "例如：补气类"}),
            "safety_stock": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].initial = self.fields["unit"].initial or "kg"
        self._style_fields()

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip().upper()


class StockBatchCreateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StockBatch
        fields = [
            "herb",
            "location",
            "batch_no",
            "quantity",
            "production_date",
            "expiry_date",
        ]
        widgets = {
            "batch_no": forms.TextInput(attrs={"placeholder": "例如：HQ20261001"}),
            "quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0.001"}),
            "production_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["herb"].queryset = Herb.objects.filter(is_active=True)
        self.fields["location"].queryset = StorageLocation.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse")
        self._style_fields()

    def clean(self):
        cleaned = super().clean()
        herb = cleaned.get("herb")
        location = cleaned.get("location")
        batch_no = (cleaned.get("batch_no") or "").strip()
        if herb and location and batch_no:
            if StockBatch.objects.filter(
                herb=herb, location=location, batch_no=batch_no
            ).exists():
                self.add_error("batch_no", "该药材 + 库位 + 批次已存在，请直接编辑原批次。")
        if cleaned.get("production_date") and cleaned.get("expiry_date"):
            if cleaned["production_date"] > cleaned["expiry_date"]:
                self.add_error("expiry_date", "有效期不能早于生产日期。")
        return cleaned

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity is None or quantity <= 0:
            raise forms.ValidationError("期初数量必须大于 0。")
        return quantity


class StockBatchEditForm(StyledFormMixin, forms.ModelForm):
    new_quantity = forms.DecimalField(
        label="调整后库存",
        max_digits=12,
        decimal_places=3,
        min_value=0,
        widget=forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
    )
    adjust_reason = forms.CharField(
        label="调整原因",
        required=False,
        max_length=300,
        widget=forms.TextInput(attrs={"placeholder": "调整库存时必填，例如：盘点差异"}),
    )

    class Meta:
        model = StockBatch
        fields = ["production_date", "expiry_date"]
        widgets = {
            "production_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and not self.is_bound:
            self.initial["new_quantity"] = self.instance.quantity
        self._style_fields()

    def clean(self):
        cleaned = super().clean()
        new_qty = cleaned.get("new_quantity")
        reason = (cleaned.get("adjust_reason") or "").strip()
        if new_qty is not None and self.instance.pk and new_qty != self.instance.quantity:
            if len(reason) < 2:
                self.add_error("adjust_reason", "库存发生变化时必须填写调整原因。")
        if cleaned.get("production_date") and cleaned.get("expiry_date"):
            if cleaned["production_date"] > cleaned["expiry_date"]:
                self.add_error("expiry_date", "有效期不能早于生产日期。")
        return cleaned


# ---------------------------------------------------------------------------
# 学生 3：入库单与明细
# ---------------------------------------------------------------------------
class InboundOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = InboundOrder
        fields = ["supplier", "warehouse", "inbound_date", "invoice_no", "remark"]
        widgets = {
            "inbound_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "invoice_no": forms.TextInput(attrs={"placeholder": "随货同行单/发票号，可选"}),
            "remark": forms.Textarea(
                attrs={"rows": 3, "placeholder": "到货情况、验收要求等，可选"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)
        self.fields["supplier"].empty_label = "请选择供应来源"
        self.fields["warehouse"].empty_label = "请选择入库仓库"
        if not self.instance.pk and not self.is_bound:
            from django.utils import timezone

            self.initial.setdefault("inbound_date", timezone.localdate())
        self._style_fields()


class InboundItemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = InboundItem
        fields = [
            "herb",
            "batch_no",
            "location",
            "quantity",
            "unit_price",
            "production_date",
            "expiry_date",
            "remark",
        ]
        widgets = {
            "batch_no": forms.TextInput(attrs={"placeholder": "批次号"}),
            "quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0.001"}),
            "unit_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "production_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "remark": forms.TextInput(attrs={"placeholder": "可选"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["herb"].queryset = Herb.objects.filter(is_active=True)
        self.fields["location"].queryset = StorageLocation.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse")
        self.fields["herb"].empty_label = "选择药材"
        self.fields["location"].empty_label = "选择库位"
        self._style_fields()

    def clean_batch_no(self):
        return (self.cleaned_data.get("batch_no") or "").strip()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("production_date") and cleaned.get("expiry_date"):
            if cleaned["production_date"] > cleaned["expiry_date"]:
                self.add_error("expiry_date", "有效期不能早于生产日期。")
        return cleaned


InboundItemFormSet = inlineformset_factory(
    InboundOrder,
    InboundItem,
    form=InboundItemForm,
    extra=1,
    min_num=1,
    validate_min=True,
    can_delete=True,
)

