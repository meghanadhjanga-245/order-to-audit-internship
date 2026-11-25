from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/new/", views.order_create, name="order_create"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("production/", views.production_list, name="production_list"),
    path("production/new/", views.production_create, name="production_create"),
    path("production/plan/", views.production_plan, name="production_plan"),
    path("production/<int:pk>/", views.production_detail, name="production_detail"),
    path("purchases/", views.purchase_list, name="purchase_list"),
    path("purchases/new/", views.purchase_create, name="purchase_create"),
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/pdf/", views.invoice_pdf_view, name="invoice_pdf"),
    path("payments/new/", views.payment_create, name="payment_create"),
    path("stock/", views.stock_view, name="stock"),
    path("reports/", views.report_list, name="report_list"),
    path("reports/<str:key>/", views.report_view, name="report_view"),
    path("benchmark/", views.benchmark_studio, name="benchmark_studio"),
    path("switch-user/<str:username>/", views.switch_user, name="switch_user"),
]
