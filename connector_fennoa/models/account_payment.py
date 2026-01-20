import logging

from odoo import _, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _name = "account.payment"
    _inherit = ["account.payment", "api.request.mixin", "fennoa.binding.mixin"]

    def fennoa_import_record(self, values, company_id):
        """
        Import payment data from Fennoa into Odoo as a payment.
        :param values: Payment data from Fennoa API
        """
        Binding = self.env["fennoa.binding"]

        payment_data = values.get("SalesInvoicePayment") or {}
        invoice_data = values.get("SalesInvoice") or {}

        if not payment_data or not invoice_data:
            raise ValidationError(_("Invalid payment data received from Fennoa."))

        fennoa_payment_id = payment_data.get("id")
        fennoa_invoice_id = invoice_data.get("id")

        if not fennoa_payment_id or not fennoa_invoice_id:
            raise ValidationError(
                _("Payment or Invoice ID missing in Fennoa payment data.")
            )

        payment_binding = Binding.search(
            [
                ("external_id", "=", int(fennoa_payment_id)),
                ("res_model", "=", self._name),
                ("company_id", "=", company_id.id),
            ],
        )
        if payment_binding:
            return "Payment already imported."

        move_binding = Binding.search(
            [
                ("external_id", "=", int(fennoa_invoice_id)),
                ("res_model", "=", "account.move"),
                ("company_id", "=", company_id.id),
            ],
        )

        if move_binding:
            move = self.env["account.move"].browse(move_binding.res_id)
            if move.payment_state == "paid":
                return f"Related invoice '{move.name}' is already paid."
            elif move.payment_state == "reversed":
                return f"Related invoice '{move.name}' is already reconciled."

            ctx = {
                "active_model": "account.move",
                "active_ids": [move_binding.res_id],
            }

            wizard = (
                self.env["account.payment.register"]
                .with_context(**ctx)
                .create(
                    {
                        "partner_id": move.partner_id.id,
                        "payment_date": payment_data.get("date"),
                        "amount": float(payment_data.get("sum") or 0.0),
                        "communication": invoice_data.get("banking_reference") or "",
                        "company_id": company_id.id,
                        "payment_type": "inbound",
                    }
                )
            )

            odoo_payments = wizard._create_payments()

            # Create bindings for the imported payment
            for payment in odoo_payments:
                Binding.create(
                    {
                        "backend_id": move_binding.backend_id.id,
                        "res_model": self._name,
                        "res_id": payment.id,
                        "external_id": int(fennoa_payment_id),
                    }
                )

            msg = (
                f"Created Odoo payments {odoo_payments.ids} "
                f"from Fennoa payment {fennoa_payment_id}"
            )

            _logger.info(msg)
            return msg
        else:
            raise ValidationError(
                _(
                    "Related invoice with Fennoa ID %s not found in Odoo.",
                    fennoa_invoice_id,
                )
            )
