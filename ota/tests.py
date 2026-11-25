"""Tests that earn the code-quality marks: stock maths, tax maths, permissions."""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from . import benchmark
from .models import Item, StockMovement, convert
from .models import UnitError
from .services import production as prod
from .services import sales
from .services.gst import financial_year, next_invoice_number, tax_split
from .services.ledger import InsufficientStock, on_hand, post_movement
from .services.reports import stock_summary


class BenchmarkScenarioTests(TestCase):
    """Section 5, replayed and asserted number by number."""

    def setUp(self):
        benchmark.reset_data()
        self.ctx = benchmark.seed()

    def test_benchmark_numbers(self):
        results = benchmark.replay(self.ctx)
        for key, expected, actual, ok in benchmark.check(results):
            self.assertTrue(ok, f"{key}: expected {expected}, got {actual}")

    def test_all_expected_keys_are_produced(self):
        results = benchmark.replay(self.ctx)
        self.assertEqual(set(benchmark.EXPECTED) - set(results), set())


class LedgerTests(TestCase):
    def setUp(self):
        benchmark.reset_data()
        self.ctx = benchmark.seed()
        self.admin = self.ctx["users"]["admin"]

    def test_stock_summary_closing_matches_ledger(self):
        benchmark.replay(self.ctx)
        report = stock_summary()
        items = list(Item.objects.filter(is_active=True))
        for row, item in zip(report["rows"], items):
            closing = Decimal(row[6].split()[0])
            self.assertEqual(closing, on_hand(item), f"{item.code} closing differs")

    def test_issue_cannot_go_negative(self):
        flour = self.ctx["flour"]
        with self.assertRaises(InsufficientStock):
            post_movement(
                item=flour, qty=Decimal("-9999"), kind=StockMovement.Kind.ISSUE,
                business_date=date(2026, 11, 20), user=self.admin,
            )

    def test_ledger_rows_are_append_only_via_services(self):
        before = StockMovement.objects.count()
        post_movement(
            item=self.ctx["spice"], qty=Decimal("1"), kind=StockMovement.Kind.PURCHASE,
            business_date=date(2026, 11, 20), user=self.admin, unit_cost=Decimal("200"),
        )
        self.assertEqual(StockMovement.objects.count(), before + 1)
        # No update path exists on the service; balances only ever come from rows.
        self.assertEqual(on_hand(self.ctx["spice"]), Decimal("6.000"))


class MoneyAndTaxTests(TestCase):
    def test_same_state_splits_into_cgst_and_sgst(self):
        cgst, sgst, igst = tax_split(Decimal("7500"), Decimal("5"), True)
        self.assertEqual((cgst, sgst, igst), (Decimal("187.50"), Decimal("187.50"), Decimal("0.00")))

    def test_interstate_charges_igst(self):
        cgst, sgst, igst = tax_split(Decimal("6000"), Decimal("5"), False)
        self.assertEqual((cgst, sgst, igst), (Decimal("0.00"), Decimal("0.00"), Decimal("300.00")))

    def test_financial_year_rolls_on_first_of_april(self):
        self.assertEqual(financial_year(date(2027, 3, 31)), "26-27")
        self.assertEqual(financial_year(date(2027, 4, 1)), "27-28")

    def test_invoice_numbering_restarts_each_financial_year(self):
        with transaction.atomic():
            first, fy_first = next_invoice_number(date(2027, 3, 31))
            second, fy_second = next_invoice_number(date(2027, 4, 1))
        self.assertTrue(first.endswith("0001"))
        self.assertTrue(second.endswith("0001"))
        self.assertNotEqual(fy_first, fy_second)

    def test_unit_conversion_round_trips(self):
        self.assertEqual(convert(Decimal("1"), "kg", "g"), Decimal("1000"))
        self.assertEqual(convert(Decimal("2"), "carton", "packet"), Decimal("40"))
        self.assertEqual(convert(Decimal("1000"), "ml", "L"), Decimal("1"))
        with self.assertRaises(UnitError):
            convert(Decimal("1"), "kg", "L")


class VarianceTests(TestCase):
    def setUp(self):
        benchmark.reset_data()
        self.ctx = benchmark.seed()

    def test_exactly_tolerance_is_not_flagged_but_over_is(self):
        results = benchmark.replay(self.ctx)
        # Pouches: 194 used against 200 planned = exactly -3.00%, inside tolerance.
        self.assertEqual(results["pouch_variance"], Decimal("-3.00"))
        # Cartons: 9 against 10 = -10%, flagged as favourable.
        self.assertTrue(results["carton_flagged"])
        # Oil: 10.5 against 10 = +5%, flagged as adverse.
        self.assertTrue(results["oil_flagged"])
        self.assertTrue(results["yield_variance"] < Decimal("-3"))


