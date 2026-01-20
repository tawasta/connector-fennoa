from odoo import fields, models


class FennoaBinding(models.Model):
    _name = "fennoa.binding"
    _description = "Fennoa Binding"
    _inherit = "external.binding"
    _order = "id DESC"

    _sql_constraints = [
        (
            "unique_binding",
            "unique(backend_id, res_model, res_id)",
            "A Fennoa binding for this record already exists.",
        ),
    ]

    name = fields.Char(
        compute="_compute_name",
    )

    backend_id = fields.Many2one(
        comodel_name="fennoa.backend",
        string="Fennoa Backend",
        required=True,
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
    )

    def _compute_name(self):
        for record in self:
            record.name = f"{record.res_model}.{record.res_id}: {record.external_id}"

    def action_open_record(self):
        """
        Open the related Odoo record.
        :return: Action dictionary
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
        }
