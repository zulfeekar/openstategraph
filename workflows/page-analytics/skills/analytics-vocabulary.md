# Store analytics vocabulary

- "Revenue" is SUM(InvoiceLine.UnitPrice * InvoiceLine.Quantity); Invoice.Total is the per-invoice sum.
- "Revenue by genre" joins InvoiceLine -> Track -> Genre; "revenue by country" uses Invoice.BillingCountry.
- "Top customers" rank by lifetime spend (SUM of their Invoice.Total), named via Customer.FirstName/LastName.
- "Invoice trends" bucket Invoice.InvoiceDate by month; media-type mix joins InvoiceLine -> Track -> MediaType.
- Track catalogue size is not sales: Track rows are what the store offers, InvoiceLine rows are what sold.
