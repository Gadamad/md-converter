# MD Converter 0.3.1

Saved queues are easier to find, reopen and remove.

- A visible **Saved queues** label and “Choose a name to reopen it” hint explain the dropdown. Choosing a name immediately restores that queue without starting conversion.
- **Queue actions → Delete queue…** removes the selected queue after a confirmation naming it. Original files, converted Markdown and other queues are kept.
- Empty queues can also be deleted. Deleting the last queue creates a fresh Inbox.
- **Clear all items** replaces the ambiguous “Clear queue” wording; this action keeps the saved queue's name.
- Deletion is transactional, is blocked during conversion, and uses the queue ID shown in the confirmation. Failed writes preserve the queue and its contents.

No new runtime dependencies or database migration are required.

Validation: 276 tests and 4 subtests pass, including deletion rollback, restart persistence, file preservation, stale confirmations, and browser checks at the minimum window size in light and dark themes. Five existing PyMuPDF deprecation warnings remain.
