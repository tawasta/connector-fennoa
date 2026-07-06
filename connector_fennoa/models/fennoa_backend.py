import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class FennoaBackend(models.Model):
    _name = "fennoa.backend"
    _description = "Fennoa Backend"
    _inherit = ["api.request.mixin", "connector.backend"]
    _rec_name = "company_id"

    # region fields
    base_url = fields.Char(
        required=True,
        default="https://app.fennoa.com/api",
        help="Fennoa API base URL, usually https://app.fennoa.com/api",
    )
    client_identifier = fields.Char(
        required=True,
        string="API User",
        help="Fennoa API user / client identifier",
    )
    secret_key_b64 = fields.Char(
        required=True,
        string="API Key",
        help="Fennoa API key. Can be stored as base64 or as plain text.",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    binding_ids = fields.One2many("fennoa.binding", "backend_id", readonly=True)

    sale_invoice_auto_approve = fields.Boolean(
        string="Auto-approve sales invoice",
        help="Auto-approve sales invoices on confirmation",
        default=False,
    )

    sale_invoice_auto_send = fields.Boolean(
        string="Auto-send sales invoice",
        help="Auto-send sales invoices from Fennoa to customer on confirmation",
        default=False,
    )

    purchase_invoice_from_date = fields.Date(
        string="Import Purchase Invoices From",
        readonly=True,
    )
    purchase_invoice_to_date = fields.Date(
        string="Import Purchase Invoices To",
        readonly=True,
    )

    payments_from_date = fields.Date(
        string="Import Payments From",
        readonly=True,
    )
    payments_to_date = fields.Date(
        string="Import Payments To",
        readonly=True,
    )

    # endregion fields

    # region compute methods

    # endregion compute methods

    # region constraints and helpers

    def get_backend(self, company):
        """
        Return Fennoa backend record based on the current user company
        :param company: Company record
        :return: Fennoa backend record
        """

        if not company:
            # Fallback to current user's company
            company = self.env.company

        if isinstance(company, int):
            company_id = company
        else:
            company_id = company.id

        backend = self.search([("company_id", "=", company_id)])

        if not backend:
            raise UserError(
                _("Please configure a Fennoa backend for company {}.").format(
                    backend.company_id.name
                )
            )

        return backend

    @api.constrains("base_url")
    def _check_base_url(self):
        """Ensure base_url starts with http/https."""
        for rec in self:
            if rec.base_url and not rec.base_url.startswith(("http://", "https://")):
                raise ValidationError(
                    _("Fennoa base URL must start with http:// or https://.")
                )

    def _normalized_base_url(self):
        """Return base_url without trailing slash."""
        self.ensure_one()
        return (self.base_url or "").rstrip("/")

    # endregion constraints and helpers

    # region actions
    def action_test_connection(self):
        """Test API access by calling GET /customer_api."""
        for backend in self:
            backend._fennoa_api_request_make(
                "GET",
                "/customer_api/",
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("Fennoa API test succeeded."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_open_schedulers(self):
        """Open Fennoa-related cron jobs."""
        cron_jobs = (
            self.env["ir.cron"]
            .with_context(active_test=False)
            .search(
                [
                    ("name", "like", "Fennoa%"),
                ]
            )
        )
        backend_model = self.env.ref("connector_fennoa.model_fennoa_backend")

        return {
            "name": _("Fennoa Schedulers"),
            "type": "ir.actions.act_window",
            "res_model": "ir.cron",
            "view_mode": "tree,form",
            "domain": [("id", "in", cron_jobs.ids)],
            "context": {"default_model_id": backend_model.id},
        }

    def action_import_customers(self):
        """
        Fetch all customers from Fennoa and create them in Odoo (via background job).
        """
        self.ensure_one()

        job_desc = _("Fennoa: import customers for '%(company)s'") % {
            "company": self.company_id.display_name,
        }

        self.with_delay(description=job_desc)._import_customers()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import started"),
                "message": _("Importing customers in the background..."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_import_purchase_invoices(self):
        """
        Fetch all purchase invoices from Fennoa.
        """
        self.ensure_one()

        res = self._import_purchase_invoices()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import started"),
                "message": _(
                    "Importing %s purchase invoices in the background...", len(res)
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def _cron_import_payments(self):
        """
        Helper method to run payment import for all backends via cron job.
        """
        for backend in self.env["fennoa.backend"].sudo().search([]):
            backend.action_import_payments()

    def action_import_payments(self):
        """
        Fetch all payments from Fennoa and create them in Odoo (via background job).
        """
        self.ensure_one()

        job_desc = _("Fennoa: import payments for '%(company)s'") % {
            "company": self.company_id.display_name,
        }

        self.with_delay(description=job_desc)._import_payments()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import started"),
                "message": _("Importing payments in the background..."),
                "type": "success",
                "sticky": False,
            },
        }

    # endregion actions

    # region API calls

    # -------------------------------------------------------------------------
    # API: Customers
    # -------------------------------------------------------------------------
    def _import_customers(self):
        customer_list = self.api_get_customers()

        if not customer_list:
            return "No customers to import"

        Partner = self.env["res.partner"]
        jobs = 0

        for row in customer_list:
            customer = row.get("Customer") or {}
            if not customer:
                continue

            fennoa_id = customer.get("id")
            if not fennoa_id:
                continue

            job_desc = _("Fennoa: import customer '[%(id)s] %(name)s'") % {
                "id": fennoa_id,
                "name": customer.get("name") or "",
            }

            jobs += 1
            Partner.with_delay(description=job_desc)._fennoa_import_record(
                int(fennoa_id)
            )

        return "Import jobs for %s customers have been queued." % jobs

    def api_get_customers(self, params=None):
        """Fetch list of customers from Fennoa."""
        self.ensure_one()

        endpoint = "/customer_api/"
        res = self._fennoa_api_request_make(
            "GET",
            endpoint,
            params=params,
        )

        return res

    # -------------------------------------------------------------------------
    # API: Sales invoice payments
    # -------------------------------------------------------------------------

    def _format_fennoa_date(self, value, field_name):
        """Format a date/datetime/string to YYYY-MM-DD for Fennoa API."""
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, str):
            return value
        raise UserError(
            _("Invalid value for %(field)s in Fennoa payment query: %(value)s")
            % {"field": field_name, "value": value}
        )

    def _import_payments(self):
        from_date = self.payments_from_date
        to_date = self.payments_to_date

        if not from_date:
            from_date = fields.Date.today() - timedelta(days=30)
        if not to_date:
            to_date = fields.Date.today()

        payment_list = self.api_get_sales_payments(from_date, to_date)

        if not payment_list or not isinstance(payment_list, list):
            return "No payments to import"

        Payment = self.env["account.payment"]
        jobs = 0

        for payment in payment_list:
            payment_data = payment.get("SalesInvoicePayment") or {}
            job_desc = _("Fennoa: import payment [%(id)s] %(name)s") % {
                "id": payment_data.get("id"),
                "name": payment_data.get("description") or "",
            }

            jobs += 1
            Payment.with_delay(description=job_desc)._fennoa_import_record(
                payment,
                self.company_id,
            )

            self.payments_from_date = to_date

        return "Import jobs for %s payments have been queued." % jobs

    def api_get_sales_payments(self, from_date, to_date, created_after=None):
        """
        Fetch a list of payments to sales invoices from Fennoa.

        Wraps GET /sales_api/get/payments/<from_date>/<to_date>
        with optional /created_after:<date> suffix.
        """
        self.ensure_one()

        from_str = self._format_fennoa_date(from_date, "from_date")
        to_str = self._format_fennoa_date(to_date, "to_date")

        endpoint = f"/sales_api/get/payments/{from_str}/{to_str}"
        if created_after:
            created_str = self._format_fennoa_date(created_after, "created_after")
            endpoint = f"{endpoint}/created_after:{created_str}"

        res = self._fennoa_api_request_make("GET", endpoint)

        return res

    # -------------------------------------------------------------------------
    # API: Purchase invoices
    # -------------------------------------------------------------------------
    def _import_purchase_invoices(self):
        from_date = self.purchase_invoice_from_date
        to_date = self.purchase_invoice_to_date
        AccountInvoice = self.env["account.move"]

        if not from_date:
            from_date = fields.Date.today() - timedelta(days=30)
        if not to_date:
            to_date = fields.Date.today()

        res = self.api_get_purchase_invoices(from_date, to_date)

        for invoice in res:
            values = invoice.get("PurchaseInvoice") or {}
            fennoa_id = values.get("id")
            desc = f"Fennoa: import purchase invoice '{fennoa_id}'"
            AccountInvoice.with_delay(description=desc)._fennoa_import_record(
                fennoa_id,
                "purchase",
            )

        self.purchase_invoice_from_date = fields.Date.today()
        return res

    def api_get_purchase_invoices(self, from_date, to_date):
        """
        Fetch a list of purchase invoices from Fennoa.

        Get purchase invoices from
        /purchases_api/get/list?
        """
        self.ensure_one()

        from_str = self._format_fennoa_date(from_date, "from_date") + " 00:00:00"
        to_str = self._format_fennoa_date(to_date, "to_date") + " 23:59:59"
        params = {
            "createdAfter": from_str,
            "createdBefore": to_str,
            # TODO: configurable filter for approved invoices only
            # "isApproved": 1,
        }

        endpoint = "/purchases_api/get/list"

        res = self._fennoa_api_request_make("GET", endpoint, params=params)

        if not isinstance(res, list):
            raise ValidationError(
                _("Fennoa API returned unexpected response for purchase invoices.")
            )

        return res

    # endregion API calls
