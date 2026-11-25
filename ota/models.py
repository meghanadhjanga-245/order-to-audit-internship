"""Data model for the Order-to-Audit system.

Design rules that the whole codebase depends on:

* Stock is never stored as a balance field. Every movement is appended to
  ``StockMovement`` and balances are always derived by summing that ledger.
* Money is ``Decimal`` everywhere; ``MONEY`` is the only place values are
  rounded, and only on documents and posted ledger rows.
* Rates are kept to four decimals because the benchmark's weighted-average
  flour rate is Rs 43.125, which is not a whole paisa.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
QTY = Decimal("0.001")


class UnitError(ValueError):
    """Raised when two units cannot be converted into each other."""


def d(value):
    """Coerce to Decimal without ever going through binary float arithmetic."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value):
    return d(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def rate(value):
    return d(value).quantize(RATE, rounding=ROUND_HALF_UP)


def qty(value):
    return d(value).quantize(QTY, rounding=ROUND_HALF_UP)


# unit -> (factor to family base unit, family)
_UNIT_FAMILY = {
    "g": (Decimal("0.001"), "mass"),
    "kg": (Decimal("1"), "mass"),
    "ml": (Decimal("0.001"), "volume"),
    "L": (Decimal("1"), "volume"),
    "piece": (Decimal("1"), "count"),
    "packet": (Decimal("1"), "count"),
    "carton": (Decimal("20"), "count"),
}


class ItemKind(models.TextChoices):
    RAW = "RAW", "Raw material"
    PACK = "PACK", "Packaging"
    FG = "FG", "Finished good"


class Unit(models.TextChoices):
    KG = "kg", "kg"
    L = "L", "litre"
    PIECE = "piece", "piece"
    PACKET = "packet", "packet"


class CompanySettings(models.Model):
    """Singleton: the manufacturer's own GST identity."""

    name = models.CharField(max_length=120, default="Sri Lakshmi Snacks")
    gstin = models.CharField(max_length=15, default="33ABCDE1234F1Z5")
    state_code = models.CharField(max_length=2, default="33")
    state_name = models.CharField(max_length=60, default="Tamil Nadu")
    address = models.CharField(max_length=200, blank=True)
    invoice_prefix = models.CharField(max_length=8, default="TN")

    class Meta:
        verbose_name = "company settings"
        verbose_name_plural = "company settings"

    def __str__(self):
        return self.name

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Item(models.Model):
    """Raw material, packaging material or finished good."""

    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=6, choices=ItemKind.choices)
    base_unit = models.CharField(max_length=8, choices=Unit.choices, default=Unit.KG)
    hsn = models.CharField(max_length=8, blank=True)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    tolerance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("3.00"))
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    packets_per_carton = models.PositiveIntegerField(
        null=True, blank=True, help_text="Only for finished goods."
    )
    reorder_level = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_finished_good(self):
        return self.kind == ItemKind.FG


class UnitConversion(models.Model):
    """Optional per-item conversion override, e.g. 1 carton = 20 packets."""

    item = models.ForeignKey(
        Item, null=True, blank=True, on_delete=models.CASCADE, related_name="conversions"
    )
    from_unit = models.CharField(max_length=8)
    to_unit = models.CharField(max_length=8)
    factor = models.DecimalField(max_digits=18, decimal_places=6)

    def __str__(self):
        return f"{self.from_unit} -> {self.to_unit} x {self.factor}"


def convert(value, from_unit, to_unit, item=None):
    """Convert a quantity between units, honouring per-item overrides."""
    value = d(value)
    if from_unit == to_unit:
        return value
    if item is not None:
        forward = item.conversions.filter(from_unit=from_unit, to_unit=to_unit).first()
        if forward:
            return value * d(forward.factor)
        reverse = item.conversions.filter(from_unit=to_unit, to_unit=from_unit).first()
        if reverse:
            return value / d(reverse.factor)
    if from_unit not in _UNIT_FAMILY or to_unit not in _UNIT_FAMILY:
        raise UnitError(f"Unknown unit: {from_unit} -> {to_unit}")
    f_from, fam_from = _UNIT_FAMILY[from_unit]
    f_to, fam_to = _UNIT_FAMILY[to_unit]
    if fam_from != fam_to:
        raise UnitError(f"Cannot convert {from_unit} to {to_unit}")
    return value * f_from / f_to


