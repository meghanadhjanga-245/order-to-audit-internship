"""The single writer of stock. Nothing else in the codebase touches balances.

Every receipt, issue, dispatch and adjustment goes through ``post_movement``.
Balances are always derived by summing ``StockMovement`` rows, so the ledger,
the stock summary and the stock ledger report can never disagree.
"""
from decimal import Decimal

from django.db import transaction

from ..models import Item, StockMovement, d, money, rate


class InsufficientStock(Exception):
    """Raised when an issue would take an item below zero."""

    def __init__(self, item, available, needed):
        self.item = item
        self.available = d(available)
        self.needed = d(needed)
        super().__init__(
            f"Insufficient stock for {item.code}: available {self.available}, needed {self.needed}"
        )


def ledger_totals(item):
    """Return (quantity, value) on hand for an item by summing the ledger."""
    total_qty = Decimal("0")
    total_value = Decimal("0")
    for row in StockMovement.objects.filter(item=item).only("qty", "value"):
        total_qty += d(row.qty)
        total_value += d(row.value)
    return total_qty, total_value


def on_hand(item):
    return ledger_totals(item)[0]


def average_cost(item):
    total_qty, total_value = ledger_totals(item)
    if total_qty <= 0:
        return Decimal("0.0000")
    return rate(total_value / total_qty)


@transaction.atomic
def post_movement(
    *,
    item,
    qty,
    kind,
    business_date,
    source_type="",
    source_id=None,
    source_ref="",
    user=None,
    unit_cost=None,
    value=None,
    batch="",
    note="",
):
    """Append one ledger row and return it.

    * Receipts (positive qty) must carry ``unit_cost`` or an explicit ``value``.
    * Issues (negative qty) are valued at the moving weighted average *before*
      the issue and may never drive the balance negative.
    * A ``REVALUATION`` row carries zero quantity and a value delta, which is how
      overheads are added to finished-goods value without touching quantities.
    """
    q = d(qty)
    kind = str(kind)

    if q == 0 and kind != StockMovement.Kind.REVALUATION:
        raise ValueError("A zero-quantity movement is only allowed for revaluation.")

    # Serialise concurrent writers per item on databases that support it.
    item = Item.objects.select_for_update().get(pk=item.pk)
    current_qty, current_value = ledger_totals(item)

    if q > 0:
        if value is None:
            if unit_cost is None:
                raise ValueError("A receipt needs a unit_cost or an explicit value.")
            value = money(q * d(unit_cost))
        value = money(value)
        unit_cost = rate(value / q)
    elif q < 0:
        if current_qty + q < 0:
            raise InsufficientStock(item, current_qty, -q)
        unit_cost = (current_value / current_qty) if current_qty > 0 else Decimal("0")
        value = money(q * unit_cost)
    else:  # revaluation: quantity unchanged, value adjusted
        if current_qty <= 0:
            raise ValueError("Cannot revalue an item with no stock on hand.")
        value = money(value)
        unit_cost = rate(value / current_qty)

    return StockMovement.objects.create(
        item=item,
        business_date=business_date,
        kind=kind,
        qty=q,
        unit_cost=unit_cost,
        value=value,
        source_type=source_type,
        source_id=source_id,
        source_ref=source_ref,
        batch=batch,
        created_by=user,
        note=note,
    )


def reverse_movement(*, movement, user, reason="", business_date=None):
    """Correction by reversal entry: the original row is never edited or deleted."""
    return post_movement(
        item=movement.item,
        qty=-d(movement.qty),
        kind=StockMovement.Kind.ADJUSTMENT,
        business_date=business_date or movement.business_date,
        source_type="Reversal",
        source_id=movement.pk,
        source_ref=f"Reversal of #{movement.pk}",
        user=user,
        unit_cost=d(movement.unit_cost) if d(movement.qty) > 0 else None,
        value=-d(movement.value) if d(movement.qty) < 0 else None,
        note=reason[:200],
    )
