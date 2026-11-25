"""GST tax invoice as a PDF, built with ReportLab (no system libraries needed)."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..models import CompanySettings, d, money


def _rupees(value):
    return f"{d(value):,.2f}"


def invoice_pdf(invoice):
    stream = io.BytesIO()
    company = CompanySettings.get()
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    doc = SimpleDocTemplate(
        stream, pagesize=A4, title=f"Tax Invoice {invoice.invoice_no}",
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
    )

    is_interstate = d(invoice.igst) > 0
    story = [
        Paragraph(f"<b>{company.name}</b>", styles["Title"]),
        Paragraph(f"GSTIN {company.gstin} &nbsp;|&nbsp; State code {company.state_code} {company.state_name}", small),
        Spacer(1, 3 * mm),
        Paragraph("<b>TAX INVOICE</b>", styles["Heading2"]),
    ]

    meta = Table(
        [
            ["Invoice no.", invoice.invoice_no, "Date", invoice.business_date.strftime("%d-%m-%Y")],
            ["Place of supply", f"{invoice.place_of_supply}",
             "Supply type", "Inter-state (IGST)" if is_interstate else "Intra-state (CGST + SGST)"],
            ["Bill to", invoice.customer.name, "GSTIN", invoice.customer.gstin or "Unregistered / B2C"],
        ],
        colWidths=[28 * mm, 62 * mm, 26 * mm, 66 * mm],
    )
    meta.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F9")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EEF3F9")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C4D4")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story += [meta, Spacer(1, 4 * mm)]

    rows = [["#", "Description", "HSN", "Qty", "Rate", "Taxable", "GST%", "CGST", "SGST", "IGST", "Amount"]]
    for index, line in enumerate(invoice.lines.select_related("item"), start=1):
        line_total = d(line.taxable_value) + d(line.cgst) + d(line.sgst) + d(line.igst)
        rows.append(
            [
                str(index),
                line.item.name,
                line.item.hsn or "-",
                f"{d(line.qty):g}",
                _rupees(line.rate),
                _rupees(line.taxable_value),
                f"{d(line.gst_rate):g}%",
                _rupees(line.cgst),
                _rupees(line.sgst),
                _rupees(line.igst),
                _rupees(line_total),
            ]
        )
    items = Table(rows, repeatRows=1)
    items.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14375E")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C4D4")),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    story += [items, Spacer(1, 4 * mm)]

    totals_rows = [["Taxable value", _rupees(invoice.taxable_value)]]
    if is_interstate:
        totals_rows.append(["IGST", _rupees(invoice.igst)])
    else:
        totals_rows.append(["CGST", _rupees(invoice.cgst)])
        totals_rows.append(["SGST", _rupees(invoice.sgst)])
    totals_rows.append(["Invoice total", _rupees(invoice.total)])
    totals = Table(totals_rows, colWidths=[60 * mm, 40 * mm], hAlign="RIGHT")
    totals.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C4D4")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEF3F9")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )
    story += [totals, Spacer(1, 4 * mm)]

    if invoice.status == "CANCELLED":
        story.append(Paragraph("<b>CANCELLED</b> — see the attached credit note.", small))
    status_line = (
        f"Dispatched: {'yes' if invoice.dispatches.exists() else 'not yet'} &nbsp;|&nbsp; "
        f"Outstanding: Rs {_rupees(invoice.outstanding)}"
    )
    story.append(Paragraph(status_line, small))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Amount in words is on the dispatch challan. Computer-generated invoice.", small))

    doc.build(story)
    return stream.getvalue()
