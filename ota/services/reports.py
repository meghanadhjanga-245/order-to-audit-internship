"""Auditor-facing reports.

Each report is one function returning the same shape:

    {"title": str, "columns": [str], "rows": [[value, ...]], "totals": {label: value}}

so screen, CSV, Excel and PDF all render the same numbers.
"""
import csv
import io
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from ..models import (
    CompanySettings,
    Customer,
    Invoice,
    Item,
    ItemKind,
    Payment,
    ProductionRun,
    Purchase,
    SalesOrder,
    StockMovement,
    d,
    money,
)
from .ledger import ledger_totals

AGE_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, None)]


def _dr(rows, *indexes):
    """Sum Decimal-ish cells across rows by index."""
    total = Decimal("0")
    for row in rows:
        for i in indexes:
            total += d(row[i])
    return total


def stock_summary(from_date=None, to_date=None):
    to_date = to_date or timezone.localdate()
    rows = []
    for item in Item.objects.filter(is_active=True):
        opening = Decimal("0")
        receipts = Decimal("0")
        issues = Decimal("0")
        for mv in StockMovement.objects.filter(item=item, business_date__lte=to_date):
            q = d(mv.qty)
            if from_date and mv.business_date < from_date:
                opening += q
            elif q >= 0:
                receipts += q
            else:
                issues += q
        on_hand_qty, on_hand_value = ledger_totals(item)
        rows.append(
            [
                item.code,
                item.name,
                item.kind,
                f"{opening} {item.base_unit}",
                f"{receipts}",
                f"{abs(issues)}",
                f"{opening + receipts + issues}",
                f"{money(on_hand_value)}",
            ]
        )
    return {
        "title": "Stock summary",
        "columns": ["Code", "Item", "Type", "Opening", "Receipts", "Issues", "Closing", "Value (Rs)"],
        "rows": rows,
        "totals": {"Closing value (Rs)": money(sum(d(r[7]) for r in rows))},
    }


def stock_ledger(from_date=None, to_date=None, item=None):
    to_date = to_date or timezone.localdate()
    qs = StockMovement.objects.select_related("item", "created_by").filter(
        business_date__lte=to_date
    )
    if from_date:
        qs = qs.filter(business_date__gte=from_date)
    if item:
        qs = qs.filter(item=item)
    rows = []
    for mv in qs.order_by("business_date", "id"):
        rows.append(
            [
                mv.business_date.isoformat(),
                mv.item.code,
                mv.kind,
                f"{d(mv.qty)} {mv.item.base_unit}",
                f"{d(mv.unit_cost)}",
                f"{money(mv.value)}",
                mv.source_type or "-",
                mv.source_ref or "-",
            ]
        )
    return {
        "title": "Stock ledger",
        "columns": ["Date", "Item", "Kind", "Qty", "Unit cost", "Value (Rs)", "Source", "Reference"],
        "rows": rows,
        "totals": {"Movements": len(rows)},
    }


def sales_register(from_date=None, to_date=None):
    to_date = to_date or timezone.localdate()
    qs = Invoice.objects.select_related("customer").filter(business_date__lte=to_date)
    if from_date:
        qs = qs.filter(business_date__gte=from_date)
    rows = []
    for inv in qs.order_by("business_date", "id"):
        rows.append(
            [
                inv.invoice_no,
                inv.business_date.isoformat(),
                inv.customer.name,
                inv.customer.kind,
                f"{money(inv.taxable_value)}",
                f"{money(inv.cgst + inv.sgst + inv.igst)}",
                f"{money(inv.total)}",
                inv.status,
            ]
        )
    return {
        "title": "Sales register",
        "columns": ["Invoice", "Date", "Customer", "Type", "Taxable (Rs)", "GST (Rs)", "Total (Rs)", "Status"],
        "rows": rows,
        "totals": {
            "Taxable (Rs)": money(_dr(rows, 4)),
            "GST (Rs)": money(_dr(rows, 5)),
            "Total (Rs)": money(_dr(rows, 6)),
        },
    }