class BOM(models.Model):
    """Bill of materials: standard inputs per batch, plus expected yield."""

    product = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="boms")
    name = models.CharField(max_length=120)
    expected_yield = models.DecimalField(
        max_digits=12, decimal_places=3, help_text="Packets produced per batch."
    )
    tolerance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("3.00"))
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "BOM"

    def __str__(self):
        return self.name


class BOMLine(models.Model):
    bom = models.ForeignKey(BOM, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="bom_lines")
    qty_per_batch = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        ordering = ["item__kind", "item__code"]

    def __str__(self):
        return f"{self.item.code} {self.qty_per_batch}{self.item.base_unit}"


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    gstin = models.CharField(max_length=15, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.name


class Customer(models.Model):
    class Kind(models.TextChoices):
        RETAILER = "RETAILER", "Retailer"
        DISTRIBUTOR = "DISTRIBUTOR", "Distributor"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.RETAILER)
    gstin = models.CharField(max_length=15, blank=True)
    state_code = models.CharField(max_length=2, default="33")
    state_name = models.CharField(max_length=60, default="Tamil Nadu")
    phone = models.CharField(max_length=20, blank=True)
    salesman = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="customers",
    )
    credit_days = models.PositiveIntegerField(default=30)

    def __str__(self):
        return self.name


class StockMovement(models.Model):
    """Append-only stock ledger. Summing this table is the only way to know stock."""

    class Kind(models.TextChoices):
        OPENING = "OPENING", "Opening balance"
        PURCHASE = "PURCHASE", "Purchase receipt"
        ISSUE = "ISSUE", "Issued to production"
        RECEIPT = "RECEIPT", "Production receipt"
        DISPATCH = "DISPATCH", "Dispatched on invoice"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"
        REVALUATION = "REVALUATION", "Cost revaluation"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements")
    ts = models.DateTimeField(auto_now_add=True)
    business_date = models.DateField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    value = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    source_type = models.CharField(max_length=40, blank=True)
    source_id = models.PositiveIntegerField(null=True, blank=True)
    source_ref = models.CharField(max_length=80, blank=True)
    batch = models.CharField(max_length=40, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["item", "business_date"])]

    def __str__(self):
        return f"{self.business_date} {self.item.code} {self.qty}"

    @property
    def signed_value(self):
        return self.value


class Purchase(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    bill_no = models.CharField(max_length=40)
    bill_date = models.DateField()
    notes = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-bill_date", "-id"]

    def __str__(self):
        return f"{self.bill_no}"

    @property
    def taxable_value(self):
        return money(sum((ln.taxable for ln in self.lines.all()), Decimal("0")))

    @property
    def tax_value(self):
        return money(sum((ln.gst_amount for ln in self.lines.all()), Decimal("0")))

    @property
    def total(self):
        return money(self.taxable_value + self.tax_value)


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    rate = models.DecimalField(max_digits=14, decimal_places=4)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))

    @property
    def taxable(self):
        return money(d(self.qty) * d(self.rate))

    @property
    def gst_amount(self):
        return money(self.taxable * d(self.gst_rate) / 100)


class ProductionRun(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ISSUED = "ISSUED", "Issued"
        COMPLETED = "COMPLETED", "Completed"
        COSTED = "COSTED", "Costed"

    bom = models.ForeignKey(BOM, on_delete=models.PROTECT, related_name="runs")
    run_no = models.CharField(max_length=20, unique=True)
    business_date = models.DateField()
    batches = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal("1.000"))
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    expected_output = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    good_output = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    damaged_packets = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    issued_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.run_no

    @property
    def material_cost(self):
        return money(sum((ln.value or Decimal("0")) for ln in self.lines.all()))

    @property
    def overhead_cost(self):
        return money(sum((o.amount for o in self.overheads.all()), Decimal("0")))

    @property
    def total_cost(self):
        return money(self.material_cost + self.overhead_cost)

    @property
    def cost_per_packet(self):
        if d(self.good_output) <= 0:
            return None
        return money(d(self.total_cost) / d(self.good_output))


