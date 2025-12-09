import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def _fennoa_build_sales_invoice_payload(self):
        """Build FORM DATA payload for sending the sales invoice to Fennoa."""
        self.ensure_one()

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

        payload = {
            "customer_no": partner.fennoa_customer_no or "",
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
            "banking_reference": self.payment_reference or "",
            "our_reference": self.invoice_user_id.name or "",
            "your_reference": self.ref or "",
        }
        # TODO: Add additional fields based on full Fennoa documentation

        # Add invoice lines: row[1][...], row[2][...] etc.
        i = 1
        for line in self.invoice_line_ids:
            vatpercent = 0.0
            if line.tax_ids:
                # Only first VAT in list used (Fennoa only supports one per line)
                vatpercent = line.tax_ids[0].amount or 0.0

            payload[f"row[{i}][name]"] = (
                line.product_id.display_name if line.product_id else (line.name or "")
            )
            payload[f"row[{i}][description]"] = line.name or ""
            payload[f"row[{i}][price]"] = str(line.price_unit)
            payload[f"row[{i}][quantity]"] = str(line.quantity)
            payload[f"row[{i}][unit]"] = (
                line.product_uom_id.name if line.product_uom_id else ""
            )
            payload[f"row[{i}][vatpercent]"] = str(vatpercent)
            i += 1

        return payload

    @api.model_create_multi
    def create(self, vals_list):
        """Override create() to ensure customer exists in Fennoa and send invoice."""
        moves = super().create(vals_list)

        Partner = self.env["res.partner"]

        for move in moves:
            if move.move_type not in ("out_invoice", "out_refund"):
                continue
            if not move.partner_id:
                continue

            partner = move.partner_id

            Partner._fennoa_ensure_customer(partner)
            payload = move._fennoa_build_sales_invoice_payload()

            backend = self.env["fennoa.backend"].search(
                [("company_id", "=", move.company_id.id)],
                limit=1,
            )

            result = backend.api_create_sales_invoice(payload)
            _logger.info(
                "Fennoa sales invoice created for move %s: %s", move.id, result
            )

        return moves
