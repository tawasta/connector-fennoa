from odoo.addons.component.core import Component


class FennoaInvoiceImportMapper(Component):
    _name = "fennoa.invoice.import.mapper"
    _description = "Fennoa Invoice Import Mapper"
    _inherit = "base.import.mapper"
    _usage = "import.mapper"
    _apply_on = ["account.move"]

    # region Mappings
    # Fennoa, Odoo
    direct = []
