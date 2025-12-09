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

    @api.constrains("base_url")
    def _check_base_url(self):
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
    ):
        self.ensure_one()

        url = self._build_url(path)
        auth = self._build_auth()
        headers = {"Accept": "application/json"}

        _logger.info("Fennoa request %s %s", method.upper(), url)

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
            }
        )

        return success, status, body, parsed

    def action_test_connection(self):
        for backend in self:
            success, status, body, _parsed = backend._send_request(
                "GET", "/customer_api/"
            )
            if not success:
                raise UserError(
                    _("Fennoa API test failed.\nStatus: %s\nResponse: %s")
                    % (status, body)
                )
        return True

    def api_create_customer(self, customer_data):
        self.ensure_one()

        success, status, body, parsed = self._send_request(
            "POST",
            "/customer_api/add",
            form_payload=customer_data,
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
