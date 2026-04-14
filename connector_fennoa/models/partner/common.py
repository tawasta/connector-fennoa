import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _name = "res.partner"
    _inherit = ["res.partner", "api.request.mixin", "fennoa.binding.mixin"]

    @api.model
    def _fennoa_export_record(self):
        """
        Export or update Partner to Fennoa as a Customer.
        :return: Response from Fennoa API
        """
        self.ensure_one()

        if not self.fennoa_export:
            return _("Exporting to Fennoa is disabled for this partner.")

        backend = (
            self.env["fennoa.backend"]
            .sudo()
            .get_backend(company=self.company_id or self.env.company)
        )

        with backend.work_on(self._name) as work:
            mapper = work.component(usage="export.mapper")
            payload = mapper.map_record(self).values()

        binding = self.fennoa_binding_id
        if not binding and self.ref:
            # Try to find existing partner from Fennoa and create a binding
            fennoa_customer = self.fennoa_api_get_customer_by_number(self.ref)
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
            result = self.fennoa_api_update_customer(self.ref, payload)
            self.message_post(body=_("Updated partner data to Fennoa"))
        else:
            # Create new partner
            result = self.fennoa_api_create_customer(payload, partner=self)
            self.fennoa_sent_date = fields.Datetime.now()
            self.message_post(body=_("Exported partner to Fennoa"))
        return result

    def _fennoa_import_record(self, fennoa_id=False):
        """
        Import customer data from Fennoa into Odoo as a partner.
        :param fennoa_id: Fennoa customer ID to import
        :return: Result message
        """
        Binding = self.env["fennoa.binding"].sudo()

        if fennoa_id:
            customer_data = self.fennoa_api_get_customer_by_id(fennoa_id)
        elif self.ref:
            customer_data = self.fennoa_api_get_customer_by_number(self.ref)
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

        with backend.work_on(self._name) as work:
            mapper = work.component(usage="import.mapper")
            vals = mapper.map_record(customer_data).values()

        if existing_partner:
            existing_partner.write(vals)
        else:
            existing_partner = self.create(vals)

        if not existing_partner.fennoa_binding_id:
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

    def fennoa_api_create_customer(self, customer_data, partner=None):
        """
        Create a new customer to Fennoa
        """
        res = self._fennoa_api_request_make(
            "POST",
            "/customer_api/add",
            values=customer_data,
            related_model=partner._name if partner else None,
            related_id=partner.id if partner else None,
        )

        return res

    def fennoa_api_update_customer(self, customer_no, payload):
        """
        Update existing customer in Fennoa
        """
        if not customer_no:
            raise ValidationError(_("Customer number is required for partner."))

        if len(self.env["res.partner"].search([("ref", "=", customer_no)])) > 1:
            raise UserError(
                _(
                    "Multiple partners found with the same reference "
                    "'%s'. Cannot determine the correct "
                    "Fennoa customer to update.",
                    customer_no,
                )
            )

        endpoint = f"/customer_api/{customer_no}"
        res = self._fennoa_api_request_make(
            "PUT",
            endpoint,
            values=payload,
        )

        return res

    def fennoa_api_get_customer_by_id(self, customer_id) -> dict:
        """
        Fetch customer details by Fennoa internal ID.
         :param customer_id: Fennoa internal ID
         :return: Customer data as dict
        """
        endpoint = f"/customer_api/{customer_id}"
        try:
            res = self._fennoa_api_request_make("GET", endpoint).get("Customer") or {}
        except ValidationError as e:
            _logger.warning(f"Customer with ID {customer_id} not found: %s", str(e))
            res = {}

        return res

    def fennoa_api_get_customer_by_number(self, customer_no) -> dict:
        """
        Fetch customer by external customer number.
         :param customer_no: External customer number
         :return: Customer data as dict
        """
        endpoint = f"/customer_api/get/customer_no/{customer_no}"
        try:
            res = self._fennoa_api_request_make("GET", endpoint).get("Customer") or {}
        except ValidationError as e:
            _logger.warning(f"Customer with number {customer_no} not found: %s", str(e))
            res = {}

        return res
