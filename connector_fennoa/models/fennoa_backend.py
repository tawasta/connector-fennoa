import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import quote

import requests
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class FennoaBackend(models.Model):
    _name = "fennoa.backend"
    _description = "Fennoa Backend"
    _inherit = "connector.backend"
    _rec_name = "company_id"

    base_url = fields.Char(required=True)
    client_identifier = fields.Char(required=True)
    secret_key_b64 = fields.Char(required=True)
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
