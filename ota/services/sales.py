"""Sales loop: order -> approval -> GST invoice -> dispatch -> payment.

Stock only moves at dispatch. Approval reserves finished goods so two salesmen
cannot both promise the same packet.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import (
    CompanySettings,
    CreditNote,
    Dispatch,
    Invoice,
    InvoiceLine,
    OrderLine,
    Payment,
    PaymentAllocation,
    SalesOrder,
    StockMovement,
    d,
    money,
)
from .audit import log_action
from .gst import next_invoice_number, same_state, tax_split
from .ledger import average_cost, on_hand, post_movement

RESERVING_STATUSES = (SalesOrder.Status.APPROVED, SalesOrder.Status.INVOICED)


def reserved_qty(item, exclude_order=None):
    rows = OrderLine.objects.filter(order__status__in=RESERVING_STATUSES, item=item)
    if exclude_order is not None:
        rows = rows.exclude(order=exclude_order)
    return sum((d(row.qty) for row in rows), Decimal("0"))


def available_stock(item, exclude_order=None):
    """On hand minus quantity already promised on approved, undispatched orders."""
    return on_hand(item) - reserved_qty(item, exclude_order)


def next_order_no(business_date):
    prefix = f"SO/{business_date:%y%m}/"
    n = SalesOrder.objects.filter(order_no__startswith=prefix).count() + 1
    while SalesOrder.objects.filter(order_no=f"{prefix}{n:03d}").exists():
        n += 1
    return f"{prefix}{n:03d}"


@transaction.atomic
def create_order(*, customer, salesman, lines, business_date, offline=False):
    """``lines`` is a list of (item, qty); prices come from the product master."""
    lines = [(item, d(q)) for item, q in lines if d(q) > 0]
    if not lines:
        raise ValueError("An order needs at least one line.")
    order = SalesOrder.objects.create(
        order_no=next_order_no(business_date),
        customer=customer,
        salesman=salesman,
        business_date=business_date,
        captured_offline=offline,
    )
    for item, q in lines:
        OrderLine.objects.create(order=order, item=item, qty=q, rate=item.selling_price)
    log_action(entity=order, action="created", user=salesman, detail=f"{order.customer}")
    return order


def stock_check(order):
    """Required vs available per line, with the shortage in packets."""
    rows = []
    for line in order.lines.select_related("item"):
        available = available_stock(line.item, exclude_order=order)
        required = d(line.qty)
        shortage = required - available
        rows.append(
            {
                "line": line,
                "item": line.item,
                "required": required,
                "available": available,
                "shortage": shortage if shortage > 0 else Decimal("0"),
                "covered": shortage <= 0,
            }
        )
    return rows


@transaction.atomic
def approve_order(order, user, partial=False):
    if order.status != SalesOrder.Status.SUBMITTED:
        raise ValueError("Only a submitted order can be approved.")
    checks = stock_check(order)
    if not all(row["covered"] for row in checks):
        if not partial:
            raise ValueError(
                "Not enough finished stock to approve this order in full."
            )
        for row in checks:
            line = row["line"]
            line.qty = d(row["available"]) if row["available"] > 0 else Decimal("0")
            line.save(update_fields=["qty"])
        order.lines.filter(qty=0).delete()
        if not order.lines.exists():
            raise ValueError("No line could be covered by available stock.")
        log_action(entity=order, action="approved-partial", user=user)
    else:
        log_action(entity=order, action="approved", user=user)
    order.status = SalesOrder.Status.APPROVED
    order.approved_by = user
    order.approved_at = timezone.now()
    order.save(update_fields=["status", "approved_by", "approved_at"])
    return order


@transaction.atomic
def reject_order(order, user, reason=""):
    if order.status not in (SalesOrder.Status.SUBMITTED, SalesOrder.Status.APPROVED):
        raise ValueError("This order can no longer be rejected.")
    order.status = SalesOrder.Status.REJECTED
    order.reject_reason = reason[:200]
    order.save(update_fields=["status", "reject_reason"])
    log_action(entity=order, action="rejected", user=user, detail=reason)
    return order


@transaction.atomic
def create_invoice(order, user, business_date=None):
    """Raise the GST invoice for an approved order. Stock is untouched here."""
    if order.status != SalesOrder.Status.APPROVED:
        raise ValueError("Only an approved order can be invoiced.")
    company = CompanySettings.get()
    business_date = business_date or timezone.localdate()
    is_same_state = same_state(order.customer, company)
    invoice_no, fy = next_invoice_number(business_date, company)

    invoice = Invoice.objects.create(
        invoice_no=invoice_no,
        financial_year=fy,
        customer=order.customer,
        order=order,
        business_date=business_date,
        place_of_supply=order.customer.state_code,
        created_by=user,
    )

    taxable_total = cgst_total = sgst_total = igst_total = Decimal("0")
    for line in order.lines.select_related("item"):
        taxable = money(d(line.qty) * d(line.rate))
        cgst, sgst, igst = tax_split(taxable, line.item.gst_rate, is_same_state)
        InvoiceLine.objects.create(
            invoice=invoice,
            item=line.item,
            qty=d(line.qty),
            rate=d(line.rate),
            taxable_value=taxable,
            gst_rate=d(line.item.gst_rate),
            cgst=cgst,
            sgst=sgst,
            igst=igst,
        )
        taxable_total += taxable
        cgst_total += cgst
        sgst_total += sgst
        igst_total += igst

    invoice.taxable_value = money(taxable_total)
    invoice.cgst = money(cgst_total)
    invoice.sgst = money(sgst_total)
    invoice.igst = money(igst_total)
    invoice.total = money(taxable_total + cgst_total + sgst_total + igst_total)
    invoice.save()

    order.status = SalesOrder.Status.INVOICED
    order.save(update_fields=["status"])
    log_action(entity=invoice, action="posted", user=user, detail=f"{invoice.total}")
    return invoice


@transaction.atomic
def dispatch_invoice(invoice, user, business_date=None):
    """Post the finished-goods issue and record the dispatch."""
    if invoice.status != Invoice.Status.POSTED:
        raise ValueError("A cancelled invoice cannot be dispatched.")
    if invoice.dispatches.exists():
        raise ValueError("This invoice is already dispatched.")
    business_date = business_date or timezone.localdate()

    total_qty = Decimal("0")
    for line in invoice.lines.select_related("item"):
        post_movement(
            item=line.item,
            qty=-d(line.qty),
            kind=StockMovement.Kind.DISPATCH,
            business_date=business_date,
            source_type="Invoice",
            source_id=invoice.pk,
            source_ref=invoice.invoice_no,
            user=user,
        )
        total_qty += d(line.qty)

    Dispatch.objects.create(
        invoice=invoice, business_date=business_date, qty=total_qty, created_by=user
    )
    if invoice.order_id:
        invoice.order.status = SalesOrder.Status.DISPATCHED
        invoice.order.save(update_fields=["status"])
    log_action(entity=invoice, action="dispatched", user=user, detail=f"{total_qty} packets")
    return invoice


@transaction.atomic
def cancel_invoice(invoice, user, reason):
    """Cancel by credit note. A posted invoice is never deleted."""
    if invoice.status == Invoice.Status.CANCELLED:
        raise ValueError("This invoice is already cancelled.")
    fy_part = invoice.financial_year
    count = CreditNote.objects.filter(note_no__startswith="CN/").count() + 1
    note_no = f"CN/{fy_part}/{count:04d}"
    while CreditNote.objects.filter(note_no=note_no).exists():
        count += 1
        note_no = f"CN/{fy_part}/{count:04d}"

    note = CreditNote.objects.create(
        note_no=note_no,
        invoice=invoice,
        business_date=timezone.localdate(),
        amount=invoice.total,
        reason=reason[:200],
        created_by=user,
    )

    # Put dispatched goods back on the shelf at current moving-average cost.
    if invoice.dispatches.exists():
        for line in invoice.lines.select_related("item"):
            post_movement(
                item=line.item,
                qty=d(line.qty),
                kind=StockMovement.Kind.ADJUSTMENT,
                business_date=note.business_date,
                source_type="CreditNote",
                source_id=note.pk,
                source_ref=note.note_no,
                user=user,
                unit_cost=average_cost(line.item) or d(line.rate),
                note="Returned against credit note",
            )

    invoice.status = Invoice.Status.CANCELLED
    invoice.save(update_fields=["status"])
    if invoice.order_id:
        order = invoice.order
        order.status = SalesOrder.Status.APPROVED
        order.save(update_fields=["status"])
    log_action(entity=invoice, action="cancelled", user=user, detail=note.note_no)
    return note


@transaction.atomic
def record_payment(
    *,
    customer,
    amount,
    business_date=None,
    user=None,
    mode="UPI",
    reference="",
    allocations=None,
):
    """Record a receipt; unallocated amounts go to the oldest open invoices."""
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    business_date = business_date or timezone.localdate()
    payment = Payment.objects.create(
        customer=customer,
        business_date=business_date,
        amount=amount,
        mode=mode,
        reference=reference,
        created_by=user,
    )

    if allocations:
        for invoice, value in allocations:
            PaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=money(value))
    else:
        remaining = amount
        open_invoices = Invoice.objects.filter(
            customer=customer, status=Invoice.Status.POSTED
        ).order_by("business_date", "id")
        for invoice in open_invoices:
            if remaining <= 0:
                break
            due = invoice.outstanding
            if due <= 0:
                continue
            take = min(due, remaining)
            PaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=take)
            remaining -= take

    log_action(entity=payment, action="recorded", user=user, detail=f"{amount}")
    return payment
