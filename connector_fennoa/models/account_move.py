import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

from odoo.addons.queue_job.delay import group

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "api.request.mixin", "fennoa.binding.mixin"]

    # region Fields

    # endregion

    # region Compute and helper methods
    @api.depends("date", "auto_post")
    def _compute_hide_post_button(self):
        # Hide "Confirm"-button if fennoa_export is enabled
        res = super()._compute_hide_post_button()
        for record in self.filtered("fennoa_export"):
            record.hide_post_button = record.fennoa_export

        return res

    def _get_fennoa_tax_class_id(self) -> int:
        """
        Get the Fennoa tax class ID for this invoice.
        """
        self.ensure_one()
        if not self.fiscal_position_id:
            raise ValidationError(
                _("Invoice '%s' has no fiscal position set.", self.display_name)
            )
        tax_class_id = self.fiscal_position_id.fennoa_tax_class_id

        if not tax_class_id:
            raise ValidationError(
                _(
                    "Fiscal position '%s' has no Fennoa tax class set. ",
                    self.fiscal_position_id.display_name,
                )
            )
        return int(tax_class_id)

    def _get_fennoa_invoice_type_id(self) -> int:
        """
        Get the Fennoa invoice type ID for this invoice.
        1 = Sales invoice
        2 = Credit note
        3 = Cash invoice
        """
        self.ensure_one()
        if self.move_type == "out_invoice":
            return 1
        elif self.move_type == "out_refund":
            return 2
        else:
            raise ValidationError(
                _(
                    "Unsupported move type '%s' for Fennoa invoice type.",
                    self.move_type,
                )
            )

    def _get_fennoa_locale_code(self) -> str:
        """
        Get the Fennoa locale code for this invoice based on the partner's language.
        Defaults to english
        """
        self.ensure_one()
        lang_code = self.partner_id.lang or "en_US"
        if lang_code == "fi_FI":
            return "fi"
        elif lang_code == "sv_SE":
            return "sv"
        else:
            return "en"

    def _get_fennoa_delivery_method(self) -> str:
        """
        Get the Fennoa delivery method for this invoice.
        Options: email, postal, finvoice (einvoice)
        Defaults to postal
        """
        self.ensure_one()
        delivery_method = "postal"

        if self.transmit_method_id and self.transmit_method_id.code:
            code = self.transmit_method_id.code.lower()
            if code == "einvoice":
                delivery_method = "finvoice"
            elif code in ["mail", "email"]:
                delivery_method = "email"
            elif code == "post":
                delivery_method = "postal"

        return delivery_method

    # endregion

    # region Mappers
    def fennoa_export_mapper(self) -> dict:
        """
        Map Odoo invoice values to Fennoa sales invoice payload.
        """
        self.ensure_one()
        # TODO: use exporter mapper
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

        einvoice_address = False
        einvoice_operator = False
        delivery_method = self._get_fennoa_delivery_method()

        if delivery_method == "finvoice":
            einvoice_address = partner.edicode or False
            einvoice_operator = (
                partner.einvoice_operator_id.name
                if partner.einvoice_operator_id
                else False
            )
        elif delivery_method == "email":
            einvoice_address = partner.email or False

        payload = {
            "customer_no": partner.ref or "",
            "account_type_id": 1 if partner.is_company else 2,
            "name": partner.name,
            # "name2": "" // Secondary name of the customer
            "address": partner.get_combined_street(),
            "postalcode": partner.zip or "",
            "city": partner.city or "",
            "country": partner.country_id.code or "",
            "phone": partner.phone or "",
            "sales_invoice_taxclass_id": self._get_fennoa_tax_class_id(),
            "email": partner.email or "",
            "invoice_type_id": self._get_fennoa_invoice_type_id(),
            "vat_number": partner.vat or "",
            "currency": self.currency_id.name or "EUR",
            "invoice_date": self.invoice_date.strftime("%Y-%m-%d"),
            "due_date": self.invoice_date_due.strftime("%Y-%m-%d"),
            # "shipping_date": "" // Shipping date of the invoice
            # Omitting payment reference will force Fennoa to calculate it
            # "banking_reference": self.payment_reference or "",
            "locale": self._get_fennoa_locale_code(),
            # "our_reference": self.invoice_user_id.name or "",
            "your_reference": self.ref or "",
            "contact_person": self.invoice_user_id.name or "",
            # "penal_interest": "" // TODO: inherit account_invoice_overdue_interest
            "notes_before": html2plaintext(self.narration) or "",
            "delivery_method": delivery_method,
            # TODO: internal notes
            # "notes_internal": self.description or "",
        }

        if einvoice_address:
            payload["einvoice_address"] = einvoice_address
        if einvoice_operator:
            payload["einvoice_operator"] = einvoice_operator

        # Add invoice lines: row[1][...], row[2][...] etc.
        i = 1
        # TODO: separate row mapper
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

            product_id = line.product_id

            if product_id and product_id.default_code:
                payload[f"row[{i}][product_no]"] = product_id.default_code
            payload[f"row[{i}][name]"] = product_id.name if product_id else ""
            payload[f"row[{i}][description]"] = line.name or ""
            payload[f"row[{i}][price]"] = str(price)
            payload[f"row[{i}][quantity]"] = str(qty)
            payload[f"row[{i}][unit]"] = (
                line.product_uom_id.name if line.product_uom_id else ""
            )
            payload[f"row[{i}][vatpercent]"] = str(vatpercent)

            payload[f"row[{i}][account_code]"] = line.account_id.code or ""
            payload[f"row[{i}][discount_percent]"] = line.discount or 0.0
            # TODO: dimension
            i += 1

        return payload

    # endregion

    # region Actions
    # TODO: This overwrites the mixin method, and could be handled better
    def action_fennoa_export_record(self):
        """
        Export (send) invoice(s) to Fennoa.

        - If there is a single invoice and fennoa_delayed_send = False:
          send synchronously in the current transaction.
        - Otherwise:
          schedule one background job per invoice using with_delay (queue_job).
        """
        sale_moves = self.filtered(lambda m: m.is_sale_document() and m.fennoa_export)
        if not sale_moves:
            return True

        if len(sale_moves) == 1 and not sale_moves.fennoa_delayed_send:
            # Direct send for a single invoice (no background job)
            sale_moves._fennoa_export_record()
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
                )._fennoa_export_record()

        return True

    def action_fennoa_approve_invoice(self):
        """Approve invoice(s) in Fennoa."""
        for record in self:
            record.fennoa_api_approve_sales_invoice()
            record.message_post(
                body=_("Invoice approved in Fennoa."),
                subtype_xmlid="mail.mt_note",
            )
        return True

    def action_fennoa_get_invoice_number(self):
        """
        Fetch and update the invoice number from Fennoa
        """
        for record in self:
            res = self.fennoa_api_get_sales_invoice(record.fennoa_id)
            sale_invoice = res.get("SalesInvoice", {})
            invoice_no = sale_invoice.get("invoice_no")

            if invoice_no and invoice_no != record.name:
                record.message_post(
                    body=_("Fetched invoice number '%s' from Fennoa." % invoice_no),
                    subtype_xmlid="mail.mt_note",
                )
                record.name = invoice_no  # Update the invoice number in Odoo

    # endregion

    # region Business logic
    def _post(self, soft=True):
        """
        After posting sale invoices, automatically send them to Fennoa
        according to fennoa_export / fennoa_delayed_send flags.
        """
        res = super()._post(soft)

        sale_invoices = res.filtered(lambda m: m.is_sale_document() and m.fennoa_export)
        sale_invoices.action_fennoa_export_record()

        return res

    def write(self, vals):
        res = super().write(vals)

        if vals.get("payment_id"):
            for record in self.filtered(lambda r: r.is_entry()):
                # Send the payment to Fennoa
                job_desc = (
                    "Fennoa: send payment for invoice %s to Fennoa",
                    record.display_name,
                )
                record.payment_id.with_delay(
                    description=job_desc
                )._fennoa_export_record()

        return res

    def _fennoa_export_record(self):
        """Send a single invoice to Fennoa (called directly or via with_delay)."""
        self.ensure_one()

        if self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(
                _("Only customer invoices and credit notes can be sent to Fennoa.")
            )

        if not self.partner_id:
            raise UserError(
                _("Invoice %s has no customer to send to Fennoa.") % self.display_name
            )

        # Ensure customer exists in Fennoa and is up to date
        self.partner_id.action_fennoa_export_record()

        payload = self.fennoa_export_mapper()

        self.fennoa_api_create_sales_invoice(payload)

        self.fennoa_sent_date = fields.Datetime.now()

        self.message_post(
            body=_("Invoice was sent to Fennoa"),
            subtype_xmlid="mail.mt_note",
        )

        delayables = []

        job_desc = f"Fennoa: approve invoice ID {self.id}"
        delayables.append(
            self.delayable(description=job_desc).action_fennoa_approve_invoice()
        )

        job_desc = f"Fennoa: fetch invoice number for invoice ID {self.id}"
        delayables.append(
            self.delayable(description=job_desc).action_fennoa_get_invoice_number()
        )

        # TODO: auto-send (add to connector config)
        # job_send_to_customer = self.delayable().action_fennoa_send_invoice()

        group(*delayables).delay()

    # endregion

    # region Fennoa API methods
    def fennoa_api_create_sales_invoice(self, payload):
        """Send a new sales invoice to Fennoa (FORM DATA)."""
        res = self._fennoa_api_request_make(
            "POST",
            "/sales_api/add",
            values=payload,
            related_model=self._name,
            related_id=self.id,
        )

        return res

    def fennoa_api_approve_sales_invoice(self):
        """Approve a sales invoice in Fennoa by its ID."""
        fennoa_id = self.fennoa_binding_id.external_id
        res = self._fennoa_api_request_make(
            "POST",
            f"/sales_api/do/approve/{fennoa_id}",
            related_model=self._name,
            related_id=self.id,
        )

        return res

    def fennoa_api_send_sales_invoice(self, fennoa_id):
        """Send a sales invoice in Fennoa by its ID."""
        res = self._fennoa_api_request_make(
            "POST",
            f"/sales_api/do/send/{fennoa_id}",
            related_model=self._name,
            related_id=self.id,
        )

        return res

    def fennoa_api_get_sales_invoice(self, fennoa_id):
        """Get sales invoice details from Fennoa by its ID."""
        res = self._fennoa_api_request_make(
            "GET",
            f"/sales_api/{fennoa_id}",
            related_model=self._name,
            related_id=self.id,
        )

        return res

    # endregion
