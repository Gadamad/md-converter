# EPUB conversion implementation plan

**Goal:** Add EPUB intake and local conversion to a single Markdown or plain-text file, preserving reading order, readable structure and Hungarian accents.

**Scope:** The user requested EPUB as another input format with Markdown or TXT output. Pending the optional output preference question, use Markdown by default and an EPUB-only Markdown/TXT choice in Preferences. Existing source formats keep Markdown. Original books remain unchanged. Keep the approved app design and aligned footer.

**Architecture:** An isolated `epub_reader` module handles bounded ZIP/XML reading and book rendering. `converters.route` adds an optional `epub_output_format='md'` keyword without changing `ConvertResult`. The existing queue freezes that choice and publishes the chosen extension from its saved receipt. Named copies preserve bytes; optional Obsidian delivery remains a `.md` note even when the primary book export is TXT. Use existing Python, BeautifulSoup and markdownify dependencies.

**Spec:** This document records the request, stated defaults and implementation decisions. Existing authorization covers the feature and normal Git/build/install workflow; no additional stage approval is needed.

## Constraints and expected behavior

- Accept `.epub` through file selection, drag/drop, folders, saved queues and default CLI routing.
- One file per book in the `epub` output folder. Markdown preserves headings, lists, emphasis and basic tables; TXT contains readable text without Markdown metadata or formatting markers. Include title and authors when available.
- Follow the package spine, including auxiliary textual entries in their declared positions. Strip navigation blocks and scripts while retaining legitimate chapter headers and footers. Do not guess reading order when metadata is broken.
- Read ZIP members without extracting files, executing book content or fetching remote resources. Reject unsafe/ambiguous paths, duplicate members, unsupported reading-order documents, encrypted selected chapters, missing chapter data and control-XML DTDs. Font obfuscation alone is allowed.
- Bound archive entries, each decompressed document and cumulative document bytes; check cancellation during reads and between chapters. An image-only book reports that text extraction is unavailable; no new OCR workflow is added.
- Keep the four-field `ConvertResult` and old receipt/queue behavior. New options default to Markdown when absent. A delivery retry reuses private converted output even if the preference or source changes later.
- TXT stays `.txt` in normal output and named copies. Obsidian notes remain `.md`, with existing frontmatter plus the selected textual content.
- No new dependency, queue schema migration, unrelated redesign or modification of personal conversion results.

## Tasks and verification

- [x] **Reader/rendering:** Create `src/epub_reader.py` and `tests/test_epub_reader.py`. Interface: `read_epub(path, *, should_cancel=None) -> EpubBook`, immutable book fields `title`, `authors`, `chapters`; `render_markdown(book) -> str`, `render_text(book) -> str`; `EpubError(ValueError)` and `EpubCancelled`. Tests cover EPUB 2/3, spine ordering independent of ZIP/manifest order, Unicode, paragraphs/inline text/tables, auxiliary content, metadata, nested encoded paths, navigation, encrypted chapters versus fonts, missing/invalid XML, DTDs, limits, unsafe paths, no-text and cancellation. Use generated permutations/invariants with existing test tools instead of adding a property-testing dependency.
- [x] **Preferences/interface:** Add `epub_output_format` with values `md`/`txt`, default `md`; validate explicit saves and preserve older preferences. Add a native select in the existing Preferences modal with an EPUB-only explanation; save/cancel/restart behavior follows existing controls. Add EPUB file-picker support and freeze the format in new queue runs. Owner files: `src/preferences.py`, `src/converter_app.py`, `src/app_ui.py`, `src/queue_api.py` and focused preference/API/browser tests. Preserve visual tokens, density, footer and busy guards.
- [x] **Conversion/delivery:** Add `convert_epub(..., *, output_format='md', should_cancel=None)` and route keyword `epub_output_format='md'`; use reader rendering and atomic collision-safe writes. Update `src/queue_runner.py` publication to retain `.md`/`.txt`, produce Markdown vault notes for TXT, and pass EPUB cancellation/options. Permit `.txt` in `src/output_copy.py` without weakening path/ownership safeguards. Test real EPUB conversions, preserved originals, cancellation, mixed queues, collision handling, frozen format and export-only retries with named/vault copies.
- [x] **Review/finish:** Run the full suite, perform an independent reader/delivery review, verify actual Safari preferences behavior and installed app conversion/restart, preserve current queues/preferences/quote hashes, then commit/build/publish/install the next version with matching source metadata and backups. Document the checks and practical EPUB limits.

## Review focus

1. Chapter order must come from the spine, even when ZIP and manifest entries are shuffled.
2. UTF-16 XML/DTDs and percent-encoded traversal must not bypass parsing/path safeguards.
3. Font-only obfuscation must not reject an otherwise readable book; an encrypted selected chapter must fail clearly.
4. Real book headings, inline spacing, notes and accents must survive navigation removal and TXT rendering.
5. TXT delivery, vault notes and retry receipts must retain correct extensions and saved content without reconversion or changes to older completed work.
