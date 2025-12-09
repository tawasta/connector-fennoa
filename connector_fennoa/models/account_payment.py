from odoo import _, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    fennoa_payment_id = fields.Integer(
        string="Fennoa Payment ID",
        readonly=True,
        help="ID of the payment in Fennoa.",
        index=True,
    )

    fennoa_invoice_id = fields.Integer(
        string="Fennoa Invoice ID",
        readonly=True,
        help="ID of the invoice in Fennoa linked to this payment.",
        index=True,
    )
