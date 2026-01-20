import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _name = "res.partner"
    _inherit = ["res.partner", "api.request.mixin"]

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
    fennoa_binding_id = fields.Many2one(
        comodel_name="fennoa.binding",
        string="Fennoa Binding",
        compute="_compute_fennoa_binding_id",
    )
    fennoa_id = fields.Integer(
        string="Fennoa Invoice ID",
        related="fennoa_binding_id.external_id",
        compute="_compute_fennoa_binding_id",
    )
    fennoa_export = fields.Boolean(
        string="Export to Fennoa",
        help="Disable this to prevent exporting partner to Fennoa",
        default=True,
    )

    def _compute_fennoa_binding_count(self):
        for record in self:
            record.fennoa_binding_count = len(self.fennoa_binding_ids)

    def _compute_fennoa_binding_id(self):
        """
        Helper for getting the correct binding for this record.
        """
        FennoaBinding = self.env["fennoa.binding"].sudo()
        for record in self:
            vals = {
                "fennoa_binding_id": False,
                "fennoa_id": False,
            }

            binding = FennoaBinding.search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "=", record.id),
                    ("company_id", "=", record.company_id.id),
                ],
                limit=1,
            )

            if binding:
                vals.update(
                    {
                        "fennoa_binding_id": binding.id,
                        "fennoa_id": binding.external_id,
                    }
                )

            record.write(vals)

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
        for record in self:
            record.fennoa_import_record()
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

        payload = self.fennoa_export_mapper()
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
            result = self.api_update_customer(self.ref, payload)
            self.message_post(body=_("Updated partner data to Fennoa"))
        else:
            # Create new partner
            result = self.api_create_customer(payload, partner=self)
            self.message_post(body=_("Exported partner to Fennoa"))
        return result

    def fennoa_export_mapper(self) -> dict:
        """
        Map Odoo partner fields to Fennoa customer fields for export.
        :return: dict with mapped Fennoa customer fields
        """
        # TODO: use actual export mapper
        self.ensure_one()
        vals = {
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

        return vals

    def fennoa_import_record(self, fennoa_id=False):
        """
        Import customer data from Fennoa into Odoo as a partner.
        :param customer: dict with customer data from Fennoa API
        :return: Result message
        """
        Binding = self.env["fennoa.binding"]

        if fennoa_id:
            customer_data = self.api_get_customer_by_id(fennoa_id)
        elif self.ref:
            customer_data = self.api_get_customer_by_number(self.ref)
        else:
            raise ValidationError(
                _("Cannot import customer without Fennoa ID or customer number.")
            )

        existing_partner = None

        if not customer_data.get("id"):
            raise ValidationError(_("Invalid customer data from Fennoa: missing ID"))

        backend = (
            self.env["fennoa.backend"]
            .sudo()
            .get_backend(company=self.company_id or self.env.company)
        )

        if len(self) == 1:
            existing_partner = self
        else:
            # Try to find existing partner by customer number or exact name
            existing_partner = self.search(
                [
                    ("ref", "=", customer_data.get("customer_no") or ""),
                ],
            )
            if not existing_partner:
                existing_partner = self.search(
                    [
                        ("name", "=ilike", customer_data.get("name")),
                    ],
                )

            if len(existing_partner) > 1:
                # Multiple matches, cannot decide which one to use
                raise ValidationError(
                    _(
                        "Multiple partners found matching "
                        "Fennoa customer '%s' during import."
                    )
                    % customer_data.get("customer_no")
                )

        vals = self.fennoa_import_mapper(customer_data)

        if existing_partner:
            existing_partner.write(vals)
        else:
            existing_partner = self.create(vals)

        if not existing_partner.fennoa_binding_ids.filtered(
            lambda b: b.backend_id == backend
        ):
            binding_vals = {
                "backend_id": backend.id,
                "res_model": self._name,
                "external_id": fennoa_id,
                "res_id": existing_partner.id,
            }

            Binding.create(binding_vals)

        existing_partner.message_post(body=_("Updated partner data from Fennoa"))

        return (
            f"Imported Fennoa customer ID '{fennoa_id}' "
            f"into Odoo with ID '{existing_partner.id}'"
        )

    def fennoa_import_mapper(self, customer_data) -> dict:
        """
        Map customer data from Fennoa to Odoo partner fields.
        :param customer_data: dict with customer data from Fennoa API
        :return: dict with mapped Odoo partner fields
        """
        country_code = customer_data.get("country_id") or ""
        country = False
        if country_code:
            country = self.env["res.country"].search(
                [("code", "=", country_code)], limit=1
            )

        # TODO: use actual import mapper
        vals = {
            "name": customer_data.get("name") or "",
            "street": customer_data.get("address") or "",
            "zip": customer_data.get("postalcode") or "",
            "city": customer_data.get("city") or "",
            "country_id": country.id if country else False,
            "email": customer_data.get("email") or "",
            "phone": customer_data.get("phone") or "",
            "vat": customer_data.get("business_id") or "",
            "comment": customer_data.get("description") or "",
            "website": customer_data.get("website") or "",
            "ref": customer_data.get("customer_no") or "",
            "company_id": self.company_id.id,
        }

        return vals

    def api_create_customer(self, customer_data, partner=None):
        """Create a new customer in Fennoa using FORM DATA."""
        res = self._fennoa_api_request_make(
            "POST",
            "/customer_api/add",
            values=customer_data,
            related_model=partner._name if partner else None,
            related_id=partner.id if partner else None,
        )

        return res

    def api_update_customer(self, fennoa_id, payload):
        """Update existing customer in Fennoa using JSON."""
        endpoint = f"/customer_api/{fennoa_id}"
        res = self._fennoa_api_request_make(
            "PUT",
            endpoint,
            values=payload,
        )

        return res

    def api_get_customer_by_id(self, customer_id) -> dict:
        """Fetch customer details by Fennoa internal ID."""
        endpoint = f"/customer_api/{customer_id}"
        try:
            res = self._fennoa_api_request_make("GET", endpoint).get("Customer") or {}
        except ValidationError as e:
            _logger.warning(f"Customer with ID {customer_id} not found: %s", str(e))
            res = {}

        return res

    def api_get_customer_by_number(self, customer_no) -> dict:
        """Fetch customer by external customer number."""
        endpoint = f"/customer_api/get/customer_no/{customer_no}"
        try:
            res = self._fennoa_api_request_make("GET", endpoint).get("Customer") or {}
        except ValidationError as e:
            _logger.warning(f"Customer with number {customer_no} not found: %s", str(e))
            res = {}

        return res
