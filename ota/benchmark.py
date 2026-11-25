"""Section 5 of the brief, as data and as a scripted run.

``seed()`` loads exactly the master data the evaluators specify; ``replay()``
walks the nine steps in order and returns every figure they check. The test
suite and the ``run_benchmark`` command both drive this module, so the numbers
quoted in the README and the numbers in the database cannot drift apart.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction

from .models import (
    BOM,
    BOMLine,
    CompanySettings,
    Customer,
    Invoice,
    InvoiceSequence,
    Item,
    ItemKind,
    ProductionRun,
    SalesOrder,
    Supplier,
    Unit,
    d,
    money,
    qty as q3,
)
from .roles import ADMIN, ACCOUNTANT, OWNER, PRODUCTION, SALESMAN, ensure_groups
from .services import production as prod
from .services import sales
from .services.ledger import ledger_totals, post_movement
from .services.reports import (
    gst_summary,
    outstanding,
    production_report,
    purchase_register,
    sales_register,
    stock_ledger,
    stock_summary,
)

OPENING_DATE = date(2026, 11, 1)
PURCHASE_DATE = date(2026, 11, 5)
RUN_DATE = date(2026, 11, 10)
SALES_DATE = date(2026, 11, 12)
PAYMENT_DATE = date(2026, 11, 15)

PASSWORD = "benchmark123"

USERNAMES = {
    "admin": "admin",
    "production": "production",
    "salesman_a": "salesman_a",
    "salesman_b": "salesman_b",
    "accountant": "accountant",
    "owner": "owner",
}
ROLE_FOR = {
    "admin": ADMIN,
    "production": PRODUCTION,
    "salesman_a": SALESMAN,
    "salesman_b": SALESMAN,
    "accountant": ACCOUNTANT,
    "owner": OWNER,
}


def reset_data():
    """Empty the app's tables in dependency order, leaving auth alone."""
    from .models import (
        AuditLog,
        CreditNote,
        Dispatch,
        InvoiceLine,
        OrderLine,
        Payment,
        PaymentAllocation,
        Purchase,
        PurchaseLine,
        RunLine,
        RunOverhead,
        StockMovement,
        UnitConversion,
    )

    for model in [
        AuditLog, PaymentAllocation, Payment, CreditNote, Dispatch, InvoiceLine, Invoice,
        InvoiceSequence, OrderLine, SalesOrder, RunOverhead, RunLine, ProductionRun,
        PurchaseLine, Purchase, StockMovement, BOMLine, BOM, Customer, Supplier,
        UnitConversion, Item, CompanySettings,
    ]:
        model.objects.all().delete()


