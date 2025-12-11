Customer sync
-------------

* On partners, the checkbox **Send to Fennoa** controls whether the partner
  should be created/updated in Fennoa.
* When an outgoing invoice is sent to Fennoa, the customer is ensured to exist
  in Fennoa first (created if necessary).
* Fennoa identifiers are stored on the partner:

  * ``fennoa_customer_id`` – internal Fennoa ID
  * ``fennoa_customer_no`` – external customer number

Invoice sending
---------------

* On customer invoices and credit notes, the **Fennoa** tab contains:

  * **Send to Fennoa** – controls whether the invoice is exported
  * **Fennoa delayed send** – if enabled, sending uses a background queue job
  * **Fennoa Invoice ID** – ID of the invoice in Fennoa
  * **Sent to Fennoa** – timestamp when the invoice was successfully sent

* When an invoice is posted and *Send to Fennoa* is enabled, the connector:

  * Ensures the customer exists in Fennoa
  * Builds a FORM-DATA payload for the Fennoa *sales_api/add* endpoint
  * Derives delivery method and e-invoice/email details from:

    * Partner ``edicode`` and e-invoice operator (Finvoice)
    * Partner email (email delivery)
    * Invoice ``transmit_method_id`` (einvoice / mail / post)

  * Sends the invoice immediately or via queue job depending on
    **Fennoa delayed send**

* A **Post & Send to Fennoa** button is available on the invoice form to
  post and export in a single action.

* Credit notes (``out_refund``) are exported as Fennoa credit invoices with
  negative line quantities and positive unit prices, so that the total sum
  is negative as required by the Fennoa API.

Payment import
--------------

* The cron job *Fennoa Payment Sync* calls the backend method
  ``action_sync_payments`` every hour.
* The connector fetches sales invoice payments from Fennoa for a given
  date range and:

  * Finds the corresponding Odoo invoice by ``fennoa_invoice_id``
  * Uses the standard *Payment Register* wizard to create payments
  * Links the created payments with Fennoa IDs via:

    * ``fennoa_payment_id`` – payment ID in Fennoa
    * ``fennoa_invoice_id`` – invoice ID in Fennoa

* These fields are visible on the payment form.

Log access
----------

* On invoices and partners, the **Fennoa Logs** smart button opens related
  ``fennoa.binding`` entries for the record.
* The full log browser is available via *Fennoa > Bindings*, providing:

  * List and form views of all API calls
  * Request payload and response bodies (with code widgets)
  * Search and group-by options (backend, method, model, status, etc.)