1. Make sure the OCA ``queue_job`` framework is available.
2. Go to *Connectors > Fennoa*.
3. Create a backend for each company:

   * **Base URL** (default: ``https://app.fennoa.com/api``)
   * **API User** (Fennoa client identifier)
   * **API Key** (plain text or Base64-encoded key)
   * **Company**

4. Press **Test Connection** to validate credentials.
5. (Optional) Click **Import Customers** to fetch customer master data from Fennoa.
6. A scheduled cron job *Fennoa Payment Sync* is created to import payments every hour.