def _user(username, role, first_name):
    from django.contrib.auth.models import Group

    user, created = User.objects.get_or_create(username=username)
    if created:
        user.set_password(PASSWORD)
        user.first_name = first_name
        user.save()
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def seed():
    """Load the benchmark master data and opening stock. Returns a context dict."""
    ensure_groups()
    users = {key: _user(USERNAMES[key], ROLE_FOR[key], key.title()) for key in USERNAMES}

    company = CompanySettings.get()
    company.name = "Sri Lakshmi Snacks"
    company.gstin = "33ABCDE1234F1Z5"
    company.state_code = "33"
    company.state_name = "Tamil Nadu"
    company.invoice_prefix = "TN"
    company.save()

    flour = Item.objects.create(
        code="RM-FLOUR", name="Flour (maida)", kind=ItemKind.RAW, base_unit=Unit.KG,
        hsn="1101", gst_rate=Decimal("5.00"),
    )
    oil = Item.objects.create(
        code="RM-OIL", name="Cooking oil", kind=ItemKind.RAW, base_unit=Unit.L,
        hsn="1507", gst_rate=Decimal("5.00"),
    )
    spice = Item.objects.create(
        code="RM-SPICE", name="Salt and spice mix", kind=ItemKind.RAW, base_unit=Unit.KG,
        hsn="0910", gst_rate=Decimal("5.00"),
    )
    pouch = Item.objects.create(
        code="PK-POUCH200", name="200 g pouch", kind=ItemKind.PACK, base_unit=Unit.PIECE,
        hsn="3923", gst_rate=Decimal("12.00"),
    )
    carton = Item.objects.create(
        code="PK-CARTON", name="Carton (holds 20 packets)", kind=ItemKind.PACK,
        base_unit=Unit.PIECE, hsn="4819", gst_rate=Decimal("12.00"),
    )
    murukku = Item.objects.create(
        code="FG-MUR200", name="Murukku 200 g", kind=ItemKind.FG, base_unit=Unit.PACKET,
        hsn="2106", gst_rate=Decimal("5.00"), selling_price=Decimal("50.00"),
        packets_per_carton=20,
    )

    bom = BOM.objects.create(
        product=murukku, name="Murukku 200 g - standard batch",
        expected_yield=Decimal("200.000"), tolerance_pct=Decimal("3.00"),
    )
    for item, per_batch in [
        (flour, Decimal("40")), (oil, Decimal("10")), (spice, Decimal("1.2")),
        (pouch, Decimal("200")), (carton, Decimal("10")),
    ]:
        BOMLine.objects.create(bom=bom, item=item, qty_per_batch=per_batch)

    supplier = Supplier.objects.create(
        name="Ganesh Traders", gstin="33AAACG1234H1Z9", phone="+91 90000 11111"
    )
    retailer_a = Customer.objects.create(
        name="Retailer A", kind=Customer.Kind.RETAILER, gstin="33AABCR1234M1Z1",
        state_code="33", state_name="Tamil Nadu", salesman=users["salesman_a"],
    )
    distributor_b = Customer.objects.create(
        name="Distributor B", kind=Customer.Kind.DISTRIBUTOR, gstin="29AACCD5678N1Z2",
        state_code="29", state_name="Karnataka", salesman=users["salesman_b"],
    )

    # Opening stock, including finished goods at an explicit opening rate.
    # The brief does not state an opening cost for finished goods; Rs 30 is an
    # assumption recorded in the README.
    opening = [
        (flour, Decimal("100"), Decimal("42")),
        (oil, Decimal("30"), Decimal("140")),
        (spice, Decimal("5"), Decimal("200")),
        (pouch, Decimal("500"), Decimal("2.50")),
        (carton, Decimal("30"), Decimal("15")),
        (murukku, Decimal("50"), Decimal("30")),
    ]
    for item, quantity, cost in opening:
        post_movement(
            item=item, qty=quantity, kind="OPENING", business_date=OPENING_DATE,
            source_type="Opening", source_ref="Opening balance", unit_cost=cost,
            user=users["admin"], note="Opening balance",
        )

    return {
        "users": users, "company": company, "bom": bom, "flour": flour, "oil": oil,
        "spice": spice, "pouch": pouch, "carton": carton, "murukku": murukku,
        "supplier": supplier, "retailer_a": retailer_a, "distributor_b": distributor_b,
    }


