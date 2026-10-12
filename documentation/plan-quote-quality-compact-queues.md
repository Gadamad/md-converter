# Quote quality and compact queues

Approved scope: repair the 79 damaged quotes from their original images, preserve Hungarian accents and existing results, check future OCR quality, provide a dashboard source-detail toggle and Open actions, then release and restart.

1. Back up the current queue database, preferences, journal, both Markdown copies, and affected source fingerprints. Visually verify every affected quote and retain the old recognition in the private repair audit.
2. Test and add conservative OCR quality checks. Try alternate image variants and the fallback engine before accepting suspicious mixed-script punctuation. Keep uncertain text for review, continue the batch, and retain the existing backend deadlines. Legitimate accents and multilingual text must survive.
3. Test and add a compact queue default, a persisted dashboard Show source details checkbox, and Open original / Open output actions. Preserve queue names, recovery controls, and busy-state protection.
4. Apply only verified repairs with source and record guards under existing locks. Re-export both matching Markdown copies and verify unaffected records, skipped images, preferences, queue rows and original images remain safe.
5. Run the relevant and full checks, review the changes, release v0.3.6 on GitHub, install the stamped build and restart. Verify the running version and the live interface.

Personal quote data, source images and backup files stay outside version control.
