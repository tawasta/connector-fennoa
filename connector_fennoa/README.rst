.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

================
Fennoa Connector
================
Odoo 17 connector for integrating with the Fennoa accounting platform.

This module synchronizes customer master data, exports sales invoices and
imports account receivable payments from Fennoa into Odoo.

All API requests and responses are logged into ``fennoa.binding`` records
for debugging and traceability.

Features
========

* Fennoa backend configuration per company
* Export customers on demand, and auto-create when sending invoices
* Export customer invoices to Fennoa (immediately or delayed queue job)
* Import Fennoa sales payments and automatically reconcile in Odoo
* Complete REST call logging with related model references
* Menu, search view and grouping for API bindings

Configuration
=============
1. Go to *Fennoa > Backends*
2. Create a backend for each company:

   * Base URL (default: https://app.fennoa.com/api)
   * API User (client identifier)
   * API Key (plain text or Base64)
   * Company

3. Press **Test Connection** to validate credentials.
4. (Optional) Run **Import Customers** to fetch customer master data.

A scheduled cron job will automatically import Fennoa payments every hour.

Usage
=====
**Invoice sending**

* When a customer invoice is posted and *Send to Fennoa* is enabled,
  the invoice is exported automatically.
* One-click **Post & Send to Fennoa** button is available.
* Manual export also available via *Actions > Send to Fennoa*.

**Payment import**

* Runs automatically via cron: *Fennoa Payment Sync*
* Reconciles invoices using Odoo’s payment creation logic

**Log access**

* On invoices and partners, a smart button **Fennoa Logs** opens related API logs
* Full log browser available: *Fennoa > Bindings*


Known issues / Roadmap
======================
\-

Credits
=======

Contributors
------------

* Valtteri Lattu <valtteri.lattu@tawasta.fi>

Maintainer
----------

.. image:: https://tawasta.fi/templates/tawastrap/images/logo.png
   :alt: Oy Tawasta OS Technologies Ltd.
   :target: https://tawasta.fi/

This module is maintained by Oy Tawasta OS Technologies Ltd.
