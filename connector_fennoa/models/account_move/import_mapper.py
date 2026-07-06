from odoo import _
from odoo.exceptions import ValidationError

from odoo.addons.component.core import Component
from odoo.addons.connector.components.mapper import mapping


class FennoaInvoiceImportMapper(Component):
    _name = "fennoa.invoice.import.mapper"
    _description = "Fennoa Invoice Import Mapper"
    _inherit = "base.import.mapper"
    _usage = "import.mapper"
    _apply_on = ["account.move"]

    # region Mappings
    # Fennoa, Odoo
    direct = [
        ("invoice_number", "name"),
        ("invoice_date", "invoice_date"),
        ("due_date", "invoice_date_due"),
        ("entry_date", "date"),
        # TODO
        # ("our_reference", ""),
        ("your_reference", "ref"),
        ("order_identifier", "order_identifier"),
        ("order_number", "invoice_origin"),
        # TODO
        # ("purchase_order_id", ""),
    ]

    @mapping
    def move_type(self, record):
        if (
            record.get("PurchaseInvoiceType")
            and record.get("PurchaseInvoiceType").get("name") == "Debit invoice"
        ):
            return {"move_type": "in_invoice"}
        else:
            raise ValidationError(
                _("Cannot determine invoice type for Fennoa invoice '%s'")
                % record.get("invoice_number")
            )

    @mapping
    def partner(self, record):
        ResPartner = self.env["res.partner"]
        name = record.get("name") or record.get("supplier_name")
        company_registry = record.get("supplier_business_id")
        vat = record.get("vat_number") or record.get("supplier_vat_number")

        # Try to find existing partner by company_registry or vat
        existing_partner = ResPartner.search(
            [
                "|",
                "|",
                ("name", "=", name),
                "&",
                ("company_registry", "=", company_registry),
                ("company_registry", "!=", False),
                "&",
                ("vat", "=", vat),
                ("vat", "!=", False),
            ],
        )

        if not existing_partner or len(existing_partner) != 1:
            # Create a new partner
            existing_partner = ResPartner.create(
                {
                    "name": name,
                    "company_registry": company_registry,
                    "vat": vat,
                }
            )

        return {"partner_id": existing_partner.id}

    @mapping
    def bank_account(self, record):
        bank_account_number = record.get("bank_account")

        if not bank_account_number:
            return {}

        BankAccount = self.env["res.partner.bank"]

        existing_account = BankAccount.search(
            [("acc_number", "=", bank_account_number)], limit=1
        )

        if not existing_account:
            # Create a new bank account
            account_vals = {
                "acc_number": bank_account_number,
                "partner_id": self.partner(record).get("partner_id"),
            }

            if record.get("bank_bic"):
                bank = self.env["res.bank"].search(
                    [("bic", "=", record.get("bank_bic"))], limit=1
                )
                if bank:
                    account_vals["bank_id"] = bank.id

            existing_account = BankAccount.create(account_vals)

        return {"partner_bank_id": existing_account.id}

    @mapping
    def payment_reference(self, record):
        payment_reference = record.get("bank_reference") or record.get("bank_message")

        if payment_reference:
            return {"payment_reference": payment_reference}

    @mapping
    def currency_id(self, record):
        currency = record.get("Currency")
        currency_code = currency.get("code") if currency else None
        currency_name = currency.get("name") if currency else None

        currency_id = self.env["res.currency"].search(
            ["|", ("name", "=", currency_code), ("full_name", "=", currency_name)],
            limit=1,
        )

        return {"currency_id": currency_id.id if currency_id else None}

    @mapping
    def invoice_rows(self, record):
        # TODO: Invoice row mapping
        # invoice_rows = record.get("InvoiceRows")
        # or record.get("PurchaseInvoiceRows") or []

        total_gross = record.get("total_gross")
        total_net = record.get("total_net")

        # TODO: Get the correct default account
        account_id = (
            self.env["account.account"].search([("code", "=", "4000")], limit=1).id
        )

        # TODO: Get correct taxes
        tax_ids = []

        if total_gross > total_net:
            # Search for correct tax
            pass
        else:
            # 0% tax
            pass

        invoice_rows = [
            (
                0,
                0,
                {
                    "name": "-",
                    "quantity": 1,
                    "price_unit": total_net,
                    "tax_ids": tax_ids,
                    "account_id": account_id,
                },
            )
        ]

        return {"line_ids": invoice_rows}
