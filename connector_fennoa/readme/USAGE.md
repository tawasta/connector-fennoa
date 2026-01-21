Customers
---------

* Partners can be imported / updated from Fennoa to Odoo
* On partners, the checkbox **Send to Fennoa** controls whether the partner should be created/updated in Fennoa.
* When an outgoing invoice is sent to Fennoa, the customer is exported/updated to to fennoa.

Sale invoices
---------------

* Sale invoices and credit notes can be sent to Fennoa
* Payments can be sent to Fennoa and matched to invoices
* Payments can be fetched from Fennoa to Odoo and matched to invoices

If you are sending just one invoice, it will be sent immediately.
When sending multiple invoices (mass invoicing), the invoices will be sent in a queue.

When sending invoice to Fennoa, Odoo assigns a temporary invoice number "INV/123" to invoice,
and after invoice is approved in Fennoa, Odoo updates the invoice number and payment reference from there.

Payments
--------

* Sale invoice payments will be sent to Fennoa and will be matched to existing invoices
* Payments will be fetched automatically from Fennoa and matched to invoices in Odoo
