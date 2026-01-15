import base64
import json
import logging

from odoo import models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ApiRequestMixin(models.Model):
    _inherit = "api.request.mixin"

    def _get_fennoa_backend(self):
        company = self.company_id or self.env.company

        backend = self.env["fennoa.backend"].search([("company_id", "=", company.id)])

        return backend

    def _build_auth(self):
        """Return Fennoa API authentication tuple (username, password)."""
        raw = self._get_fennoa_backend().secret_key_b64 or ""
        password = raw
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            if decoded:
                password = decoded
        except Exception:
            password = raw
        return (self._get_fennoa_backend().client_identifier, password)

    def _build_url(self, endpoint):
        """Build full request URL including base URL and endpoint."""
        base = self._get_fennoa_backend()._normalized_base_url()
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        return f"{base}{endpoint}"

    def _get_headers(self):
        """Return common headers for Fennoa API requests."""
        return {
            "Accept": "application/json",
            "User-Agent": "Futural-Odoo-Fennoa-Connector/1.0",
        }

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

    def _fennoa_api_request_make(
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
            backend = self._get_fennoa_backend()
            existing = FennoaBinding.search(
                [
                    ("backend_id", "=", backend.id),
                    ("res_model", "=", related_model),
                    ("res_id", "=", related_id),
                    ("external_id", "=", external_id),
                ],
                limit=1,
            )
            if not existing:
                vals = {
                    "backend_id": backend.id,
                    "res_model": related_model,
                    "res_id": related_id,
                    "external_id": external_id,
                }
                self.env["fennoa.binding"].create(vals)

        return response
