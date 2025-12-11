Odoo 17 connector for integrating with the Fennoa accounting platform.

This module synchronizes customer master data, exports sales invoices (including
credit notes) and imports accounts receivable payments from Fennoa into Odoo.

All API requests and responses are logged into ``fennoa.binding`` records
for debugging and traceability.

Features
========

* Fennoa backend configuration per company
* Customer sync:
  
  * Import customers from Fennoa on demand
  * Auto-create customer in Fennoa when sending invoices if *Send to Fennoa* is enabled
  * Store Fennoa customer ID and customer number on partners

* Sales invoice export:

  * Export customer invoices and credit notes (``out_invoice`` and ``out_refund``)
  * Correct handling of credit notes: credit invoices are sent with negative total
  * Delivery method mapping from Odoo ``transmit_method_id`` to Fennoa
    (Finvoice / email / postal)
  * E-invoice address (``edicode``) and operator are sent when using Finvoice
  * E-mail delivery uses partner email address
  * Per-invoice flags for sending and delayed (queued) sending
  * Store Fennoa invoice ID and sent timestamp on the invoice

* Payment import:

  * Import Fennoa sales invoice payments via API
  * Create Odoo payments using the standard payment register wizard
  * Link payments to Fennoa payment and invoice IDs on ``account.payment``
  * Designed to run via a cron job (hourly sync)

* Logging and traceability:

  * All API calls stored in ``fennoa.binding`` with request/response payloads
  * Smart buttons on invoices and partners to open related Fennoa logs
  * Dedicated menu, tree, form and search views for bindings

* Queue job integration:

  * Uses ``queue_job`` channels for background processing
  * Separate Fennoa job channel for importing customers and exporting invoices