@transaction.atomic
def replay(ctx=None):
    """Run the nine benchmark steps and return every figure Section 5 checks."""
    ctx = ctx or seed()
    users = ctx["users"]
    flour, oil, spice = ctx["flour"], ctx["oil"], ctx["spice"]
    pouch, carton, murukku = ctx["pouch"], ctx["carton"], ctx["murukku"]

    # 1. Purchase: 60 kg flour at Rs 45.
    purchase = sales_purchase = _purchase(
        supplier=ctx["supplier"], item=flour, quantity=Decimal("60"), rate=Decimal("45"),
        bill_no="GT/2026/014", business_date=PURCHASE_DATE, user=users["admin"],
    )

    # 2. Production run: issue 40 kg flour, 10.5 L oil, 1.2 kg spice.
    run = prod.create_run(bom=ctx["bom"], batches=Decimal("1"), business_date=RUN_DATE,
                          user=users["production"])
    prod.issue_run(
        run,
        {flour.pk: Decimal("40"), oil.pk: Decimal("10.5"), spice.pk: Decimal("1.2")},
        user=users["production"],
    )

    # 3. Actual output 188 good packets, 6 damaged pouches, 9 cartons used.
    prod.complete_run(
        run, good_output=Decimal("188"), damaged_packets=Decimal("6"),
        pack_actuals={pouch.pk: Decimal("194"), carton.pk: Decimal("9")},
        user=users["production"],
    )

    fg_after_run = ledger_totals(murukku)[0]

    # 4. Salesman A orders 150 packets for Retailer A.
    order_a = sales.create_order(
        customer=ctx["retailer_a"], salesman=users["salesman_a"],
        lines=[(murukku, Decimal("150"))], business_date=SALES_DATE,
    )

    # 5. Admin approves, raises the GST invoice, records dispatch.
    sales.approve_order(order_a, users["admin"])
    invoice_a = sales.create_invoice(order_a, users["admin"], business_date=SALES_DATE)
    sales.dispatch_invoice(invoice_a, users["admin"], business_date=SALES_DATE)

    # 6. Salesman B orders 120 packets for Distributor B: not enough stock.
    order_b = sales.create_order(
        customer=ctx["distributor_b"], salesman=users["salesman_b"],
        lines=[(murukku, Decimal("120"))], business_date=SALES_DATE,
    )
    check_b = sales.stock_check(order_b)
    shortage = sum((row["shortage"] for row in check_b), Decimal("0"))
    from .services.gst import tax_split

    interstate_tax = tax_split(Decimal("6000"), Decimal("5"), is_same_state=False)

    # 7. Payment of Rs 4,000 from Retailer A.
    payment = sales.record_payment(
        customer=ctx["retailer_a"], amount=Decimal("4000"), business_date=PAYMENT_DATE,
        user=users["admin"], mode="UPI", reference="UPI/2026/5512",
    )

    # 8. Labour Rs 1,200 and gas/power Rs 600 for the run, then cost per packet.
    prod.set_overheads(run, [("LABOUR", Decimal("1200")), ("POWER", Decimal("600"))])
    prod.cost_run(run, user=users["production"])

    # 9. Month's reports.
    reports = {
        "sales": sales_register(),
        "gst": gst_summary(),
        "purchases": purchase_register(),
        "stock": stock_summary(),
        "ledger": stock_ledger(),
        "production": production_report(),
        "outstanding": outstanding(),
    }

    flour_qty, flour_value = ledger_totals(flour)
    variance = prod.variance_table(run)
    oil_row = next(r for r in variance["lines"] if r["item"] == oil)

    return {
        "run": run,
        "order_a": order_a,
        "invoice_a": invoice_a,
        "order_b": order_b,
        "payment": payment,
        "purchase": purchase,
        "flour_closing": flour_qty,
        "flour_value": flour_value,
        "flour_average_rate": (flour_value / flour_qty).quantize(Decimal("0.0001")),
        "oil_closing": ledger_totals(oil)[0],
        "spice_closing": ledger_totals(spice)[0],
        "pouch_closing": ledger_totals(pouch)[0],
        "carton_closing": ledger_totals(carton)[0],
        "fg_after_run": fg_after_run,
        "fg_after_dispatch": ledger_totals(murukku)[0],
        "fg_value": ledger_totals(murukku)[1],
        "yield_variance": variance["yield_variance"],
        "oil_variance": oil_row["variance"],
        "oil_flagged": oil_row["flagged"],
        "pouch_variance": next(
            r["variance"] for r in variance["lines"] if r["item"] == pouch
        ),
        "carton_variance": next(
            r["variance"] for r in variance["lines"] if r["item"] == carton
        ),
        "carton_flagged": next(
            r["flagged"] for r in variance["lines"] if r["item"] == carton
        ),
        "material_cost": run.material_cost,
        "overhead_cost": run.overhead_cost,
        "total_cost": run.total_cost,
        "cost_per_packet": run.cost_per_packet,
        "margin_per_packet": money(Decimal("50") - d(run.cost_per_packet)),
        "invoice_total": invoice_a.total,
        "invoice_cgst": invoice_a.cgst,
        "invoice_sgst": invoice_a.sgst,
        "invoice_taxable": invoice_a.taxable_value,
        "outstanding_a": invoice_a.outstanding,
        "shortage_b": shortage,
        "igst_if_invoiced": interstate_tax[2],
        "reports": reports,
    }


def _purchase(*, supplier, item, quantity, rate, bill_no, business_date, user):
    from .models import Purchase, PurchaseLine

    purchase = Purchase.objects.create(
        supplier=supplier, bill_no=bill_no, bill_date=business_date, created_by=user
    )
    PurchaseLine.objects.create(
        purchase=purchase, item=item, qty=quantity, rate=rate, gst_rate=item.gst_rate
    )
    post_movement(
        item=item, qty=quantity, kind="PURCHASE", business_date=business_date,
        source_type="Purchase", source_id=purchase.pk, source_ref=bill_no,
        user=user, unit_cost=rate,
    )
    return purchase


EXPECTED = {
    "flour_closing": Decimal("120"),
    "flour_average_rate": Decimal("43.1250"),
    "oil_closing": Decimal("19.5"),
    "spice_closing": Decimal("3.8"),
    "pouch_closing": Decimal("306"),
    "carton_closing": Decimal("21"),
    "fg_after_dispatch": Decimal("88"),
    "yield_variance": Decimal("-6.00"),
    "oil_variance": Decimal("5.00"),
    "pouch_variance": Decimal("-3.00"),
    "carton_variance": Decimal("-10.00"),
    "invoice_taxable": Decimal("7500.00"),
    "invoice_cgst": Decimal("187.50"),
    "invoice_sgst": Decimal("187.50"),
    "invoice_total": Decimal("7875.00"),
    "outstanding_a": Decimal("3875.00"),
    "shortage_b": Decimal("32"),
    "material_cost": Decimal("4055.00"),
    "total_cost": Decimal("5855.00"),
    "cost_per_packet": Decimal("31.14"),
}


def check(results):
    """Compare a replay against Section 5. Returns a list of (key, expected, actual, ok)."""
    rows = []
    for key, expected in EXPECTED.items():
        actual = results.get(key)
        rows.append((key, expected, d(actual) if actual is not None else None, d(actual) == d(expected)))
    return rows