class RunLine(models.Model):
    run = models.ForeignKey(ProductionRun, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=14, decimal_places=3)
    actual_qty = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    value = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)

    @property
    def is_packaging(self):
        return self.item.kind == ItemKind.PACK

    @property
    def variance_pct(self):
        planned = d(self.planned_qty)
        if planned == 0:
            return None
        return ((d(self.actual_qty) - planned) / planned * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


class RunOverhead(models.Model):
    class Kind(models.TextChoices):
        LABOUR = "LABOUR", "Labour"
        POWER = "POWER", "Gas / power"
        OTHER = "OTHER", "Other"

    run = models.ForeignKey(ProductionRun, on_delete=models.CASCADE, related_name="overheads")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=120, blank=True)


class SalesOrder(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        INVOICED = "INVOICED", "Invoiced"
        DISPATCHED = "DISPATCHED", "Dispatched"

    order_no = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    salesman = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    business_date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approved_orders",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=200, blank=True)
    captured_offline = models.BooleanField(default=False, help_text="Taken on weak network.")

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.order_no

    @property
    def total_qty(self):
        return sum((d(ln.qty) for ln in self.lines.all()), Decimal("0"))

    @property
    def total_value(self):
        total = sum((money(d(ln.qty) * d(ln.rate)) for ln in self.lines.all()), Decimal("0"))
        return money(total)


class OrderLine(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=12, decimal_places=3)
    rate = models.DecimalField(max_digits=12, decimal_places=4)

    @property
    def amount(self):
        return money(d(self.qty) * d(self.rate))


class InvoiceSequence(models.Model):
    """One gap-free invoice counter per financial year, taken under a row lock."""

    financial_year = models.CharField(max_length=7, unique=True)
    last_number = models.PositiveIntegerField(default=0)


class Invoice(models.Model):
    class Status(models.TextChoices):
        POSTED = "POSTED", "Posted"
        CANCELLED = "CANCELLED", "Cancelled"

    invoice_no = models.CharField(max_length=20, unique=True)
    financial_year = models.CharField(max_length=7)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    order = models.ForeignKey(
        SalesOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    business_date = models.DateField()
    place_of_supply = models.CharField(max_length=2)
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.POSTED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.invoice_no

    @property
    def is_interstate(self):
        return self.igst > 0

    @property
    def paid_amount(self):
        return money(
            sum((d(a.amount) for a in self.allocations.all()), Decimal("0"))
        )

    @property
    def outstanding(self):
        if self.status != self.Status.POSTED:
            return Decimal("0.00")
        return money(d(self.total) - self.paid_amount)


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=12, decimal_places=3)
    rate = models.DecimalField(max_digits=12, decimal_places=4)
    taxable_value = models.DecimalField(max_digits=14, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))


class Dispatch(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="dispatches")
    business_date = models.DateField()
    qty = models.DecimalField(max_digits=12, decimal_places=3)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Dispatch for {self.invoice.invoice_no}"


class CreditNote(models.Model):
    """The only way to undo a posted invoice: never deleted, always credited."""

    note_no = models.CharField(max_length=20, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    business_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.note_no


class Payment(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    business_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    mode = models.CharField(max_length=20, default="UPI")
    reference = models.CharField(max_length=60, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.business_date} {self.customer} {self.amount}"


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2)


class AuditLog(models.Model):
    """User + timestamp trail for edits to documents that must stay explainable."""

    entity_type = models.CharField(max_length=40)
    entity_id = models.PositiveIntegerField()
    action = models.CharField(max_length=40)
    detail = models.CharField(max_length=300, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.entity_type}#{self.entity_id} {self.action}"
