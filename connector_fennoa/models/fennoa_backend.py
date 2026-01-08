import base64
import json
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
        if isinstance(company, int):
            company_id = company
        else:
            company_id = company.id

        backend = self.search(
            [
                ("company_id", "=", company_id),
            ]
        )

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

    def _build_auth(self):
        """Return Fennoa API authentication tuple (username, password)."""
        self.ensure_one()
        raw = self.secret_key_b64 or ""
        password = raw
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            if decoded:
                password = decoded
        except Exception:
            password = raw
        return (self.client_identifier, password)

    def _build_url(self, endpoint):
        """Build full request URL including base URL and endpoint."""
        base = self._normalized_base_url()
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        return f"{base}{endpoint}"

    def _get_headers(self):
        """Return common headers for Fennoa API requests."""
        return {
            "Accept": "application/json",
            "User-Agent": "Futural-Odoo-Fennoa-Connector/1.0",
        }

    def _send_request(
        self,
        method,
        endpoint,
        *,
        params=None,
        values=None,
        form_payload=None,
        json_payload=None,
        related_model=None,
        related_id=None,
    ):
        """
        Perform HTTP request to Fennoa API and log request/response.
        """
        self.ensure_one()

        url = self._build_url(endpoint)
        auth = self._build_auth()
        headers = self._get_headers()

        if json_payload is not None:
            headers["Content-Type"] = "application/json"
            payload = json_payload
        elif form_payload is not None:
            payload = form_payload
        else:
            payload = None

        kwargs = {
            "auth": auth,
            "headers": headers,
            "params": params or {},
            "values": values or {},
            "endpoint": url,
            "method": method,
            "payload": payload,
        }

        _logger.debug("Sending request to Fennoa: %s", kwargs)

        try:
            request = self._api_request_make(**kwargs)
        except ValidationError as e:
            _logger.error("Fennoa API request failed: %s", str(e))
            error_msg = self._format_api_error_message(e)
            raise ValidationError(error_msg) from e

        response = request.json().get("data") or request.json() or {}

        # TODO: different method for response handling / binding creation
        if not isinstance(response, dict):
            external_id = None
        elif response.get("id"):
            external_id = response.get("id")
        elif len(response) == 1:
            external_id = list(response.values())[0].get("id")
        else:
            external_id = None

        if external_id and related_model and related_id:
            FennoaBinding = self.env["fennoa.binding"].sudo()
            existing = FennoaBinding.search(
                [
                    ("backend_id", "=", self.id),
                    ("res_model", "=", related_model),
                    ("res_id", "=", related_id),
                    ("external_id", "=", external_id),
                ],
                limit=1,
            )
            if not existing:
                vals = {
                    "backend_id": self.id,
                    "res_model": related_model,
                    "res_id": related_id,
                    "external_id": external_id,
                }
                self.env["fennoa.binding"].create(vals)

        return response

    def _format_api_error_message(self, error):
        """
        Format API error message for user display.
        """
        error_dict = json.loads(str(error))
        error_msg = ""
        if isinstance(error_dict, dict):
            messages = []
            for key, value in error_dict.get("errors", {}).items():
                errors = ", ".join(value) if isinstance(value, list) else value
                messages.append(f"{key}: {errors}")
            error_msg = "\n".join(messages)
        else:
            error_msg = str(error)

        return error_msg

    # endregion constraints and helpers

    # region actions
    def action_test_connection(self):
        """Test API access by calling GET /customer_api."""
        for backend in self:
            backend._send_request(
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

    # -------------------------------------------------------------------------
    # API: GET Customers
    # -------------------------------------------------------------------------

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
        )._import_fennoa_customers()

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
    def _import_fennoa_customers(self):
        customer_list = self.api_get_customers()

        if not customer_list:
            return "No customers to import"

        for row in customer_list:
            customer = row.get("Customer") or {}
            if not customer:
                continue

            job_desc = _("Fennoa: import customer '[%(id)s] %(name)s'") % {
                "id": customer.get("id") or "",
                "name": customer.get("name") or "",
            }

            self.with_delay(description=job_desc)._import_fennoa_customer(customer)

        return "Import jobs for %s customers have been queued." % len(customer_list)

    def _import_fennoa_customer(self, customer):
        """Create missing Fennoa customers into Odoo."""
        Partner = self.env["res.partner"]
        Binding = self.env["fennoa.binding"]

        fennoa_id = customer.get("id")
        if not fennoa_id:
            return "Invalid customer data from Fennoa: missing ID"

        # Try to find existing binding
        existing = Binding.search(
            [
                ("backend_id", "=", self.id),
                ("external_id", "=", str(fennoa_id)),
                ("res_model", "=", Partner._name),
            ],
            limit=1,
        )
        if not existing:
            # Try to find existing partner by customer number
            existing = Partner.search(
                [
                    ("ref", "=", customer.get("customer_no") or ""),
                ],
                limit=1,
            )
        if existing:
            return "Customer already exists in Odoo, skipping import"

        country_code = customer.get("country_id") or ""
        country = False
        if country_code:
            country = self.env["res.country"].search(
                [("code", "=", country_code)], limit=1
            )

        # TODO: use importer instead of raw values
        vals = {
            "name": customer.get("name") or "",
            "street": customer.get("address") or "",
            "zip": customer.get("postalcode") or "",
            "city": customer.get("city") or "",
            "country_id": country.id if country else False,
            "email": customer.get("email") or "",
            "phone": customer.get("phone") or "",
            "vat": customer.get("business_id") or "",
            "comment": customer.get("description") or "",
            "website": customer.get("website") or "",
            "ref": customer.get("customer_no") or "",
            "company_id": self.company_id.id,
        }
        new_partner = Partner.create(vals)

        binding_vals = {
            "backend_id": self.id,
            "res_model": Partner._name,
            "external_id": fennoa_id,
            "res_id": new_partner.id,
        }

        Binding.create(binding_vals)
        return (
            f"Imported Fennoa customer ID '{fennoa_id}' "
            f"into Odoo with ID '{new_partner.id}'"
        )

    # -------------------------------------------------------------------------
    # API: Customers
    # -------------------------------------------------------------------------

    def api_create_customer(self, customer_data, partner=None):
        """Create a new customer in Fennoa using FORM DATA."""
        self.ensure_one()

        res = self._send_request(
            "POST",
            "/customer_api/add",
            form_payload=customer_data,
            related_model=partner._name if partner else None,
            related_id=partner.id if partner else None,
        )

        return res

    def api_update_customer(self, external_id, payload):
        """Update existing customer in Fennoa using JSON."""
        self.ensure_one()

        endpoint = f"/customer_api/{external_id}"
        res = self._send_request(
            "PUT",
            endpoint,
            json_payload=payload,
        )

        return res

    def api_get_customer_by_id(self, customer_id):
        """Fetch customer details by Fennoa internal ID."""
        self.ensure_one()

        endpoint = f"/customer_api/{customer_id}"
        try:
            res = self._send_request("GET", endpoint).get("Customer") or {}
        except ValidationError as e:
            _logger.warning(f"Customer with ID {customer_id} not found: %s", str(e))
            res = None

        return res

    def api_get_customer_by_number(self, customer_no):
        """Fetch customer by external customer number."""
        self.ensure_one()

        endpoint = f"/customer_api/get/customer_no/{customer_no}"
        try:
            res = self._send_request("GET", endpoint).get("Customer") or {}
        except ValidationError as e:
            _logger.warning(f"Customer with number {customer_no} not found: %s", str(e))
            res = None

        return res

    def api_get_customers(self, params=None):
        """Fetch list of customers from Fennoa."""
        self.ensure_one()

        endpoint = "/customer_api/"
        res = self._send_request(
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

        res = self._send_request(
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

        res = self._send_request("GET", endpoint)

        return res

    # endregion API calls
