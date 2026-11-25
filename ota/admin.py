from django.contrib import admin

from .models import (
    BOM,
    BOMLine,
    AuditLog,
    CompanySettings,
    CreditNote,
    Customer,
    Dispatch,
    Invoice,
    InvoiceLine,
    Item,
    Payment,
    PaymentAllocation,
    ProductionRun,
    Purchase,
    PurchaseLine,
    RunLine,
    RunOverhead,
    SalesOrder,
    StockMovement,
    Supplier,
    UnitConversion,
)


class BOMLineInline(admin.TabularInline):
    model = BOMLine
    extra = 1


@admin.register(BOM)
class BOMAdmin(admin.ModelAdmin):
    list_display = ("name", "product", "expected_yield", "tolerance_pct", "is_active")
    inlines = [BOMLineInline]


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "base_unit", "gst_rate", "selling_price")
    list_filter = ("kind",)
    search_fields = ("code", "name")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "gstin", "state_code", "salesman")
    list_filter = ("kind", "state_code")
    search_fields = ("name", "gstin")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Read-only on purpose: the ledger is append-only."""

    list_display = ("business_date", "item", "kind", "qty", "unit_cost", "value", "source_ref")
    list_filter = ("kind", "item")
    date_hierarchy = "business_date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):
    list_display = ("run_no", "bom", "business_date", "status", "good_output")
    list_filter = ("status",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_no", "customer", "business_date", "total", "status")
    list_filter = ("status",)
    search_fields = ("invoice_no", "customer__name")


admin.site.register(
    [BOMLine, Supplier, UnitConversion, Purchase, PurchaseLine, RunLine, RunOverhead,
     SalesOrder, InvoiceLine, Dispatch, CreditNote, Payment, PaymentAllocation, AuditLog]
)
admin.site.register(CompanySettings)
admin.site.site_header = "Order-to-Audit | Sri Lakshmi Snacks"
admin.site.site_title = "Order-to-Audit Admin"
