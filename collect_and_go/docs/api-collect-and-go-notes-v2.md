## Session Summary: Collect&Go API & Session Analysis

**Context**
Analysis of `www.collectandgo.be` to identify session persistence mechanisms and REST API endpoints for a Home Assistant Add-on integration. The analysis covers authentication, cart management, and the checkout flow.

**Diagnostics**
The following cookies were identified as critical for maintaining session state and identity:

| Cookie Name | Purpose | Key Data Points |
| :--- | :--- | :--- |
| `cscsapersisted` | Identity Persistence | `visitor_stitch_user_id`, Adobe ECID |
| `tms_storevisit` | Session Context | `last_login_state`, `order_shipping_method` |
| `WC_SESSION_ESTABLISHED` | Platform Session | Boolean flag for HCL Commerce session status |
| `WC_ACTIVEPOINTER` | Store Context | Active store/org ID (e.g., `90004`) |
| `reese84` | Security | Bot detection/fingerprinting (Time-sensitive) |

**Actionable Findings**
* **Identity Management:** The `visitor_stitch_user_id` found in `cscsapersisted` and `tms_storevisit` (Base64 encoded) is required to link the session to a specific user.
* **Store Context:** API requests require a `{storeId}`. The value `90004` was extracted from the `WC_ACTIVEPOINTER` cookie.
* **Security Constraints:** The `reese84` cookie is mandatory. Automated requests without a valid, unexpired security cookie or proper `WCToken`/`WCTrustedToken` headers will be blocked (403 Forbidden).

**Proposed API Strategy**
The site utilizes HCL Commerce (WebSphere) REST patterns. The following endpoints were identified as the primary targets for automation:


`````md
### Authentication & Session
- Login: POST /wcs/resources/store/V2/loginidentity
- Refresh: POST /wcs/resources/store/{storeId}/loginidentity/refresh

### Cart Operations
- Get Cart: GET /wcs/resources/store/{storeId}/cart/@self
- Add Item: POST /wcs/resources/store/{storeId}/cart
- Remove Item: DELETE /wcs/resources/store/{storeId}/cart/item/{orderItemId}

### Checkout Flow
- Prepare Order: POST /wcs/resources/store/{storeId}/cart/@self/checkout
- Set Pickup: PUT /wcs/resources/store/{storeId}/cart/@self/shipping_info
- Finalize Order: POST /wcs/resources/store/{storeId}/order
`````


**Recommendations for Implementation**
* **Header Management:** Ensure the Home Assistant Add-on captures and sends `WCToken` and `WCTrustedToken`. These are often returned in the login response body rather than as cookies.
* **Payload Verification:** Monitor the Network tab for `POST` requests to `/wcs/resources` during manual checkout to capture the exact JSON schema for `shipping_info` (specifically `addressId` and `shipModeId`).
* **Bot Mitigation:** Implement logic to handle or refresh the `reese84` cookie to prevent automated traffic detection.

*Note: The code fixes and findings above were identified on a live page in DevTools. When applying them to your codebase, please adapt them to your project's specific technical stack (e.g., Tailwind CSS classes, CSS modules, framework components) rather than applying them as literal CSS overrides.*