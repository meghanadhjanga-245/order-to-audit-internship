from django.core.management.base import BaseCommand

from ota import benchmark
from ota.models import Item


class Command(BaseCommand):
    help = "Load the Section 5 benchmark master data and opening stock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing app data first. Destroys all transactions.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            benchmark.reset_data()
        elif Item.objects.exists():
            self.stdout.write(
                self.style.WARNING(
                    "Data already present; nothing loaded. Use --reset to rebuild."
                )
            )
            return

        ctx = benchmark.seed()
        self.stdout.write(self.style.SUCCESS("Benchmark data loaded."))
        self.stdout.write("")
        self.stdout.write("  Logins (password: %s)" % benchmark.PASSWORD)
        for role, username in [
            ("Factory admin", benchmark.USERNAMES["admin"]),
            ("Production supervisor", benchmark.USERNAMES["production"]),
            ("Salesman A", benchmark.USERNAMES["salesman_a"]),
            ("Salesman B", benchmark.USERNAMES["salesman_b"]),
            ("Accountant / auditor", benchmark.USERNAMES["accountant"]),
            ("Owner", benchmark.USERNAMES["owner"]),
        ]:
            self.stdout.write(f"    {role:<24} {username}")
        self.stdout.write("")
        self.stdout.write(
            f"  Seeded: {Item.objects.count()} items, BOM for {ctx['murukku'].name}, "
            f"Retailer A and Distributor B."
        )