def gst_summary(from_date=None, to_date=None):
    """Outward supplies in a shape that maps onto GSTR-1 and GSTR-3B."""
    to_date = to_date or timezone.localdate()
    qs = Invoice.objects.filter(status=Invoice.Status.POSTED, business_date__lte=to_date)
    if from_date:
        qs = qs.filter(business_date__gte=from_date)

    buckets = {}
    b2b = {"taxable": Decimal("0"), "tax": Decimal("0")}
    b2c = {"taxable": Decimal("0"), "tax": Decimal("0")}
    for inv in qs.select_related("customer"):
        target = b2b if inv.customer.gstin else b2c
        target["taxable"] += d(inv.taxable_value)
        target["tax"] += d(inv.cgst) + d(inv.sgst) + d(inv.igst)
        for line in inv.lines.select_related("item"):
            key = (line.item.hsn or "-", d(line.gst_rate), line.item.name)
            row = buckets.setdefault(key, {"taxable": Decimal("0"), "cgst": Decimal("0"),
                                           "sgst": Decimal("0"), "igst": Decimal("0"),
                                           "qty": Decimal("0")})
            row["taxable"] += d(line.taxable_value)
            row["cgst"] += d(line.cgst)
            row["sgst"] += d(line.sgst)
            row["igst"] += d(line.igst)
            row["qty"] += d(line.qty)

    rows = []
    for (hsn, rate, name), row in sorted(buckets.items()):
        rows.append(
            [
                hsn,
                name,
                f"{row['qty']}",
                f"{rate}%",
                f"{money(row['taxable'])}",
                f"{money(row['cgst'])}",
                f"{money(row['sgst'])}",
                f"{money(row['igst'])}",
                f"{money(row['taxable'] + row['cgst'] + row['sgst'] + row['igst'])}",
            ]
        )
    return {
        "title": "GST summary (outward supplies)",
        "columns": ["HSN", "Description", "Qty", "Rate", "Taxable (Rs)", "CGST (Rs)", "SGST (Rs)", "IGST (Rs)", "Total (Rs)"],
        "rows": rows,
        "totals": {
            "B2B taxable (Rs)": money(b2b["taxable"]),
            "B2B tax (Rs)": money(b2b["tax"]),
            "B2C taxable (Rs)": money(b2c["taxable"]),
            "B2C tax (Rs)": money(b2c["tax"]),
        },
    }


def purchase_register(from_date=None, to_date=None):
    to_date = to_date or timezone.localdate()
    qs = Purchase.objects.select_related("supplier").filter(bill_date__lte=to_date)
    if from_date:
        qs = qs.filter(bill_date__gte=from_date)
    rows = []
    for purchase in qs.order_by("bill_date", "id"):
        rows.append(
            [
                purchase.bill_no,
                purchase.bill_date.isoformat(),
                purchase.supplier.name,
                f"{money(purchase.taxable_value)}",
                f"{money(purchase.tax_value)}",
                f"{money(purchase.total)}",
            ]
        )
    return {
        "title": "Purchase register",
        "columns": ["Bill", "Date", "Supplier", "Taxable (Rs)", "GST (Rs)", "Total (Rs)"],
        "rows": rows,
        "totals": {
            "Taxable (Rs)": money(_dr(rows, 3)),
            "GST (Rs)": money(_dr(rows, 4)),
            "Total (Rs)": money(_dr(rows, 5)),
        },
    }


def production_report(from_date=None, to_date=None):
    to_date = to_date or timezone.localdate()
    qs = ProductionRun.objects.select_related("bom", "bom__product").filter(
        business_date__lte=to_date
    )
    if from_date:
        qs = qs.filter(business_date__gte=from_date)
    rows = []
    for run in qs.order_by("business_date", "id"):
        expected = d(run.expected_output)
        actual = d(run.good_output)
        var = None if expected <= 0 else ((actual - expected) / expected * 100)
        rows.append(
            [
                run.run_no,
                run.business_date.isoformat(),
                run.bom.product.name,
                f"{d(run.batches)}",
                f"{expected}",
                f"{actual}",
                "-" if var is None else f"{var.quantize(Decimal('0.01'))}%",
                f"{d(run.damaged_packets)}",
                f"{money(run.material_cost)}",
                f"{money(run.overhead_cost)}",
                f"{money(run.total_cost)}",
                "-" if run.cost_per_packet is None else f"{run.cost_per_packet}",
            ]
        )
    return {
        "title": "Production report",
        "columns": ["Run", "Date", "Product", "Batches", "Expected", "Actual", "Yield var", "Damaged",
                    "Material (Rs)", "Overhead (Rs)", "Total (Rs)", "Cost/packet"],
        "rows": rows,
        "totals": {
            "Material (Rs)": money(_dr(rows, 8)),
            "Overhead (Rs)": money(_dr(rows, 9)),
            "Total (Rs)": money(_dr(rows, 10)),
        },
    }


def outstanding(as_of=None):
    as_of = as_of or timezone.localdate()
    rows = []
    for customer in Customer.objects.all():
        invoices = list(
            Invoice.objects.filter(customer=customer, status=Invoice.Status.POSTED)
            .order_by("business_date")
        )
        if not invoices:
            continue
        billed = sum((d(inv.total) for inv in invoices), Decimal("0"))
        received = sum((d(inv.paid_amount) for inv in invoices), Decimal("0"))
        due = billed - received
        buckets = {label: Decimal("0") for label in ("0-30", "31-60", "61-90", "90+")}
        for inv in invoices:
            amount = d(inv.outstanding)
            if amount <= 0:
                continue
            age = (as_of - inv.business_date).days
            for low, high in AGE_BUCKETS:
                if age >= low and (high is None or age <= high):
                    label = "90+" if high is None else f"{low}-{high}"
                    buckets[label] += amount
                    break
        rows.append(
            [
                customer.name,
                customer.kind,
                f"{money(billed)}",
                f"{money(received)}",
                f"{money(due)}",
                f"{money(buckets['0-30'])}",
                f"{money(buckets['31-60'])}",
                f"{money(buckets['61-90'])}",
                f"{money(buckets['90+'])}",
            ]
        )
    return {
        "title": "Outstanding receivables",
        "columns": ["Customer", "Type", "Billed (Rs)", "Received (Rs)", "Outstanding (Rs)",
                    "0-30", "31-60", "61-90", "90+"],
        "rows": rows,
        "totals": {
            "Outstanding (Rs)": money(_dr(rows, 4)),
            "Overdue 90+ (Rs)": money(_dr(rows, 8)),
        },
    }


