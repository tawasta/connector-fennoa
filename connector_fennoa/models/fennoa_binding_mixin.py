from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FennoaBindingMixin(models.AbstractModel):
    _name = "fennoa.binding.mixin"
    _description = "Mixin for Fennoa Binding"

    fennoa_binding_count = fields.Integer(
        string="Fennoa Logs",
        compute="_compute_fennoa_binding_count",
    )
    fennoa_binding_ids = fields.One2many(
        comodel_name="fennoa.binding",
        inverse_name="res_id",
        string="Fennoa Bindings",
        domain=lambda self: [("res_model", "=", self._name)],
    )
    fennoa_binding_id = fields.Many2one(
        comodel_name="fennoa.binding",
        string="Fennoa Binding",
        compute="_compute_fennoa_binding_id",
    )
    fennoa_export = fields.Boolean(
        string="Export to Fennoa",
        help="Disable this to prevent exporting to Fennoa",
        default=True,
    )
    fennoa_delayed_send = fields.Boolean(
        string="Fennoa delayed send",
        default=False,
        copy=False,
        help=(
            "When enabled, records are sent to Fennoa as background jobs "
            "using the Odoo queue (with_delay)."
        ),
    )
    fennoa_sent_date = fields.Datetime(
        string="Sent to Fennoa",
        readonly=True,
        copy=False,
        help="Timestamp when this record was successfully sent to Fennoa.",
    )

    def _compute_fennoa_binding_count(self):
        for record in self:
            record.fennoa_binding_count = len(record.fennoa_binding_ids)

    @api.depends("fennoa_binding_ids")
    def _compute_fennoa_binding_id(self):
        FennoaBinding = self.env["fennoa.binding"].sudo()
        for record in self:
            company = record.company_id or self.env.company
            binding = FennoaBinding.search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "=", record.id),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )

            record.fennoa_binding_id = binding

    def action_view_fennoa_bindings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Fennoa Bindings"),
            "res_model": "fennoa.binding",
            "view_mode": "tree,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {"default_res_model": self._name, "default_res_id": self.id},
        }

    def action_fennoa_export_record(self):
        """Export record to Fennoa"""
        if not hasattr(self, "_fennoa_export_record"):
            raise UserError(
                _("The model '%s' does not implement '_fennoa_export_record' method.")
                % self._name
            )

        for record in self:
            if not record.fennoa_export:
                raise UserError(_("Fennoa export not enabled for this record."))

            record._fennoa_export_record()
        return True

    def action_fennoa_import_record(self):
        """Update record from Fennoa."""
        if not hasattr(self, "_fennoa_import_record"):
            raise UserError(
                _("The model '%s' does not implement '_fennoa_import_record' method.")
                % self._name
            )

        for record in self:
            record._fennoa_import_record()
        return True
