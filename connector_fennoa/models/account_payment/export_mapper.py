from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import changed_by, mapping


class FennoaPaymentExportMapper(Component):
    _name = "fennoa.payment.export.mapper"
    _description = "Fennoa Payment Export Mapper"
    _inherit = "fennoa.export.mapper"
    _usage = "export.mapper"
    _apply_on = ["account.payment"]

    # region Mappings
    # Odoo, Fennoa
    direct = [
        ("amount", "sum"),
    ]

    @mapping
    @changed_by("ref")
    def invoice_no(self, record):
        if len(record.reconciled_invoice_ids) == 1:
            invoice_number = record.reconciled_invoice_ids.name or ""
        else:
            # TODO: this invoice number mapping is hacky and should be improved
            invoice_number = record.ref and record.ref.strip("/INV") or ""

        return {"invoice_no": invoice_number}

    @mapping
    @changed_by("date")
    def payment_date(self, record):
        return {"payment_date": record.date.strftime("%Y-%m-%d")}

    @mapping
    @changed_by("payment_type")
    def payment_type(self, record):
        # TODO: Map payment method
        return {"payment_type": 2}

    @mapping
    @changed_by("is_factoring")
    def is_factoring(self, record):
        # TODO: Map factoring status
        return {"is_factoring": 0}

    @mapping
    @changed_by("description")
    def description(self, record):
        # TODO: Map description
        return {"description": record.ref or ""}

    # endregion