REPORTS = {
    "stock": stock_summary,
    "ledger": stock_ledger,
    "sales": sales_register,
    "gst": gst_summary,
    "purchases": purchase_register,
    "production": production_report,
    "outstanding": outstanding,
}


# ---------------------------------------------------------------- renderers


def to_csv(report):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([report["title"]])
    writer.writerow(report["columns"])
    for row in report["rows"]:
        writer.writerow(row)
    for label, value in report["totals"].items():
        writer.writerow([label, value])
    return buffer.getvalue()


def to_tally_xml(report, key="sales"):
    """Export report as Tally-compatible XML (vouchers / ledger)."""
    company = CompanySettings.get()
    xml_lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<ENVELOPE>',
        '  <HEADER>',
        '    <TALLYREQUEST>Import Data</TALLYREQUEST>',
        '  </HEADER>',
        '  <BODY>',
        '    <IMPORTDATA>',
        '      <REQUESTDESC>',
        '        <REPORTNAME>Vouchers</REPORTNAME>',
        '        <STATICVARIABLES>',
        f'          <SVCURRENTCOMPANY>{company.name}</SVCURRENTCOMPANY>',
        '        </STATICVARIABLES>',
        '      </REQUESTDESC>',
        '      <REQUESTDATA>',
    ]
    if key == "sales":
        for row in report.get("rows", []):
            try:
                inv_no, inv_date, cust_name, cust_type, taxable, gst, total, status = row
                clean_date = inv_date.replace("-", "")
                xml_lines.extend([
                    '        <TALLYMESSAGE xmlns:UDF="TallyUDF">',
                    '          <VOUCHER VCHTYPE="Sales" ACTION="Create">',
                    f'            <DATE>{clean_date}</DATE>',
                    f'            <VOUCHERNUMBER>{inv_no}</VOUCHERNUMBER>',
                    f'            <PARTYLEDGERNAME>{cust_name}</PARTYLEDGERNAME>',
                    f'            <NARRATION>Tax Invoice {inv_no} - Sri Lakshmi Snacks</NARRATION>',
                    '            <ALLLEDGERENTRIES.LIST>',
                    f'              <LEDGERNAME>{cust_name}</LEDGERNAME>',
                    '              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>',
                    f'              <AMOUNT>-{total}</AMOUNT>',
                    '            </ALLLEDGERENTRIES.LIST>',
                    '            <ALLLEDGERENTRIES.LIST>',
                    '              <LEDGERNAME>Sales Local GST 5%</LEDGERNAME>',
                    '              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>',
                    f'              <AMOUNT>{taxable}</AMOUNT>',
                    '            </ALLLEDGERENTRIES.LIST>',
                    '            <ALLLEDGERENTRIES.LIST>',
                    '              <LEDGERNAME>GST Output Tax</LEDGERNAME>',
                    '              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>',
                    f'              <AMOUNT>{gst}</AMOUNT>',
                    '            </ALLLEDGERENTRIES.LIST>',
                    '          </VOUCHER>',
                    '        </TALLYMESSAGE>',
                ])
            except Exception:
                continue
    else:
        for row in report.get("rows", []):
            xml_lines.append(f'        <!-- Entry: {" | ".join(str(c) for c in row)} -->')
    xml_lines.extend([
        '      </REQUESTDATA>',
        '    </IMPORTDATA>',
        '  </BODY>',
        '</ENVELOPE>',
    ])
    return "\n".join(xml_lines)


def to_xlsx(report):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = report["title"][:30]
    sheet.append([report["title"]])
    sheet.append(report["columns"])
    for row in report["rows"]:
        sheet.append([str(cell) if isinstance(cell, (Decimal,)) else cell for cell in row])
    sheet.append([])
    for label, value in report["totals"].items():
        sheet.append([label, str(value)])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def to_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    stream = io.BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=report["title"],
    )
    styles = getSampleStyleSheet()
    company = CompanySettings.get()
    story = [
        Paragraph(company.name, styles["Title"]),
        Paragraph(report["title"], styles["Heading2"]),
        Spacer(1, 4 * mm),
    ]
    data = [report["columns"]] + [[str(cell) for cell in row] for row in report["rows"]]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14375E")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C4D4")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FA")]),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))
    for label, value in report["totals"].items():
        story.append(Paragraph(f"<b>{label}:</b> {value}", styles["Normal"]))
    doc.build(story)
    return stream.getvalue()
