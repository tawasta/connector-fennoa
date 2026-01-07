from odoo import fields, models


class FennoaBinding(models.Model):
    _name = "fennoa.binding"
    _description = "Fennoa Binding Log"
    _inherit = "external.binding"
    _order = "id DESC"

    _sql_constraints = [
        (
            "unique_binding",
            "unique(backend_id, res_model, res_id)",
            "A Fennoa binding for this record already exists.",
        ),
    ]

    backend_id = fields.Many2one(
        comodel_name="fennoa.backend",
        string="Fennoa Backend",
        required=True,
        ondelete="restrict",
        readonly=True,
    )
    company_id = fields.Many2one(
        related="backend_id.company_id",
    )
    external_id = fields.Integer(
        "Fennoa ID",
        help="Fennoa record id",
        index=True,
        readonly=True,
    )
    res_model = fields.Char(string="Related Model", readonly=True)
    res_id = fields.Integer(
        string="Related Record ID",
        readonly=True,
        ondelete="cascade",
    )
