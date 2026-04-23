from odoo import _
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import changed_by, mapping


class FennoaInvoiceExportMapper(Component):
    _name = "fennoa.invoice.export.mapper"
    _description = "Fennoa Invoice Export Mapper"
    _inherit = "fennoa.export.mapper"
    _usage = "export.mapper"
    _apply_on = ["account.move"]

    # region Mappings
    # Odoo, Fennoa
    direct = []

    @changed_by("partner_id")
    @mapping
    def partner_id(self, record):
        partner = record.partner_id
        if not partner:
            raise ValidationError(
                _("Cannot send invoice to Fennoa without a customer.")
            )

        if not partner.country_id or not partner.country_id.code:
            raise ValidationError(
                _("Customer must have a country (ISO code) to send invoice to Fennoa.")
            )

        # Use partner mapper for partner values
        vals = partner.fennoa_get_export_payload()

        # Partner has "country_id", move has "country"
        vals["country"] = vals.pop("country_id")

        # Partner has "locale_id", move has "locale"
        vals["locale"] = vals.pop("locale_id")

        # Partner has "einvoice_operator_id", move has "einvoice_operator"
        if "einvoice_operator_id" in vals:
            vals["einvoice_operator"] = vals.pop("einvoice_operator_id")

        return vals

    @changed_by("partner_shipping_id")
    @mapping
    def partner_shipping_id(self, record):
        res = {}
        if (
            record.partner_shipping_id
            and record.partner_shipping_id != record.partner_id
        ):
            partner = record.partner_shipping_id
            # Use partner mapper for shipping partner values
            partner_vals = partner.fennoa_get_export_payload()

            res["shipping_name"] = partner_vals.get("name", "")
            # payload["shipping_name2"] = // Secondary name of the shipping address
            res["shipping_address"] = partner_vals.get("address", "")
            res["shipping_postalcode"] = partner_vals.get("postalcode", "")
            res["shipping_city"] = partner_vals.get("city", "")
            res["shipping_country"] = partner_vals.get("country_id", "")

        return res

    @mapping
    @changed_by("invoice_date", "invoice_date_due")
    def invoice_dates(self, record):
        if not record.invoice_date or not record.invoice_date_due:
            raise ValidationError(
                _("Invoice date and due date must be set before sending to Fennoa.")
            )

        return {
            "invoice_date": record.invoice_date.strftime("%Y-%m-%d"),
            "due_date": record.invoice_date_due.strftime("%Y-%m-%d"),
        }

    @mapping
    @changed_by("einvoice_operator_id", "edicode", "email")
    def delivery_method(self, record):
        delivery_method = self._get_fennoa_delivery_method(record)
        return {"delivery_method": delivery_method}

    @mapping
    @changed_by("move_type")
    def invoice_type(self, record):
        invoice_type_id = self._get_fennoa_invoice_type_id(record)
        return {"invoice_type_id": invoice_type_id}

    @mapping
    @changed_by("fiscal_position_id")
    def tax_class_id(self, record):
        tax_class_id = self._get_fennoa_tax_class_id(record)
        return {"sales_invoice_taxclass_id": tax_class_id}

    @mapping
    @changed_by("currency_id")
    def currency_id(self, record):
        return {"currency": record.currency_id.name or "EUR"}

    @mapping
    @changed_by("narration")
    def notes_before(self, record):
        return {
            "notes_before": html2plaintext(record.narration) if record.narration else ""
        }

    @mapping
    @changed_by("delivery_date")
    def shipping_date(self, record):
        res = {}
        if record.delivery_date:
            res["shipping_date"] = record.delivery_date.strftime("%Y-%m-%d")

        return res

    @mapping
    @changed_by("payment_reference")
    def payment_reference(self, record):
        res = {}
        if record.payment_reference:
            # TODO
            # Omitting payment reference will force Fennoa to calculate it
            # res["banking_reference"] = record.payment_reference
            pass

        return res

    @mapping
    @changed_by("invoice_user_id")
    def our_reference(self, record):
        res = {}
        if record.invoice_user_id:
            # TODO
            # "Our reference" should be salesperson, but this should be behind a setting
            # res["our_reference"] = record.invoice_user_id.name
            pass

        return res

    @mapping
    @changed_by("ref")
    def your_reference(self, record):
        res = {}
        if record.ref:
            res["your_reference"] = record.ref

        return res

    @mapping
    @changed_by("name")
    def order_identifier(self, record):
        res = {}
        if record.name:
            res["order_identifier"] = record.name

        return res

    @mapping
    def contact_person(self, record):
        res = {}

        # TODO: The contact person should be THEIR contact person, "tilaaja"
        # res["contact_person"] = record.partner_contact_id.name

        return res

    @mapping
    @changed_by("overdue_interest")
    def penal_interest(self, record):
        res = {}
        if hasattr(record, "overdue_interest") and record.overdue_interest:
            res["penal_interest"] = record.overdue_interest

        return res

    @mapping
    @changed_by("description")
    def notes_internal(self, record):
        res = {}
        if hasattr(record, "description") and record.description:
            res["notes_internal"] = record.description

        return res

    @mapping
    def rows(self, record):
        # TODO: Use line submapper
        res = {}
        lines = record.invoice_line_ids
        i = 1
        for line in lines:
            # Add invoice lines: row[1][...], row[2][...] etc.
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

            qty = line.quantity or 0.0
            price = line.price_unit or 0.0
            if record.move_type == "out_refund":
                # For credit notes we want to use negative total sum
                # (negative quantity with positive unit price)
                qty = -abs(qty)
                price = abs(price)

            product_id = line.product_id.with_context(
                lang=record.partner_id.lang or self.env.user.lang
            )

            if product_id and product_id.default_code:
                res[f"row[{i}][product_no]"] = product_id.default_code

            res[f"row[{i}][name]"] = product_id.name if product_id else ""
            res[f"row[{i}][description]"] = (
                "" if (line.name or "").strip() == "-" else (line.name or "")
            )
            res[f"row[{i}][price]"] = str(price)
            res[f"row[{i}][quantity]"] = str(qty)
            res[f"row[{i}][unit]"] = (
                line.product_uom_id.name if line.product_uom_id else ""
            )
            res[f"row[{i}][vatpercent]"] = str(vatpercent)

            res[f"row[{i}][account_code]"] = line.account_id.code or ""
            res[f"row[{i}][discount_percent]"] = line.discount or 0.0
            # TODO: dimension
            i += 1

        return res

    # endregion
