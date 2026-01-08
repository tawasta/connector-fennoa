import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    fennoa_binding_count = fields.Integer(
        string="Fennoa bindings",
        compute="_compute_fennoa_binding_count",
    )
    fennoa_binding_ids = fields.One2many(
        comodel_name="fennoa.binding",
        inverse_name="res_id",
        string="Fennoa Bindings",
        domain=[("res_model", "=", "account.move")],
    )
    fennoa_export = fields.Boolean(
        string="Export to Fennoa",
        help="Disable this to prevent exporting partner to Fennoa",
        default=True,
    )

    fennoa_delayed_send = fields.Boolean(
        string="Fennoa delayed send",
        default=False,
        copy=False,
        help=(
            "When enabled, invoices are sent to Fennoa as background jobs "
            "using the Odoo queue (with_delay)."
        ),
    )

    fennoa_sent = fields.Datetime(
        string="Sent to Fennoa",
        readonly=True,
        copy=False,
        help="Timestamp when this invoice was successfully sent to Fennoa.",
    )

    fennoa_invoice_id = fields.Integer(
        string="Fennoa Invoice ID",
        readonly=True,
        help="ID of the invoice in Fennoa.",
        index=True,
    )

    def _compute_fennoa_binding_count(self):
        for record in self:
            record.fennoa_binding_count = len(self.fennoa_binding_ids)

    @api.depends("date", "auto_post")
    def _compute_hide_post_button(self):
        # Hide "Confirm"-button if fennoa_export is enabled
        res = super()._compute_hide_post_button()
        for record in self.filtered("fennoa_export"):
            record.hide_post_button = record.fennoa_export

        return res

    def action_view_fennoa_bindings(self):
        """Open Fennoa bindings related to this record."""
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
        for record in self:
            record.fennoa_export_record()
        return True

    def action_fennoa_import_record(self):
        """Update record from Fennoa."""
        _logger.error("Importing record from Fennoa not implemented!")
        return True

    def _fennoa_build_sales_invoice_payload(self):
        """Build FORM DATA payload for sending the sales invoice to Fennoa."""
        self.ensure_one()
        # TODO: use exporter
        # TODO: separate method for validation
        partner = self.partner_id
        if not partner:
            raise UserError(_("Cannot send invoice to Fennoa without a customer."))

        if not partner.country_id or not partner.country_id.code:
            raise UserError(
                _("Customer must have a country (ISO code) to send invoice to Fennoa.")
            )

        if not self.invoice_date or not self.invoice_date_due:
            raise UserError(
                _("Invoice date and due date must be set before sending to Fennoa.")
            )

        delivery_method = "postal"
        einvoice_address = False
        einvoice_operator = False

        if self.transmit_method_id and self.transmit_method_id.code:
            code = self.transmit_method_id.code.lower()
            if code == "einvoice":
                delivery_method = "finvoice"
                einvoice_address = partner.edicode or False
                einvoice_operator = (
                    partner.einvoice_operator_id.name
                    if partner.einvoice_operator_id
                    else False
                )
            elif code == "mail":
                delivery_method = "email"
                einvoice_address = partner.email or False
                einvoice_operator = False
            elif code == "post":
                delivery_method = "postal"

        payload = {
            "customer_no": partner.ref or "",
            "account_type_id": 1 if partner.is_company else 2,
            "name": partner.name,
            "address": partner.street or "",
            "postalcode": partner.zip or "",
            "city": partner.city or "",
            "country": partner.country_id.code or "",
            "phone": partner.phone or "",
            "email": partner.email or "",
            "invoice_type_id": 1 if self.move_type == "out_invoice" else 2,
            "vat_number": partner.vat or "",
            "currency": self.currency_id.name or "EUR",
            "invoice_date": self.invoice_date.strftime("%Y-%m-%d"),
            "due_date": self.invoice_date_due.strftime("%Y-%m-%d"),
            "our_reference": self.invoice_user_id.name or "",
            "your_reference": self.ref or "",
            "delivery_method": delivery_method,
        }

        if einvoice_address:
            payload["einvoice_address"] = einvoice_address
        if einvoice_operator:
            payload["einvoice_operator"] = einvoice_operator
        if self.payment_reference:
            payload["banking_reference"] = self.payment_reference

        # TODO: Add additional fields based on full Fennoa documentation.

        # Add invoice lines: row[1][...], row[2][...] etc.
        i = 1
        for line in self.invoice_line_ids:
            vatpercent = 0.0
            if len(line.tax_ids) > 1:
                raise ValidationError(
                    _(
                        "Invoice line %s has multiple taxes. "
                        "Fennoa only supports one tax per invoice line."
                    )
                    % line.display_name
                )
            if line.tax_ids:
                # Only first VAT in list used (Fennoa only supports one per line)
                vatpercent = line.tax_ids[0].amount or 0.0

            # For credit notes (out_refund),
            # Fennoa expects the total sum to be negative.
            qty = line.quantity or 0.0
            price = line.price_unit or 0.0
            if self.move_type == "out_refund":
                # Recommended: negative quantity with positive unit price.
                qty = -abs(qty)
                price = abs(price)

            payload[f"row[{i}][name]"] = (
                line.product_id.display_name if line.product_id else (line.name or "")
            )
            payload[f"row[{i}][description]"] = line.name or ""
            payload[f"row[{i}][price]"] = str(price)
            payload[f"row[{i}][quantity]"] = str(qty)
            payload[f"row[{i}][unit]"] = (
                line.product_uom_id.name if line.product_uom_id else ""
            )
            payload[f"row[{i}][vatpercent]"] = str(vatpercent)
            i += 1

        return payload

    def fennoa_export_record(self):
        """Send a single invoice to Fennoa (called directly or via with_delay)."""
        self.ensure_one()

        if not self.fennoa_export:
            raise UserError(_("Fennoa export not enabled for this invoice."))

        if self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(
                _("Only customer invoices and credit notes can be sent to Fennoa.")
            )

        if not self.partner_id:
            raise UserError(
                _("Invoice %s has no customer to send to Fennoa.") % self.display_name
            )

        # Ensure customer exists in Fennoa and is up to date
        self.partner_id.fennoa_export_record()

        backend = self.env["fennoa.backend"].search(
            [("company_id", "=", self.company_id.id)],
            limit=1,
        )
        if not backend:
            raise UserError(
                _("No Fennoa backend configured for company %s.")
                % (self.company_id.display_name,)
            )

        payload = self._fennoa_build_sales_invoice_payload()

        backend.api_create_sales_invoice(payload, move=self)

        self.write(
            {
                "fennoa_sent": fields.Datetime.now(),
            }
        )

        # TODO: fetch and save Fennoa invoice number?

        self.message_post(
            body=_("Invoice was sent to Fennoa"),
            subtype_xmlid="mail.mt_note",
        )

        # TODO: auto-approve (add to connector config)
        # TODO: auto-send (add to connector config)

    def action_fennoa_export_invoice(self):
        """
        Export (send) invoice(s) to Fennoa.

        - If there is a single invoice and fennoa_delayed_send = False:
          send synchronously in the current transaction.
        - Otherwise:
          schedule one background job per invoice using with_delay (queue_job).
        """
        sale_moves = self.filtered(
            lambda m: m.move_type in ("out_invoice", "out_refund") and m.fennoa_export
        )
        if not sale_moves:
            return True

        for move in sale_moves:
            if not move.partner_id:
                raise UserError(
                    _("Invoice %s has no customer to send to Fennoa.")
                    % move.display_name
                )

        if len(sale_moves) == 1 and not sale_moves.fennoa_delayed_send:
            # Direct send for a single invoice (no background job)
            sale_moves.fennoa_export_record()
        else:
            # Schedule one background job per invoice (queue_job / with_delay)
            for move in sale_moves:
                job_desc = _("Fennoa: send invoice %(name)s [Odoo ID: %(id)s]") % {
                    "name": move.name or move.display_name,
                    "id": move.id,
                }

                move.with_delay(
                    description=job_desc,
                    priority=10,
                    max_retries=5,
                ).fennoa_export_record()
                move.message_post(body=job_desc, subtype_xmlid="mail.mt_note")

        return True

    def _post(self, soft=True):
        """
        After posting sale invoices, automatically send them to Fennoa
        according to fennoa_export / fennoa_delayed_send flags.
        """
        res = super()._post(soft)

        sale_invoices = res.filtered(lambda m: m.is_sale_document() and m.fennoa_export)
        if sale_invoices:
            sale_invoices.action_fennoa_export_invoice()

        return res
