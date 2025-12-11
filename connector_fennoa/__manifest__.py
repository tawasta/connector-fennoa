##############################################################################
#
#    Author: Tawasta
#    Copyright 2020 Oy Tawasta OS Technologies Ltd. (https://tawasta.fi)
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
    "summary": "Fennoa Connector",
    "version": "17.0.1.0.0",
    "category": "Website",
    "website": "https://gitlab.com/tawasta/odoo/connector-fennoa",
    "author": "Futural",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "connector",
        "account",
        "sale",
        "contacts",
        "queue_job",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/queue_channel.xml",
        "data/cron.xml",
        "views/fennoa_backend_views.xml",
        "views/fennoa_binding_views.xml",
        "views/move.xml",
        "views/partner.xml",
        "views/payment.xml",
    ],
}
