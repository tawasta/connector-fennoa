from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import changed_by, mapping


class FennoaPartnerExportMapper(Component):
    _name = "fennoa.partner.export.mapper"
    _description = "Fennoa Partner Export Mapper"
    _inherit = "fennoa.export.mapper"
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

    @changed_by("vat")
    @mapping
    def vat(self, record):
        return self._direct_mapping(record.vat, "vat_number")

    @changed_by("ref")
    @mapping
    def customer_no(self, record):
        # Check if there are multiple partners with the same reference
        if (
            record.ref
            and len(self.env["res.partner"].search([("ref", "=", record.ref)])) > 1
        ):
            raise UserError(
                _(
                    "Multiple partners found with the same reference "
                    "'%s'. Cannot determine the correct "
                    "Fennoa partner to update.",
                    record.ref,
                )
            )

        res = {}

        if record.ref:
            res["customer_no"] = record.ref

        return res

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

    @mapping
    @changed_by("lang")
    def locale(self, record):
        return {"locale_id": self._get_fennoa_locale_code(record)}

    @mapping
    @changed_by("edicode", "einvoice_operator_id")
    def einvoice_information(self, record):
        res = {}

        delivery_method = self._get_fennoa_delivery_method(record)

        if delivery_method == "email":
            # If delivery method is "email", it goes to einvoice_address
            if not record.email:
                raise UserError(
                    _("Email address is required when delivery method is 'email'.")
                )
            res["einvoice_address"] = record.email
            # res["einvoice_operator_id"] = ""
        elif delivery_method == "finvoice":
            edicode = record.edicode or record.commercial_partner_id.edicode
            einvoice_operator_id = (
                record.einvoice_operator_id
                or record.commercial_partner_id.einvoice_operator_id
            )

            if not edicode or not einvoice_operator_id:
                raise UserError(
                    _(
                        "Edicode and eInvoice operator are required "
                        "when delivery method is eInvoice."
                    )
                )
            res["einvoice_address"] = edicode
            res["einvoice_operator_id"] = einvoice_operator_id.identifier

        return res

    @mapping
    @changed_by("customer_invoice_transmit_method")
    def sales_invoice_delivery_method(self, record):
        res = {}
        delivery_method = self._get_fennoa_delivery_method(record)
        res["sales_invoice_delivery_method"] = delivery_method

        return res

    # endregion
