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
        ("address", "street"),
        ("postalcode", "zip"),
        ("city", "city"),
        ("email", "email"),
        ("phone", "phone"),
        ("business_id", "company_registry"),
        ("description", "comment"),
        ("website", "website"),
        ("customer_no", "ref"),
    ]

    @mapping
    def country_id(self, record):
        res = {}
        country_code = record.get("country_id") or ""
        if country_code:
            country = self.env["res.country"].search(
                [("code", "=", country_code)], limit=1
            )

            if country:
                res["country_id"] = country.id

        return res
