from odoo.addons.component.core import Component


class FennoaPaymentImportMapper(Component):
    _name = "fennoa.payment.import.mapper"
    _description = "Fennoa Payment Import Mapper"
    _inherit = "base.import.mapper"
    _usage = "import.mapper"
    _apply_on = ["account.payment"]

    # region Mappings
    # Fennoa, Odoo
    direct = []
