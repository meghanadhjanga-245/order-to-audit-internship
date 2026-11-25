"""GST: place-of-supply split, tax rounding and gap-free invoice numbering."""
from decimal import Decimal, ROUND_HALF_UP

from ..models import CompanySettings, InvoiceSequence, d, money

PAISA = Decimal("0.01")


def financial_year(business_date):
    """Indian financial year label for a date, e.g. 2026-11-22 -> '26-27'."""
    start = business_date.year if business_date.month >= 4 else business_date.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def same_state(customer, company=None):
    company = company or CompanySettings.get()
    return customer.state_code == company.state_code


def tax_split(taxable, gst_rate, is_same_state):
    """Return (cgst, sgst, igst), each rounded half-up to the paisa."""
    taxable = money(taxable)
    gst_rate = d(gst_rate)
    if is_same_state:
        half = (taxable * gst_rate / Decimal("200")).quantize(PAISA, rounding=ROUND_HALF_UP)
        return half, half, Decimal("0.00")
    igst = (taxable * gst_rate / Decimal("100")).quantize(PAISA, rounding=ROUND_HALF_UP)
    return Decimal("0.00"), Decimal("0.00"), igst


def next_invoice_number(business_date, company=None):
    """Take the next number in the current financial year under a row lock.

    Format stays inside the 16-character GST limit: TN/26-27/0001.
    Must be called inside a transaction.
    """
    company = company or CompanySettings.get()
    fy = financial_year(business_date)
    seq, _ = InvoiceSequence.objects.get_or_create(financial_year=fy)
    seq = InvoiceSequence.objects.select_for_update().get(pk=seq.pk)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"{company.invoice_prefix}/{fy}/{seq.last_number:04d}", fy
