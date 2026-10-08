# Interface direction

Refined native Mac utility. Use the system font, generous but practical spacing, neutral surfaces and a restrained green accent. Support system, light and dark appearances. Align control heights and group actions by purpose.

- Header: product name and Preferences.
- Source switch: files/folders or pasted text/URL.
- Files: a compact drop target and a single aligned Add files / Add folder toolbar. Folders can contain any supported formats, including nested files.
- Workspace: queue and activity tabs; compact saved-collection selector with New/Rename, an autosave indicator, per-item status, and readable filenames with full paths available on hover. Secondary clearing actions live in a menu.
- Recovery: interrupted batches offer Resume; failed batches offer Retry failed. Show saved and failed counts.
- Footer: destination and optional vault delivery; one primary Convert queue action for waiting items and a contextual Retry failed action. During processing, replace conversion with Stop & save.
- Intake: files, browser links, website shortcuts and pasted text collect without conversion. Text/URL has an explicit Add to queue action; links are fetched on conversion. Queues survive application restarts automatically.
- Preferences: appearance, output destination, quote details and auto-open behavior; changes persist only on Save.

Use accessible contrast, visible keyboard focus, semantic buttons, live progress, modal focus management, reduced-motion support and layouts that remain usable at the minimum window size. Use textContent for filenames and log messages. Avoid animation without a functional purpose.
