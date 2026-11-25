from decimal import Decimal

from django import forms
from django.forms import formset_factory

from .models import (
    BOM,
    Customer,
    Item,
    ItemKind,
    PurchaseLine,
    Supplier,
)


def _fg_items():
    return Item.objects.filter(kind=ItemKind.FG, is_active=True)


class OrderLineForm(forms.Form):
    item = forms.ModelChoiceField(queryset=Item.objects.none(), required=False, empty_label="-")
    qty = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=12, decimal_places=3, initial=0
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = _fg_items()


OrderLineFormSet = formset_factory(OrderLineForm, extra=3)


class OrderForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none())
    business_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    captured_offline = forms.BooleanField(
        required=False, label="Captured offline (sent when network returned)"
    )

    def __init__(self, *args, salesman=None, **kwargs):
        super().__init__(*args, **kwargs)
        customers = Customer.objects.all()
        if salesman is not None and not salesman.is_superuser:
            customers = customers.filter(salesman=salesman)
        self.fields["customer"].queryset = customers.order_by("name")


class ProductionRunForm(forms.Form):
    bom = forms.ModelChoiceField(queryset=BOM.objects.none(), label="Product / BOM")
    batches = forms.DecimalField(
        min_value=Decimal("0.001"), max_digits=8, decimal_places=3, initial=1
    )
    business_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bom"].queryset = BOM.objects.filter(is_active=True).select_related("product")


class CompleteRunForm(forms.Form):
    good_output = forms.DecimalField(min_value=Decimal("0"), max_digits=12, decimal_places=3)
    damaged_packets = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=12, decimal_places=3, initial=0
    )


class OverheadForm(forms.Form):
    labour = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, initial=0)
    power = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, initial=0)
    other = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, initial=0)


class PurchaseLineForm(forms.Form):
    item = forms.ModelChoiceField(queryset=Item.objects.none(), required=False, empty_label="-")
    qty = forms.DecimalField(required=False, min_value=Decimal("0"), max_digits=14, decimal_places=3)
    rate = forms.DecimalField(required=False, min_value=Decimal("0"), max_digits=14, decimal_places=4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.objects.filter(
            kind__in=[ItemKind.RAW, ItemKind.PACK], is_active=True
        )


PurchaseLineFormSet = formset_factory(PurchaseLineForm, extra=3)


class PurchaseForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.none())
    bill_no = forms.CharField(max_length=40)
    bill_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.order_by("name")


class PaymentForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none())
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    business_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    mode = forms.ChoiceField(choices=[("UPI", "UPI"), ("CASH", "Cash"), ("NEFT", "NEFT"), ("CHEQUE", "Cheque")])
    reference = forms.CharField(required=False, max_length=60)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.order_by("name")
