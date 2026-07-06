import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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
        fennoa_invoice = self.fennoa_api_get_invoice(fennoa_id)
        invoice_no = fennoa_invoice.get("invoice_no")

        if not invoice_no:
            raise RetryableJobError(
                _("Fennoa did not return an invoice number for invoice %s.", fennoa_id)
            )

        payment_reference = fennoa_invoice.get("banking_reference")

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

    def _fennoa_import_record(self, fennoa_id, invoice_type=None):
        """
        Import invoice from Fennoa
        """
        res = self.fennoa_api_get_invoice(fennoa_id, invoice_type)
        backend = self._get_fennoa_backend()

        invoice_number = res.get("invoice_number")
        fennoa_id = res.get("id")

        # Try to find an existing binding
        existing_binding = (
            self.env["fennoa.binding"]
            .sudo()
            .search(
                [
                    ("backend_id", "=", backend.id),
                    ("res_model", "=", self._name),
                    ("external_id", "=", fennoa_id),
                ],
            )
        )
        if existing_binding:
            return _(
                "Invoice with Fennoa ID '%(fennoa_id)s' "
                "already exists in Odoo with ID '%(odoo_id)s'"
            ) % {
                "fennoa_id": fennoa_id,
                "odoo_id": existing_binding.res_id,
            }

        # Try to find an existing invoice by invoice number
        existing_invoice = self.search([("name", "=", invoice_number)], limit=1)
        if existing_invoice:
            return _(
                "Invoice with number '%(invoice_number)s' "
                "already exists in Odoo with ID '%(odoo_id)s'"
            ) % {
                "invoice_number": invoice_number,
                "odoo_id": existing_invoice.id,
            }

        with backend.work_on(self._name) as work:
            mapper = work.component(usage="import.mapper")
            vals = mapper.map_record(res).values()

        invoice = self.create(vals)

        if not invoice.fennoa_binding_id:
            binding_vals = {
                "backend_id": backend.id,
                "res_model": self._name,
                "external_id": fennoa_id,
                "res_id": invoice.id,
            }

            self.env["fennoa.binding"].sudo().create(binding_vals)

        invoice.message_post(body=_("Imported data from Fennoa"))

        return (
            f"Imported Fennoa invoice '{fennoa_id}' "
            f"into Odoo with ID '{invoice.id}'"
        )

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

    def fennoa_api_get_invoice(self, fennoa_id, invoice_type=None):
        """
        Get invoice details from Fennoa by its ID.
        fennoa_id: The ID of the invoice in Fennoa.
        invoice_type: Optional, can be "sale" or "purchase"
        """
        if invoice_type not in (None, "sale", "purchase"):
            raise ValidationError(
                _(
                    "Invalid invoice_type '%s'. "
                    "Must be 'sale' or 'purchase' if provided."
                ),
                invoice_type,
            )

        if invoice_type == "sale" or self.is_sale_document():
            is_sale = True
            is_purchase = False
        elif invoice_type == "purchase" or self.is_purchase_document():
            is_sale = False
            is_purchase = True

        if is_sale:
            endpoint = f"/sales_api/{fennoa_id}"
        elif is_purchase:
            endpoint = f"/purchases_api/{fennoa_id}"
        else:
            raise ValidationError(
                _("Only sales and purchase invoices can be fetched from Fennoa.")
            )

        res = self._fennoa_api_request_make(
            "GET",
            endpoint,
            related_model=self._name,
            related_id=self.id,
        )

        if is_sale:
            return res.get("SalesInvoice", {})
        elif is_purchase:
            return res.get("PurchaseInvoice", {})

    # endregion
