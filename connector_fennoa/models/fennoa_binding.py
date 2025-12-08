from odoo import fields, models


class FennoaBinding(models.Model):
    _name = "fennoa.binding"
    _description = "Fennoa Binding Log"
    _inherit = "external.binding"
    _order = "id DESC"

    backend_id = fields.Many2one("fennoa.backend", required=True)
    method = fields.Char()
    endpoint = fields.Char()
    payload = fields.Text()
    response = fields.Text()
    status_code = fields.Integer()
    successful = fields.Boolean()
