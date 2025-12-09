import base64
import json
import logging

import requests
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class FennoaBackend(models.Model):
    _name = "fennoa.backend"
    _description = "Fennoa Backend"
    _inherit = "connector.backend"
    _rec_name = "company_id"

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

    def action_import_customers(self):
        """Fetch all customers from Fennoa and create them in Odoo."""
        self.ensure_one()
        response = self.api_get_customers(params={})

        customer_list = response.get("data") or []

        self._import_fennoa_customers(customer_list)

    def _import_fennoa_customers(self, customer_list):
        """Create missing Fennoa customers into Odoo."""
        Partner = self.env["res.partner"]
        for row in customer_list:
            customer = row.get("Customer") or {}
            if not customer:
                continue

            fennoa_id = customer.get("id")
            if not fennoa_id:
                continue

            existing = Partner.search(
                [
                    "|",
                    ("fennoa_customer_id", "=", fennoa_id),
                    ("fennoa_customer_no", "=", customer.get("customer_no") or ""),
                ],
                limit=1,
            )
            if existing:
                continue

            country_code = customer.get("country_id") or ""
            country = False
            if country_code:
                country = self.env["res.country"].search(
                    [("code", "=", country_code)], limit=1
                )

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
                "fennoa_customer_id": int(fennoa_id),
                "fennoa_customer_no": customer.get("customer_no") or "",
                "send_to_fennoa": True,
                "company_id": self.company_id.id,
            }

            Partner.create(vals)

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

    def _build_url(self, path):
        """Build full request URL including base URL and path."""
        base = self._normalized_base_url()
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}"

    def _send_request(
        self,
        method,
        path,
        *,
        params=None,
        form_payload=None,
        json_payload=None,
        related_model=None,
        related_id=None,
    ):
        """Perform HTTP request to Fennoa API and log request/response."""
        self.ensure_one()

        url = self._build_url(path)
        auth = self._build_auth()
        headers = {"Accept": "application/json"}

        try:
            kwargs = {
                "auth": auth,
                "headers": headers,
                "params": params or {},
                "timeout": 30,
            }
            if json_payload is not None:
                headers["Content-Type"] = "application/json"
                kwargs["json"] = json_payload
            elif form_payload is not None:
                kwargs["data"] = form_payload

            response = requests.request(method.upper(), url, **kwargs)

            status = response.status_code
            body = response.text
            success = 200 <= status < 300
        except requests.RequestException as exc:
            status = None
            body = str(exc)
            success = False

        parsed = None
        if body:
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = None

        payload_for_log = json_payload if json_payload is not None else form_payload
        self.env["fennoa.binding"].create(
            {
                "backend_id": self.id,
                "method": method.upper(),
                "endpoint": url,
                "payload": json.dumps(payload_for_log, ensure_ascii=False)
                if payload_for_log
                else "",
                "response": body,
                "status_code": status or 0,
                "successful": success,
                "res_model": related_model,
                "res_id": related_id,
            }
        )

        return success, status, body, parsed

    def action_test_connection(self):
        """Test API access by calling GET /customer_api."""
        for backend in self:
            success, status, body, _parsed = backend._send_request(
                "GET",
                "/customer_api/",
            )

            if not success:
                raise UserError(
                    _("Fennoa API test failed.\nStatus: %s\nResponse: %s")
                    % (status, body)
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
    # API: Customers
    # -------------------------------------------------------------------------

    def api_create_customer(self, customer_data, partner=None):
        """Create a new customer in Fennoa using FORM DATA."""
        self.ensure_one()

        success, status, body, parsed = self._send_request(
            "POST",
            "/customer_api/add",
            form_payload=customer_data,
            related_model=partner._name if partner else None,
            related_id=partner.id if partner else None,
        )

        if not success:
            extra = ""
            if parsed and isinstance(parsed, dict) and parsed.get("errors"):
                extra = "\nErrors: %s" % parsed.get("errors")
            raise UserError(
                _("Unable to add customer to Fennoa.\nStatus: %s\nResponse: %s%s")
                % (status, body, extra)
            )

        return parsed or {}

    def api_update_customer(self, customer_no, update_data):
        """Update existing customer in Fennoa using JSON."""
        self.ensure_one()

        path = f"/customer_api/{customer_no}"
        success, status, body, parsed = self._send_request(
            "PUT",
            path,
            json_payload=update_data,
        )

        if not success:
            extra = ""
            if parsed and isinstance(parsed, dict) and parsed.get("errors"):
                extra = "\nErrors: %s" % parsed.get("errors")
            raise UserError(
                _("Unable to update customer in Fennoa.\nStatus: %s\nResponse: %s%s")
                % (status, body, extra)
            )

        return parsed or {}

    def api_get_customer_by_id(self, customer_id):
        """Fetch customer details by Fennoa internal ID."""
        self.ensure_one()

        path = f"/customer_api/{customer_id}"
        success, status, body, parsed = self._send_request("GET", path)

        if not success:
            extra = ""
            if parsed and isinstance(parsed, dict) and parsed.get("errors"):
                extra = "\nErrors: %s" % parsed.get("errors")
            raise UserError(
                _("Unable to fetch customer from Fennoa.\nStatus: %s\nResponse: %s%s")
                % (status, body, extra)
            )

        return parsed or {}

    def api_get_customer_by_number(self, customer_no):
        """Fetch customer by external customer number."""
        self.ensure_one()

        path = f"/customer_api/get/customer_no/{customer_no}"
        success, status, body, parsed = self._send_request("GET", path)

        if not success:
            extra = ""
            if parsed and isinstance(parsed, dict) and parsed.get("errors"):
                extra = "\nErrors: %s" % parsed.get("errors")
            raise UserError(
                _("Unable to fetch customer from Fennoa.\nStatus: %s\nResponse: %s%s")
                % (status, body, extra)
            )

        return parsed or {}

    def api_get_customers(self, params=None):
        """Fetch list of customers from Fennoa."""
        self.ensure_one()

        path = "/customer_api/"
        success, status, body, parsed = self._send_request(
            "GET",
            path,
            params=params,
        )

        if not success:
            extra = ""
            if parsed and isinstance(parsed, dict) and parsed.get("errors"):
                extra = "\nErrors: %s" % parsed.get("errors")
            raise UserError(
                _("Unable to fetch customers from Fennoa.\nStatus: %s\nResponse: %s%s")
                % (status, body, extra)
            )

        return parsed or {}

    # -------------------------------------------------------------------------
    # API: Sales Invoices
    # -------------------------------------------------------------------------

    def api_create_sales_invoice(self, invoice_data, move=None):
        """Send a new sales invoice to Fennoa (FORM DATA)."""
        self.ensure_one()

        success, status, body, parsed = self._send_request(
            "POST",
            "/sales_api/add",
            form_payload=invoice_data,
            related_model=move._name if move else None,
            related_id=move.id if move else None,
        )

        if not success:
            extra = ""
            if parsed and isinstance(parsed, dict) and parsed.get("errors"):
                extra = "\nErrors: %s" % parsed.get("errors")
            raise UserError(
                _(
                    "Unable to add sales invoice to Fennoa.\n"
                    "Status: %s\nResponse: %s%s"
                )
                % (status, body, extra)
            )

        return parsed or {}

    def api_create_payment(self, payment_data):
        """Send a new payment to Fennoa (FORM DATA)."""
        self.ensure_one()

        success, status, body, parsed = self._send_request(
            "POST",
            "/payment_api/add",
            form_payload=payment_data,
        )

        if not success:
            extra = ""
            if parsed and isinstance(parsed, dict) and parsed.get("errors"):
                extra = "\nErrors: %s" % parsed.get("errors")
            raise UserError(
                _("Unable to add payment to Fennoa.\nStatus: %s\nResponse: %s%s")
                % (status, body, extra)
            )

        return parsed or {}
