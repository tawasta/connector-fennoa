import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.queue_job.delay import chain
from odoo.addons.queue_job.exception import RetryableJobError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "api.request.mixin", "fennoa.binding.mixin"]

    # region Fields
    # TODO: use an existing field?
    order_identifier = fields.Char(
        help="Optional field for purchase order reference in Fennoa",
    )

    # endregion

    # region Compute and helper methods
    @api.depends("date", "auto_post")
    def _compute_hide_post_button(self):
        # Hide "Confirm"-button if fennoa_export is enabled
        res = super()._compute_hide_post_button()
        for record in self.filtered("fennoa_export"):
            record.hide_post_button = record.fennoa_export

        return res

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

                move.with_delay(description=job_desc)._fennoa_export_record()

        return True

    def action_fennoa_approve_invoice(self):
        """Approve invoice(s) in Fennoa."""
        self.ensure_one()
        self.fennoa_api_approve_sales_invoice()
        msg = _("Invoice approved in Fennoa.")
        self.message_post(
            body=msg,
            subtype_xmlid="mail.mt_note",
        )
        return msg

    def action_fennoa_send_invoice_to_customer(self):
        """Send invoice(s) from Fennoa to the customer."""
        self.ensure_one()
        self.fennoa_api_send_sales_invoice(self.fennoa_binding_id.external_id)
        msg = _("Invoice sent from Fennoa to the customer.")
        self.message_post(
            body=msg,
            subtype_xmlid="mail.mt_note",
        )
        return msg

    def action_fennoa_get_invoice_details(self):
        """
        Fetch and update the invoice details from Fennoa
        """
        self.ensure_one()
        fennoa_id = self.fennoa_binding_id.external_id
        res = self.fennoa_api_get_sales_invoice(fennoa_id)
        sale_invoice = res.get("SalesInvoice", {})
        # TODO: create import mapper to handle more fields
        invoice_no = sale_invoice.get("invoice_no")
        if not invoice_no:
            raise RetryableJobError(
                _("Fennoa did not return an invoice number for invoice %s.", fennoa_id)
            )

        payment_reference = sale_invoice.get("banking_reference")

        if invoice_no and invoice_no != self.name:
            self.name = invoice_no  # Update the invoice number in Odoo
            self.message_post(
                body=_("Fetched invoice number '%s' from Fennoa." % invoice_no),
                subtype_xmlid="mail.mt_note",
            )
        if payment_reference and payment_reference != self.payment_reference:
            self.payment_reference = (
                payment_reference
            )  # Update the payment reference in Odoo
            self.message_post(
                body=_(
                    "Fetched payment reference '%s' from Fennoa." % payment_reference
                ),
                subtype_xmlid="mail.mt_note",
            )

        return _("Fetched invoice details from Fennoa.")

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
                job_desc = _(
                    "Fennoa: send payment for invoice %s to Fennoa",
                    record.name,
                )
                record.payment_id.with_delay(
                    description=job_desc
                )._fennoa_export_record()

        return res

    def _fennoa_export_record(self):
        """Send a single invoice to Fennoa (called directly or via with_delay)."""
        self.ensure_one()

        if self.fennoa_binding_id:
            raise UserError(
                _(
                    "Invoice '%s' has already been exported to Fennoa.",
                    self.display_name,
                )
            )

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

        backend = self._get_fennoa_backend()
        with backend.work_on(self._name) as work:
            mapper = work.component(usage="export.mapper")
            payload = mapper.map_record(self).values()

        self.fennoa_api_create_sales_invoice(payload)

        vals = {
            "fennoa_sent_date": fields.Datetime.now(),
        }
        # Set temporary prefix for invoice to avoid confusion and conflicts,
        # if Odoo is not in sync with Fennoa sequence
        # Fennoa will provide the final invoice number after approval
        if self.name[0:3] != "INV":
            new_name = f"INV/{self.name}"
            i = 1
            while self.search([("name", "=", new_name)]):
                # If there is an overlapping name, add a sequence number
                new_name = new_name + f"_{i}"
                i += 1

            vals["name"] = new_name

        self.update(vals)

        self.message_post(
            body=_("Invoice was sent to Fennoa"),
            subtype_xmlid="mail.mt_note",
        )

        backend = self._get_fennoa_backend()
        delayables = []
        if backend.sale_invoice_auto_approve:
            job_desc = f"Fennoa: approve invoice ID {self.id}"
            delayables.append(
                self.delayable(description=job_desc).action_fennoa_approve_invoice()
            )

        job_desc = f"Fennoa: fetch invoice details for invoice ID {self.id}"
        delayables.append(
            self.delayable(description=job_desc).action_fennoa_get_invoice_details()
        )

        if backend.sale_invoice_auto_approve and backend.sale_invoice_auto_send:
            job_desc = f"Fennoa: send invoice ID {self.id} to customer"
            delayables.append(
                self.delayable(
                    description=job_desc
                ).action_fennoa_send_invoice_to_customer()
            )

        chain(*delayables).delay()

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
