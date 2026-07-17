from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping


class FennoaPartnerImportMapper(Component):
    _name = "fennoa.partner.import.mapper"
    _description = "Fennoa Partner Import Mapper"
    _inherit = "base.import.mapper"
    _usage = "import.mapper"
    _apply_on = ["res.partner"]

    # region Mappings
    # Fennoa, Odoo
    direct = [
        ("name", "name"),
        ("postalcode", "zip"),
        ("city", "city"),
        ("email", "email"),
        ("phone", "phone"),
        ("business_id", "company_registry"),
        ("description", "comment"),
        ("website", "website"),
        ("customer_no", "ref"),
        ("einvoice_address", "edicode"),
    ]

    @mapping
    def country_id(self, record):
        res = {}
        country_code = record.get("country_id", "")
        if country_code:
            country = self.env["res.country"].search(
                [("code", "=", country_code)], limit=1
            )

            if country:
                res["country_id"] = country.id

        return res

    @mapping
    def address(self, record):
        address = record.get("address", "")
        # TODO: Fennoa only has one address field, but Odoo has street and street 2.
        # Address should be split into street and street2 when necessary
        if address:
            return {"street": address}

    @mapping
    def einvoice_operator(self, record):
        res = {}
        einvoice_operator = record.get("einvoice_operator_id")
        if einvoice_operator:
            operator = self.env["res.partner.operator.einvoice"].search(
                [("identifier", "ilike", einvoice_operator)], limit=1
            )
            if operator:
                res["einvoice_operator_id"] = operator.id

        return res