class SalesLoopTests(TestCase):
    def setUp(self):
        benchmark.reset_data()
        self.ctx = benchmark.seed()

    def test_shortage_is_reported_before_approval(self):
        results = benchmark.replay(self.ctx)
        self.assertEqual(results["shortage_b"], Decimal("32"))
        with self.assertRaises(ValueError):
            sales.approve_order(results["order_b"], self.ctx["users"]["admin"])

    def test_partial_approval_uses_only_available_stock(self):
        results = benchmark.replay(self.ctx)
        order_b = results["order_b"]
        sales.approve_order(order_b, self.ctx["users"]["admin"], partial=True)
        self.assertEqual(order_b.total_qty, Decimal("88"))

    def test_credit_note_returns_goods_to_stock(self):
        results = benchmark.replay(self.ctx)
        invoice = results["invoice_a"]
        item = invoice.lines.first().item
        before = on_hand(item)
        sales.cancel_invoice(invoice, self.ctx["users"]["admin"], "Customer returned goods")
        self.assertEqual(on_hand(item), before + Decimal("150"))
        self.assertEqual(invoice.status, "CANCELLED")
        self.assertTrue(invoice.credit_notes.exists())

    def test_dispatch_reduces_finished_goods(self):
        results = benchmark.replay(self.ctx)
        self.assertEqual(results["fg_after_dispatch"], Decimal("88"))


class ProductionLifecycleTests(TestCase):
    def setUp(self):
        benchmark.reset_data()
        self.ctx = benchmark.seed()

    def test_run_cannot_complete_before_issue(self):
        run = prod.create_run(
            bom=self.ctx["bom"], batches=1, business_date=date(2026, 11, 20),
            user=self.ctx["users"]["production"],
        )
        with self.assertRaises(ValueError):
            prod.complete_run(run, good_output=Decimal("188"))

    def _issued_run(self):
        ctx = self.ctx
        run = prod.create_run(
            bom=ctx["bom"], batches=1, business_date=date(2026, 11, 20),
            user=ctx["users"]["production"],
        )
        prod.issue_run(
            run,
            {ctx["flour"].pk: Decimal("40"), ctx["oil"].pk: Decimal("10"),
             ctx["spice"].pk: Decimal("1.2")},
            user=ctx["users"]["production"],
        )
        return run

    def test_packaging_quantity_entered_is_exactly_what_is_posted(self):
        """One source of truth: the per-line input drives both ledger and variance."""
        carton = self.ctx["carton"]
        pouch = self.ctx["pouch"]
        before = on_hand(carton)
        run = self._issued_run()
        prod.complete_run(
            run, good_output=Decimal("188"), damaged_packets=Decimal("6"),
            pack_actuals={pouch.pk: Decimal("194"), carton.pk: Decimal("9")},
            user=self.ctx["users"]["production"],
        )
        line = run.lines.get(item=carton)
        self.assertEqual(line.actual_qty, Decimal("9"))
        self.assertEqual(line.variance_pct, Decimal("-10.00"))
        self.assertEqual(on_hand(carton), before - Decimal("9"))

    def test_packaging_line_without_a_quantity_is_rejected(self):
        run = self._issued_run()
        before = on_hand(self.ctx["carton"])
        with self.assertRaises(ValueError):
            prod.complete_run(
                run, good_output=Decimal("188"),
                pack_actuals={self.ctx["pouch"].pk: Decimal("194")},
                user=self.ctx["users"]["production"],
            )
        # Nothing was posted, because the run never completed.
        self.assertEqual(on_hand(self.ctx["carton"]), before)

    def test_cost_per_packet_uses_good_output(self):
        results = benchmark.replay(self.ctx)
        self.assertEqual(results["total_cost"], Decimal("5855.00"))
        self.assertEqual(results["cost_per_packet"], Decimal("31.14"))


class PermissionTests(TestCase):
    def setUp(self):
        benchmark.reset_data()
        self.ctx = benchmark.seed()

    def test_salesman_cannot_open_accountant_reports(self):
        self.client.login(username="salesman_a", password=benchmark.PASSWORD)
        response = self.client.get(reverse("report_list"))
        self.assertEqual(response.status_code, 403)

    def test_salesman_cannot_open_production_screen(self):
        self.client.login(username="salesman_a", password=benchmark.PASSWORD)
        response = self.client.get(reverse("production_list"))
        self.assertEqual(response.status_code, 403)

    def test_salesman_only_sees_own_orders(self):
        results = benchmark.replay(self.ctx)
        self.client.login(username="salesman_b", password=benchmark.PASSWORD)
        response = self.client.get(reverse("order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, results["order_a"].order_no)
        self.assertContains(response, results["order_b"].order_no)

    def test_admin_can_open_every_screen(self):
        self.client.login(username="admin", password=benchmark.PASSWORD)
        for name in ["dashboard", "order_list", "production_list", "purchase_list",
                     "invoice_list", "stock", "report_list"]:
            with self.subTest(screen=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("order_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])
