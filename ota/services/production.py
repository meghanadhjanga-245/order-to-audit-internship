"""Production runs: BOM snapshot, issue, completion, variance and costing.

Lifecycle: DRAFT -> ISSUED -> COMPLETED -> COSTED

* Draft snapshots the BOM so later BOM edits never rewrite history.
* Issue posts raw-material issues to the ledger at moving average cost.
* Complete posts packaging consumption and the finished-goods receipt at
  material cost, so stored value tracks what the run actually consumed.
* Costing adds overheads as a zero-quantity revaluation row, which keeps
  quantity untouched while moving value.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from ..models import (
    BOM,
    ItemKind,
    ProductionRun,
    RunLine,
    RunOverhead,
    StockMovement,
    d,
    money,
    qty as q3,
    rate,
)
from .ledger import post_movement

TOLERANCE_DEFAULT = Decimal("3.00")


def next_run_no(business_date):
    prefix = f"PR/{business_date:%y%m}/"
    n = ProductionRun.objects.filter(run_no__startswith=prefix).count() + 1
    while ProductionRun.objects.filter(run_no=f"{prefix}{n:03d}").exists():
        n += 1
    return f"{prefix}{n:03d}"


@transaction.atomic
def create_run(*, bom, batches, business_date, user=None, run_no=None):
    batches = d(batches)
    if batches <= 0:
        raise ValueError("Batches must be greater than zero.")
    run = ProductionRun.objects.create(
        bom=bom,
        run_no=run_no or next_run_no(business_date),
        business_date=business_date,
        batches=batches,
        expected_output=q3(d(bom.expected_yield) * batches),
        created_by=user,
    )
    for line in bom.lines.select_related("item"):
        RunLine.objects.create(
            run=run,
            item=line.item,
            planned_qty=q3(d(line.qty_per_batch) * batches),
        )
    return run


@transaction.atomic
def issue_run(run, issued_by_item, user=None, business_date=None):
    """Issue raw materials. ``issued_by_item`` maps item id -> quantity."""
    if run.status != ProductionRun.Status.DRAFT:
        raise ValueError("Only a draft run can be issued.")
    business_date = business_date or run.business_date
    for line in run.lines.select_related("item"):
        if line.item.kind == ItemKind.PACK:
            continue  # packaging is consumed at completion
        issued = d(issued_by_item.get(line.item_id, d(line.planned_qty)))
        movement = post_movement(
            item=line.item,
            qty=-issued,
            kind=StockMovement.Kind.ISSUE,
            business_date=business_date,
            source_type="ProductionRun",
            source_id=run.pk,
            source_ref=run.run_no,
            user=user,
        )
        line.actual_qty = issued
        line.unit_cost = movement.unit_cost
        line.value = -d(movement.value)  # cost is kept positive on the run line
        line.save(update_fields=["actual_qty", "unit_cost", "value"])
    run.status = ProductionRun.Status.ISSUED
    run.issued_at = timezone.now()
    run.save(update_fields=["status", "issued_at"])
    return run


@transaction.atomic
def complete_run(
    run,
    *,
    good_output,
    damaged_packets=Decimal("0"),
    pack_actuals=None,
    user=None,
    business_date=None,
):
    """Record actual output, consume packaging, and receipt finished goods.

    ``pack_actuals`` maps packaging item id -> quantity actually used, and is
    the single source of truth for packaging consumption: whatever is entered
    is exactly what is posted to the ledger and compared against the plan.
    """
    if run.status != ProductionRun.Status.ISSUED:
        raise ValueError("Only an issued run can be completed.")
    business_date = business_date or run.business_date
    good_output = d(good_output)
    damaged = d(damaged_packets)
    if good_output <= 0:
        raise ValueError("Good output must be greater than zero.")
    if good_output > d(run.expected_output):
        raise ValueError("Good output cannot exceed the expected output of the run.")

    pack_actuals = {int(k): d(v) for k, v in (pack_actuals or {}).items()}

    for line in run.lines.select_related("item"):
        if line.item.kind != ItemKind.PACK:
            continue
        # No fallback estimate: an unentered packaging line is an error, so the
        # quantity posted can only ever be the quantity the supervisor entered.
        if line.item_id not in pack_actuals:
            raise ValueError(f"Enter the quantity used for {line.item.name}.")
        used = pack_actuals[line.item_id]
        movement = post_movement(
            item=line.item,
            qty=-used,
            kind=StockMovement.Kind.ISSUE,
            business_date=business_date,
            source_type="ProductionRun",
            source_id=run.pk,
            source_ref=run.run_no,
            user=user,
        )
        line.actual_qty = used
        line.unit_cost = movement.unit_cost
        line.value = -d(movement.value)
        line.save(update_fields=["actual_qty", "unit_cost", "value"])

    run.good_output = q3(good_output)
    run.damaged_packets = q3(damaged)
    run.status = ProductionRun.Status.COMPLETED
    run.completed_at = timezone.now()
    run.save()

    material_cost = run.material_cost
    post_movement(
        item=run.bom.product,
        qty=good_output,
        kind=StockMovement.Kind.RECEIPT,
        business_date=business_date,
        source_type="ProductionRun",
        source_id=run.pk,
        source_ref=run.run_no,
        user=user,
        value=material_cost,
        note=f"Production receipt {run.run_no} at material cost",
    )
    return run


@transaction.atomic
def add_overhead(run, *, kind, amount, note=""):
    # Overheads routinely arrive after dispatch (electricity bills, wage sheets),
    # so a completed run still accepts them; only a costed run is locked.
    if run.status == ProductionRun.Status.COSTED:
        raise ValueError("A costed run is locked; raise a correction instead.")
    return RunOverhead.objects.create(run=run, kind=kind, amount=money(amount), note=note)


@transaction.atomic
def set_overheads(run, items, user=None, business_date=None):
    """Replace a run's overheads. ``items`` is a list of (kind, amount)."""
    if run.status == ProductionRun.Status.COSTED:
        raise ValueError("A costed run's overheads are locked; raise a correction instead.")
    run.overheads.all().delete()
    for kind, amount in items:
        if d(amount) > 0:
            add_overhead(run, kind=kind, amount=amount)
    return run


