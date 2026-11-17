from django.apps import AppConfig


class WarehouseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "warehouse"
    verbose_name = "中药仓储库位管理"

    def ready(self):
        from . import signals  # noqa: F401
