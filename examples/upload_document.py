from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
from pathlib import Path
import logging
import os

# Example: Upload and Download Documents/Images
# This demonstrates how to upload documents and images to weclapp entities
# and download them back

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

# Example 1: Upload a document to a sales order
logging.info("=" * 50)
logging.info("Example 1: Upload a document to a sales order")
logging.info("=" * 50)

try:
    # First, get a sales order to attach the document to
    sales_orders = weclapp.get_all("salesOrder", limit=1)
    
    if not sales_orders:
        logging.error("No sales orders found. Skipping document upload example.")
    else:
        sales_order = sales_orders[0]
        logging.info(f"Using sales order: {sales_order.get('orderNumber')} (ID: {sales_order['id']})")
        
        # Create sample PDF content (in real usage, read from file)
        # with open("invoice.pdf", "rb") as f:
        #     pdf_content = f.read()
        
        # For this example, we'll use placeholder bytes
        sample_content = b"Sample document content for demonstration"
        
        # Upload the document
        # Content type is automatically inferred from the filename extension
        result = weclapp.upload(
            "document",
            data=sample_content,
            action="upload",
            filename="sample_document.txt",  # Content type inferred as text/plain
            params={
                "entityName": "salesOrder",
                "entityId": sales_order["id"],
                "name": "Sample Document.txt",
                "description": "Uploaded via weclappy example"
            }
        )
        
        logging.info(f"Document uploaded successfully!")
        logging.info(f"Document ID: {result.get('result', {}).get('id')}")

except WeclappAPIError as e:
    logging.error(f"API Error: {e}")
    if e.is_validation_error:
        logging.error(f"Validation errors: {e.get_validation_messages()}")


# Example 2: Download a document
logging.info("\n" + "=" * 50)
logging.info("Example 2: Download a document")
logging.info("=" * 50)

try:
    # Query for documents attached to an entity (entityName is required by weclapp API)
    # We'll use the sales order from Example 1 if available
    if sales_orders:
        documents = weclapp.get_all(
            "document",
            params={
                "entityName": "salesOrder",
                "entityId": sales_orders[0]["id"],
                "pageSize": 1
            },
            limit=1
        )
        
        if not documents:
            logging.info("No documents found for this sales order.")
        else:
            doc = documents[0]
            logging.info(f"Downloading document: {doc.get('name')} (ID: {doc['id']})")
            
            # Download the document
            result = weclapp.download("document", id=doc["id"])
            
            if "content" in result:
                logging.info(f"Downloaded {len(result['content'])} bytes")
                logging.info(f"Content-Type: {result['content_type']}")
            else:
                logging.info(f"Response: {result}")
    else:
        logging.info("Skipping - no sales order available from Example 1")

except WeclappAPIError as e:
    logging.error(f"API Error: {e}")


# Example 3: Download a sales invoice PDF
logging.info("\n" + "=" * 50)
logging.info("Example 3: Download a sales invoice PDF")
logging.info("=" * 50)

try:
    # Get a sales invoice
    invoices = weclapp.get_all("salesInvoice", limit=1)
    
    if not invoices:
        logging.error("No sales invoices found. Skipping PDF download example.")
    else:
        invoice = invoices[0]
        logging.info(f"Downloading PDF for invoice: {invoice.get('invoiceNumber')} (ID: {invoice['id']})")
        
        # Download the invoice PDF using the download method
        result = weclapp.download(
            "salesInvoice",
            id=invoice["id"],
            action="downloadLatestSalesInvoicePdf"
        )
        
        if "content" in result:
            logging.info(f"Downloaded {len(result['content'])} bytes")
            logging.info(f"Content-Type: {result['content_type']}")
            
            # Save to file
            filename = f"invoice_{invoice.get('invoiceNumber', invoice['id'])}.pdf"
            with open(filename, "wb") as f:
                f.write(result["content"])
            logging.info(f"Saved to: {filename}")
        else:
            logging.info(f"Response: {result}")

except WeclappAPIError as e:
    logging.error(f"API Error: {e}")


# Example 4: Upload with explicit content type override
logging.info("\n" + "=" * 50)
logging.info("Example 4: Content type override demonstration")
logging.info("=" * 50)

logging.info("""
When the filename extension doesn't match the actual content,
you can explicitly specify the content type:

    client.upload(
        "document",
        data=pdf_bytes,
        action="upload",
        content_type="application/pdf",  # Explicit override
        filename="data.bin",              # Would be octet-stream otherwise
        params={...}
    )

A warning is logged if content_type differs from what would be
inferred from the filename, helping catch potential mismatches.
""")

logging.info("=" * 50)
logging.info("Upload/Download examples completed!")
logging.info("=" * 50)
