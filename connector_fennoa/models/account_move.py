from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)

        Partner = self.env["res.partner"]

        for move in moves:
            if move.move_type not in ("out_invoice", "out_refund"):
                continue
            if not move.partner_id:
                continue

            partner = move.partner_id

            Partner._fennoa_ensure_customer(partner)

        return moves