@transaction.atomic
def cost_run(run, user=None, business_date=None):
    """Post overheads into finished-goods value and compute cost per packet."""
    if run.status != ProductionRun.Status.COMPLETED:
        raise ValueError("Only a completed run can be costed.")
    overhead = run.overhead_cost
    if overhead > 0:
        post_movement(
            item=run.bom.product,
            qty=Decimal("0"),
            kind=StockMovement.Kind.REVALUATION,
            business_date=business_date or run.business_date,
            source_type="ProductionRun",
            source_id=run.pk,
            source_ref=run.run_no,
            user=user,
            value=overhead,
            note="Overhead allocation",
        )
    run.status = ProductionRun.Status.COSTED
    run.save(update_fields=["status"])
    return run


def variance_table(run):
    """Per-line planned vs actual with an adverse/favourable flag."""
    rows = []
    for line in run.lines.select_related("item"):
        variance = line.variance_pct
        tolerance = d(line.item.tolerance_pct) or TOLERANCE_DEFAULT
        flagged = variance is not None and abs(variance) > tolerance
        rows.append(
            {
                "item": line.item,
                "planned": d(line.planned_qty),
                "actual": d(line.actual_qty),
                "variance": variance,
                "tolerance": tolerance,
                "flagged": flagged,
                "direction": (
                    "" if not flagged else ("favourable" if variance < 0 else "adverse")
                ),
                "cost": d(line.value or 0),
            }
        )
    expected = d(run.expected_output)
    yield_variance = None
    if expected > 0:
        yield_variance = ((d(run.good_output) - expected) / expected * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    tolerance = d(run.bom.tolerance_pct) or TOLERANCE_DEFAULT
    return {
        "lines": rows,
        "yield_variance": yield_variance,
        "yield_flagged": yield_variance is not None and abs(yield_variance) > tolerance,
    }
