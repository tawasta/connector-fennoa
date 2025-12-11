from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    fennoa_log_count = fields.Integer(
        string="Fennoa Logs",
        compute="_compute_fennoa_log_count",
    )

    def _compute_fennoa_log_count(self):
        for partner in self:
            partner.fennoa_log_count = self.env["fennoa.binding"].search_count(
                [("res_model", "=", "res.partner"), ("res_id", "=", partner.id)]
            )

    def action_view_fennoa_logs(self):
        """Open Fennoa bindings related to this partner."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Fennoa Logs"),
            "res_model": "fennoa.binding",
            "view_mode": "tree,form",
            "domain": [("res_model", "=", "res.partner"), ("res_id", "=", self.id)],
            "context": {"default_res_model": "res.partner", "default_res_id": self.id},
        }

    send_to_fennoa = fields.Boolean(
        string="Send to Fennoa",
        default=True,
        help=(
            "If enabled, this customer will be created/updated in Fennoa when an "
            "outgoing invoice is created."
        ),
    )
    fennoa_customer_id = fields.Integer(
        string="Fennoa Customer ID",
        readonly=True,
        help="ID of the customer in Fennoa.",
        index=True,
    )
    fennoa_customer_no = fields.Char(
        string="Fennoa Customer Number",
        readonly=True,
        help="Customer number in Fennoa.",
        index=True,
    )

    def _get_fennoa_backend(self):
        """Return available Fennoa backend for the partner's company."""
        self.ensure_one()
        _logger.info("Company for partner %s: %s", self.id, self.company_id.id)
        backend = self.env["fennoa.backend"].search(
            [("company_id", "=", self.company_id.id)],
            limit=1,
        )
        return backend

    @api.model
    def _fennoa_build_customer_payload(self, partner):
        """Create FORM DATA payload structure to send partner as a customer to Fennoa."""
        if not partner:
            raise UserError(_("No partner given for Fennoa payload build."))

        partner.ensure_one()

        if not partner.name:
            raise UserError(_("Cannot create customer in Fennoa without a name."))

        if not partner.country_id or not partner.country_id.code:
            raise UserError(
                _("Cannot create customer in Fennoa without country (ISO code).")
            )

        payload = {
            # customer_no: tyhjä -> Fennoa generoi sen
            "customer_no": partner.fennoa_customer_no or "",
            "name": partner.name,
            "address": partner.street or "",
            "postalcode": partner.zip or "",
            "city": partner.city or "",
            "country_id": partner.country_id.code or "",
            "description": partner.comment or "",
            "email": partner.email or "",
            "phone": partner.phone or "",
            "website": partner.website or "",
            "business_id": partner.vat or "",
            "account_type_id": 1 if partner.is_company else 2,
            "contact_person": partner.child_ids[:1].name if partner.child_ids else "",
        }
        return payload

    @api.model
    def _fennoa_ensure_customer(self, partner):
        """If partner should be synced and is not yet in Fennoa → create it there."""
        if not partner:
            raise UserError(_("No partner given for Fennoa ensure customer."))

        partner.ensure_one()

        if not partner.send_to_fennoa:
            return

        backend = partner._get_fennoa_backend()
        if not backend:
            raise UserError(
                _("No Fennoa backend configured for company %s.")
                % (partner.company_id.display_name,)
            )

        if partner.fennoa_customer_id:
            return

        payload = self._fennoa_build_customer_payload(partner)
        result = backend.api_create_customer(payload, partner=partner)

        partner_data = result.get("data") or []
        customer = partner_data.get("Customer") or {}

        partner.write(
            {
                "fennoa_customer_id": customer.get("id") or 0,
                "fennoa_customer_no": customer.get("customer_no") or "",
            }
        )
