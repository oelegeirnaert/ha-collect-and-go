# Changelog

All notable changes to the Collect & Go add-on. This project follows
[Semantic Versioning](https://semver.org/): **MAJOR** for breaking changes,
**MINOR** for new features, **PATCH** for fixes.

## [1.0.1] — 2026-10-22

### Fixed

- Adding an item to the list no longer returns a generic *500 Internal Server
  Error* when the Colruyt API answers with a non-JSON or error-shaped body
  (plain-text "OK", WAF block page, …). The API client now validates and
  tolerates those responses and returns a clean, readable error instead.
- Hardened all list/search parsing against unexpected response shapes and
  non-object entries, so one malformed product or item can no longer break
  the whole view.

## [1.0.0] — 2026-10-22

### Added

- Initial release: shared Collect&Go / Xtra shopping list in the Home
  Assistant sidebar.
- Connect your Xtra account with the `clpbff_session` cookie (no password
  stored); session kept in the add-on's data folder.
- View the shared list, search the Colruyt assortment (images + prices),
  add items with quantity, remove items, free-text items.
- "Frequently bought" quick-add section and deep link to the real
  Collect&Go cart for checkout.
- UI in English, Nederlands and Français.
- Optional REST API on port 8099 for automations (`rest_command`).
