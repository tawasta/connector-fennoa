import logging

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _name = "account.payment"
    _inherit = ["account.payment", "api.request.mixin", "fennoa.binding.mixin"]

    def _fennoa_import_record(self, values, company_id):
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

    def fennoa_export_mapper(self):
        """
        Map Odoo payment fields to Fennoa payment fields
        """
        if len(self.reconciled_invoice_ids) == 1:
            invoice_number = self.reconciled_invoice_ids.name or ""
        else:
            # TODO: this invoice number mapping is hacky and should be improved
            invoice_number = self.ref and self.ref.strip("/INV") or ""

        vals = {
            "invoice_no": invoice_number,
            "payment_date": self.date.strftime("%Y-%m-%d"),
            "sum": self.amount,
            # TODO: Map payment method
            "payment_type": 2,
            "is_factoring": 0,
            "description": self.ref or "",
        }
        return vals

    def _fennoa_export_record(self):
        """
        Export payment to Fennoa
        """
        self.ensure_one()

        if self.fennoa_binding_id:
            msg = _(
                "Payment '%s' has already been exported to Fennoa.",
                self.display_name,
            )
            return msg

        payload = self.fennoa_export_mapper()
        result = self.fennoa_api_create_payment(payload)
        self.fennoa_sent_date = fields.Datetime.now()
        self.message_post(body=_("Exported payment to Fennoa"))
        for invoice in self.reconciled_invoice_ids:
            invoice.message_post(
                body=_(_("Payment %s sent to Fennoa", self._get_html_link()))
            )
        return _("Payment exported to Fennoa with ID %s.") % result.get("id")

    def fennoa_api_create_payment(self, payload):
        """
        Create a new payment in Fennoa using
        """
        res = self._fennoa_api_request_make(
            "POST",
            "/sales_api/add/payment",
            values=payload,
            related_model=self._name if self else None,
            related_id=self.id if self else None,
        )

        return res
