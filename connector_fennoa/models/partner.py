from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    send_to_fennoa = fields.Boolean(
        string="Send to Fennoa",
        help=(
            "If enabled, this customer will be created/updated in Fennoa when an "
            "outgoing invoice is created."
        ),
    )
    fennoa_customer_id = fields.Integer(
        string="Fennoa Customer ID",
        readonly=True,
        help="ID of the customer in Fennoa.",
    )
    fennoa_customer_no = fields.Char(
        string="Fennoa Customer Number",
        readonly=True,
        help="Customer number in Fennoa.",
    )

    def _get_fennoa_backend(self):
        self.ensure_one()
        backend = self.env["fennoa.backend"].search(
            [("company_id", "=", self.company_id.id)],
            limit=1,
        )
        return backend

    @api.model
    def _fennoa_build_customer_payload(self, partner):
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
            "fax": partner.fax or "",
            "website": partner.website or "",
            "business_id": partner.vat or "",
            "account_type_id": 1 if partner.is_company else 2,
            "contact_person": partner.child_ids[:1].name if partner.child_ids else "",
        }
        return payload

    @api.model
    def _fennoa_ensure_customer(self, partner):
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
        result = backend.api_create_customer(payload)

        partner.write(
            {
                "fennoa_customer_id": result.get("id") or 0,
                "fennoa_customer_no": result.get("customer_no") or "",
            }
        )
