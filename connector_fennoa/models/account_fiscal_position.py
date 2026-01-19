from odoo import fields, models


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    fennoa_tax_class_id = fields.Selection(
        selection=[
            ("1", "Domestic sales (S) Default"),
            ("2", "EU-sales services (K)"),
            ("3", "EU-sales goods (K)"),
            ("4", "Construction services (AE)"),
            ("5", "Scrap metal sales (AE)"),
            ("6", "Foreign sales, outside of EU (G)"),
            ("7", "Domestic sales VAT-free (Z)"),
            ("8", "Triangulation (K)"),
            ("9", "Domestic sales, VAT-free, No VAT-liability (O)"),
        ],
        string="Fennoa Tax Class",
    )
