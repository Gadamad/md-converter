# MD Converter 0.3.2

The whole-queue deletion action was hard to find inside Queue actions. A visible **Delete queue…** button now sits beside **New** and **Rename** under Saved queues.

Choose the queue name, click **Delete queue…**, and confirm its name in the dialog. This removes the saved queue and its entries. Original files, exported Markdown and other queues are kept. Empty queues can also be removed; deleting the last creates a fresh Inbox.

The existing menu action remains available. Both buttons use the same confirmed deletion flow, stay disabled during conversion, and return keyboard focus to the opening control when the dialog closes.

No new dependencies or database changes are required.

Validation: 276 tests and 4 subtests pass, including whole-queue deletion, confirmation cancellation, keyboard focus, disabled states during conversion, and alignment at the minimum window size. Five existing PyMuPDF deprecation warnings remain.
