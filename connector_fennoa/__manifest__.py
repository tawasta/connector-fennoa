##############################################################################
#
#    Author: Futural Oy
#    Copyright 2025 Futural Oy (https://futural.fi)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program. If not, see http://www.gnu.org/licenses/agpl.html
#
##############################################################################
{
    "name": "Fennoa Connector",
    "summary": "Integrate Odoo to Fennoa",
    "version": "17.0.1.2.9",
    "category": "Invoicing & Payments",
    "website": "https://github.com/tawasta/connector-fennoa",
    "author": "Futural",
    "license": "AGPL-3",
    "application": True,
    "installable": True,
    "images": ["static/description/banner.png"],
    "depends": [
        "account",
        "account_invoice_transmit_method",
        "api_request_handler",
        "connector",
        "l10n_fi_edicode",
    ],
    "data": [
        "security/ir_model_access.xml",
        "data/queue_job_channel.xml",
        "data/queue_job_function.xml",
        "data/cron.xml",
        "views/account_fiscal_position.xml",
        "views/account_move.xml",
        "views/account_payment.xml",
        "views/fennoa_backend_form.xml",
        "views/fennoa_backend_menu.xml",
        "views/fennoa_backend_tree.xml",
        "views/fennoa_binding_form.xml",
        "views/fennoa_binding_menu.xml",
        "views/fennoa_binding_search.xml",
        "views/fennoa_binding_tree.xml",
        "views/partner.xml",
    ],
}
