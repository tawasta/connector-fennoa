from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import changed_by, mapping


class FennoaPartnerExportMapper(Component):
    _name = "fennoa.partner.export.mapper"
    _description = "Fennoa Partner Export Mapper"
    _inherit = "base.export.mapper"
    _usage = "export.mapper"
    _apply_on = ["res.partner"]

    # region Mappings
    # Odoo, Fennoa
    direct = []

    @changed_by("name")
    @mapping
    def name(self, record):
        if not record.name:
            raise UserError(_("Can't export without a name."))

        return {"name": record.name}

    @changed_by("zip")
    @mapping
    def postalcode(self, record):
        return self._direct_mapping(record.zip, "postalcode")

    @changed_by("city")
    @mapping
    def city(self, record):
        return self._direct_mapping(record.city, "city")

    @changed_by("comment")
    @mapping
    def comment(self, record):
        return self._direct_mapping(record.comment, "description")

    @changed_by("email")
    @mapping
    def email(self, record):
        return self._direct_mapping(record.email, "email")

    @changed_by("phone")
    @mapping
    def phone(self, record):
        return self._direct_mapping(record.phone, "phone")

    @changed_by("website")
    @mapping
    def website(self, record):
        return self._direct_mapping(record.website, "website")

    @changed_by("company_registry")
    @mapping
    def company_registry(self, record):
        return self._direct_mapping(record.company_registry, "business_id")

    @changed_by("ref")
    @mapping
    def customer_no(self, record):
        if not record.ref:
            raise UserError(_("Can't export without a customer reference."))

        # Check if there are multiple partners with the same reference
        if len(self.env["res.partner"].search([("ref", "=", record.ref)])) > 1:
            raise UserError(
                _(
                    "Multiple partners found with the same reference "
                    "'%s'. Cannot determine the correct "
                    "Fennoa partner to update.",
                    record.ref,
                )
            )

        return {"customer_no": record.ref}

    @changed_by("street", "street2")
    @mapping
    def address(self, record):
        # Get billing address if one is set

        res = {"address": self._get_combined_street(record)}

        return res

    @changed_by("country_id")
    @mapping
    def country_id(self, record):
        if not record.country_id or not record.country_id.code:
            raise UserError(_("Can't export without a country (ISO code)."))

        return {"country_id": record.country_id.code}

    @changed_by("account_type_id")
    @mapping
    def account_type_id(self, record):
        return {"account_type_id": 1 if record.is_company else 2}

    # endregion

    # region Helpers
    def _direct_mapping(self, source, target) -> dict:
        """
        Helper for direct mappings to prevent code repetition
        :param source: value to be mapped if it exists
        :param target: target field in Fennoa
        :return: dict with target field and source value if source exists
        """
        res = {}
        if source:
            res[target] = source

        return res

    def _get_combined_street(self, record) -> str:
        """
        Get combined string for street and street2
        :param record: res.partner record
        :return: String with streets
        """
        record.ensure_one()
        if record.street and record.street2:
            street = f"{record.street} {record.street2}"
        else:
            street = record.street or ""

        return street

    # endregion
