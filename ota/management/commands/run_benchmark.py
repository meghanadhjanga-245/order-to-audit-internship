"""Replay Section 5 end to end and print every figure the evaluators check."""
from django.core.management.base import BaseCommand, CommandError

from ota import benchmark


class Command(BaseCommand):
    help = "Replay the Section 5 benchmark scenario on a clean database and verify it."

    def handle(self, *args, **options):
        benchmark.reset_data()
        ctx = benchmark.seed()
        results = benchmark.replay(ctx)

        self.stdout.write(self.style.MIGRATE_HEADING("Section 5 - benchmark results"))
        self.stdout.write("")
        self.stdout.write(f"  Flour weighted average rate   Rs {results['flour_average_rate']}")
        self.stdout.write(f"  Flour closing                 {results['flour_closing']} kg")
        self.stdout.write(f"  Oil closing                   {results['oil_closing']} L")
        self.stdout.write(f"  Spice mix closing             {results['spice_closing']} kg")
        self.stdout.write(f"  Pouches closing               {results['pouch_closing']} pcs")
        self.stdout.write(f"  Cartons closing               {results['carton_closing']} pcs")
        self.stdout.write(f"  Finished goods after run      {results['fg_after_run']} packets")
        self.stdout.write(f"  Finished goods after dispatch {results['fg_after_dispatch']} packets")
        self.stdout.write(f"  Yield variance                {results['yield_variance']}%")
        self.stdout.write(f"  Oil consumption variance      {results['oil_variance']}% (flagged: {results['oil_flagged']})")
        self.stdout.write(f"  Pouch variance                {results['pouch_variance']}%")
        self.stdout.write(f"  Carton variance               {results['carton_variance']}% (flagged: {results['carton_flagged']})")
        self.stdout.write(f"  Retailer A invoice            Rs {results['invoice_total']} "
                          f"({results['invoice_taxable']} + {results['invoice_cgst']} CGST + {results['invoice_sgst']} SGST)")
        self.stdout.write(f"  Retailer A outstanding        Rs {results['outstanding_a']}")
        self.stdout.write(f"  Distributor B shortage        {results['shortage_b']} packets "
                          f"(IGST if invoiced: Rs {results['igst_if_invoiced']})")
        self.stdout.write(f"  Run material cost             Rs {results['material_cost']}")
        self.stdout.write(f"  Run total cost                Rs {results['total_cost']}")
        self.stdout.write(f"  Cost per packet               Rs {results['cost_per_packet']}")
        self.stdout.write(f"  Margin per packet             Rs {results['margin_per_packet']}")
        self.stdout.write("")

        rows = benchmark.check(results)
        failures = [row for row in rows if not row[3]]
        self.stdout.write(self.style.MIGRATE_HEADING("Checks"))
        for key, expected, actual, ok in rows:
            mark = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
            self.stdout.write(f"  [{mark}] {key:<20} expected {expected:<12} actual {actual}")

        if failures:
            raise CommandError(f"{len(failures)} benchmark check(s) failed.")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"All {len(rows)} benchmark checks passed."))
