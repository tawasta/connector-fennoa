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
        string="API Key (base64 or plain)",
        help="Fennoa API key. Can be stored as base64 or as plain text.",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    binding_ids = fields.One2many("fennoa.binding", "backend_id", readonly=True)
    # endregion fields

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

    def action_import_customers(self):
        """
        Fetch all customers from Fennoa and create them in Odoo (via background job).
        """
        self.ensure_one()

        job_desc = _("Fennoa: import customers for '%(company)s'") % {
            "company": self.company_id.display_name,
        }

        self.with_delay(
            description=job_desc,
            priority=30,
            max_retries=3,
        )._import_customers()

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

    def _cron_import_payments(self):
        """
        Helper method to run payment import for all backends via cron job.
        """
        for backend in self.env["fennoa.backend"].sudo().search([]):
            backend.action_import_payments()

    def action_import_payments(self, from_date=None, to_date=None, created_after=None):
        """
        Import Fennoa sales payments and apply them to invoices in Odoo.

        Designed to be called by a cron job and can also be run manually.
        """
        self.ensure_one()
        Move = self.env["account.move"]
        Payment = self.env["account.payment"]

        # Default date range: last 7 days if not provided
        if not from_date:
            from_date = (fields.Date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not to_date:
            to_date = fields.Date.today().strftime("%Y-%m-%d")

        result = self.api_get_sales_payments(
            from_date=from_date, to_date=to_date, created_after=created_after
        )
        _logger.info("RESULT: %s", result)

        payments = result.get("data") or []

        for payment_entry in payments:
            payment_data = payment_entry.get("SalesInvoicePayment") or {}
            invoice_data = payment_entry.get("SalesInvoice") or {}

            if not payment_data or not invoice_data:
                continue

            fennoa_payment_id = payment_data.get("id")
            fennoa_invoice_id = invoice_data.get("id")

            if not fennoa_payment_id or not fennoa_invoice_id:
                continue

            PaymentExists = Payment.search(
                [
                    ("fennoa_payment_id", "=", int(fennoa_payment_id)),
                    ("fennoa_invoice_id", "=", int(fennoa_invoice_id)),
                    ("company_id", "=", self.company_id.id),
                ],
                limit=1,
            )
            if PaymentExists:
                _logger.info(
                    "Payment for Fennoa payment ID %s already exists in Odoo, skipping",
                    fennoa_payment_id,
                )
                continue

            move = Move.search(
                [
                    ("fennoa_invoice_id", "=", int(fennoa_invoice_id)),
                    ("company_id", "=", self.company_id.id),
                    ("move_type", "in", ("out_invoice", "out_refund")),
                ],
                limit=1,
            )

            if move:
                ctx = {
                    "active_model": "account.move",
                    "active_ids": move.ids,
                }
                wizard = (
                    self.env["account.payment.register"]
                    .with_context(**ctx)
                    .create(
                        {
                            "payment_date": payment_data.get("date")
                            or fields.Date.today().strftime("%Y-%m-%d"),
                            "amount": float(payment_data.get("sum") or 0.0),
                            "communication": invoice_data.get("banking_reference")
                            or "",
                        }
                    )
                )

                odoo_payments = wizard._create_payments()

                # Tag payments with Fennoa ids
                for pay in odoo_payments:
                    pay.write(
                        {
                            "fennoa_payment_id": int(payment_data.get("id")),
                            "fennoa_invoice_id": int(invoice_data.get("id")),
                        }
                    )
                _logger.info(
                    "Created Odoo payments for Fennoa payment ID %s: %s",
                    fennoa_payment_id,
                    odoo_payments,
                )

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
            Partner.with_delay(description=job_desc).fennoa_import_record(
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
    # API: Sales Invoices
    # -------------------------------------------------------------------------

    def api_create_sales_invoice(self, invoice_data, move=None):
        """Send a new sales invoice to Fennoa (FORM DATA)."""
        self.ensure_one()

        res = self._fennoa_api_request_make(
            "POST",
            "/sales_api/add",
            form_payload=invoice_data,
            related_model=move._name if move else None,
            related_id=move.id if move else None,
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

    # endregion API calls
