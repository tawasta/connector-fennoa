import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    fennoa_binding_count = fields.Integer(
        string="Fennoa Logs",
        compute="_compute_fennoa_binding_count",
    )
    fennoa_binding_ids = fields.One2many(
        comodel_name="fennoa.binding",
        inverse_name="res_id",
        string="Fennoa Bindings",
        domain=[("res_model", "=", "res.partner")],
    )
    fennoa_export = fields.Boolean(
        string="Export to Fennoa",
        help="Disable this to prevent exporting partner to Fennoa",
        default=True,
    )

    def _compute_fennoa_binding_count(self):
        for record in self:
            record.fennoa_binding_count = len(self.fennoa_binding_ids)

    def get_combined_street(self):
        """
        Get combined string for street and street2
        :return: String with streets
        """
        if not self:
            # If function is called without records
            return ""

        self.ensure_one()
        if self.street and self.street2:
            street = f"{self.street} {self.street2}"
        else:
            street = self.street or ""

        return street

    def action_view_fennoa_bindings(self):
        """Open Fennoa bindings related to this record."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Fennoa Bindings"),
            "res_model": "fennoa.binding",
            "view_mode": "tree,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {"default_res_model": self._name, "default_res_id": self.id},
        }

    def action_fennoa_export_record(self):
        """Export record to Fennoa"""
        for record in self:
            record.fennoa_export_record()
        return True

    def action_fennoa_import_record(self):
        """Update record from Fennoa."""
        _logger.error("Importing record from Fennoa not implemented!")
        return True

    # TODO: use exporter instead of raw payload
    @api.model
    def _fennoa_build_customer_payload(self):
        """
        Create FORM DATA payload structure to send partner as a customer to Fennoa.
        """

        self.ensure_one()

        # TODO: separate validation method (for extendability)
        if not self.name:
            raise UserError(_("Cannot create customer in Fennoa without a name."))

        if not self.country_id or not self.country_id.code:
            raise UserError(
                _("Cannot create customer in Fennoa without country (ISO code).")
            )

        payload = {
            # If empty, Fennoa will generate a customer number
            "customer_no": self.ref or "",
            "name": self.name,
            "address": self.get_combined_street(),
            "postalcode": self.zip or "",
            "city": self.city or "",
            "country_id": self.country_id.code or "",
            "description": self.comment or "",
            "email": self.email or "",
            "phone": self.phone or "",
            "website": self.website or "",
            "business_id": self.vat or "",
            "account_type_id": 1 if self.is_company else 2,
            # TODO: contact person handling, this is incorrect
            # "contact_person": self.child_ids[:1].name if self.child_ids else "",
        }
        return payload

    @api.model
    def fennoa_export_record(self):
        """
        Export partner as a customer to Fennoa if not already exported.
        """
        self.ensure_one()

        if not self.fennoa_export:
            return

        backend = (
            self.env["fennoa.backend"]
            .sudo()
            .get_backend(company=self.company_id or self.env.company)
        )

        # TODO: use exporter
        payload = self._fennoa_build_customer_payload()

        binding = self.fennoa_binding_ids.filtered(lambda b: b.backend_id == backend)
        if not binding and self.ref:
            # Try to find existing partner from Fennoa and create a binding
            fennoa_customer = backend.api_get_customer_by_number(self.ref)
            if fennoa_customer:
                binding = (
                    self.env["fennoa.binding"]
                    .sudo()
                    .create(
                        {
                            "backend_id": backend.id,
                            "external_id": fennoa_customer.get("id"),
                            "res_model": self._name,
                            "res_id": self.id,
                        }
                    )
                )
        if binding:
            # Already exported
            result = backend.api_update_customer(self.ref, payload)
        else:
            # Create new partner
            result = backend.api_create_customer(payload, partner=self)

        return result
