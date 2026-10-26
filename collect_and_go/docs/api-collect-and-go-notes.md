## API Integration Analysis: Collect&Go

**Context**
Analysis of the Collect&Go (Colruyt) private API to identify endpoints and authentication requirements for product search, cart management, and checkout integration in a Home Assistant add-on.

**Diagnostics**
The following network patterns and headers were identified during the interaction:

| Action | API Endpoint Pattern | Method |
| :--- | :--- | :--- |
| **Search/List** | `/gateway/ecomfoodb2c.eshop.wcsproductviewsearchsvc/v1/store/90004/productview/bySearchTerm/{term}` | `GET` |
| **View Cart** | `/gateway/ecomfoodb2c.eshop.wcscartsvcv2/v2/store/90004/cart/@self` | `GET` |
| **Order History** | `/gateway/ecomfoodb2c.eshop.wcsordersvcv2/v2/store/90004/order/@history` | `GET` |

**Authentication & Headers**
To interact with the gateway, the following headers are required for each request:

*   `x-cg-apikey`: Static application API key.
*   `wcauthtoken`: Dynamic session authentication token.
*   `content-type`: `application/json`

**Actionable Findings**
*   **Search Implementation:** Product searches by GTIN/EAN or keywords use the `wcsproductviewsearchsvc` endpoint. Successful responses return a `catalogEntryView` array containing product metadata.
*   **Cart Operations:** Adding products typically involves a `POST` request to the `wcsordersvc` or `wcscartsvcv2` domains. Manual inspection of the Network tab during an "Add to Cart" action is necessary to capture the specific payload structure (e.g., `partNumber` and `quantity`).
*   **Checkout Workflow:** The checkout process is a multi-step state machine. It likely requires `PUT` requests to the cart/order endpoint to set the handover service (e.g., `COLLECTNEXTDAY`) before a final `POST` to process the order.
*   **Automation Strategy:** Ensure the add-on securely stores the `wcauthtoken`. Since these tokens are session-based, the add-on may need to simulate the login flow to refresh tokens using the `/xtra/authentication` endpoints discovered in the network logs.

*Note: The code fixes and findings above were identified on a live page in DevTools. When applying them to your codebase, please adapt them to your project's specific technical stack (e.g., Tailwind CSS classes, CSS modules, framework components) rather than applying them as literal CSS overrides.*