from odoo import _
from odoo.exceptions import ValidationError

from odoo.addons.component.core import AbstractComponent


class FennoaExportMapper(AbstractComponent):
    _name = "fennoa.export.mapper"
    _description = "Fennoa Export Mapper"
    _inherit = "base.export.mapper"
    _collection = "fennoa.backend"

    # region Helpers
    def _direct_mapping(self, source, target) -> dict:
        """
        Helper for direct mappings to prevent code repetition
        :param source: value to be mapped if it exists
        :param target: target field in Fennoa
        :return: dict with target field and source value if source exists
        """
        res = {}
        if source:
            res[target] = source

        return res

    def _get_combined_street(self, record) -> str:
        """
        Get combined string for street and street2
        :param record: res.partner record
        :return: String with streets
        """
        record.ensure_one()

        if not hasattr(record, "street") or not hasattr(record, "street2"):
            raise ValidationError(_("Record must have street and street2 fields"))

        if record.street and record.street2:
            street = f"{record.street} {record.street2}"
        else:
            street = record.street or ""

        return street

    def _get_fennoa_tax_class_id(self, record) -> int:
        """
        Get the Fennoa tax class ID for invoice/move
        """

        if record._name != "account.move":
            raise ValidationError(
                _("You need to call this method from an account.move record")
            )

        record.ensure_one()
        if not record.fiscal_position_id:
            raise ValidationError(
                _("Invoice '%s' has no fiscal position set.", record.display_name)
            )
        tax_class_id = record.fiscal_position_id.fennoa_tax_class_id

        if not tax_class_id:
            raise ValidationError(
                _(
                    "Fiscal position '%s' has no Fennoa tax class set. ",
                    record.fiscal_position_id.display_name,
                )
            )
        return int(tax_class_id)

    def _get_fennoa_invoice_type_id(self, record) -> int:
        """
        Get the Fennoa invoice type ID for invoice/move
        Options:
        1 = Sales invoice
        2 = Credit note
        3 = Cash invoice
        """
        record.ensure_one()

        if record._name != "account.move":
            raise ValidationError(
                _("You need to call this method from an account.move record")
            )

        if record.move_type == "out_invoice":
            return 1
        elif record.move_type == "out_refund":
            return 2
        else:
            raise ValidationError(
                _(
                    "Unsupported move type '%s' for Fennoa invoice type.",
                    record.move_type,
                )
            )

    def _get_fennoa_locale_code(self, record) -> str:
        """
        Get the Fennoa locale code for this invoice based on the partner's language.
        Defaults to english
        """
        record.ensure_one()

        if hasattr(record, "lang"):
            lang_code = record.lang
        elif hasattr(record, "partner_id"):
            lang_code = record.partner_id.lang
        else:
            lang_code = "en_US"

        if lang_code == "fi_FI":
            return "fi"
        elif lang_code == "sv_SE":
            return "sv"
        else:
            return "en"

    def _get_fennoa_delivery_method(self, record) -> str:
        """
        Get the Fennoa delivery method for this record.
        Options: email, postal, finvoice (einvoice)
        Defaults to postal
        """
        record.ensure_one()

        if hasattr(record, "transmit_method_id"):
            # Invoices, moves
            transmit_method = record.transmit_method_id
        elif hasattr(record, "customer_invoice_transmit_method_id"):
            # Customers
            transmit_method = record.customer_invoice_transmit_method_id
        else:
            raise ValidationError(
                _("Record must have a transmit method to determine delivery method.")
            )

        # Use post as default
        delivery_method = "postal"

        if transmit_method and transmit_method.code:
            code = transmit_method.code.lower()
            if code == "einvoice":
                delivery_method = "finvoice"
            elif code in ["mail", "email"]:
                delivery_method = "email"
            elif code == "post":
                delivery_method = "postal"

        return delivery_method

    # endregion
