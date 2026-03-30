# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OneTab Saver extracts saved tabs from the Chrome OneTab extension and exports them to a Markdown file. It uses Playwright to automate a headful Chrome browser (extensions don't work in headless mode) with a cloned profile to avoid lock conflicts with running Chrome instances.

## Run the Tool

```bash
# Windows (from repo root)
uv run python .\onetab_saver.py

# Or use the batch file
run.bat
```

## Architecture

### Core Flow (`onetab_saver.py`)

1. **Profile Cloning** (`extract_onetab_html`): Creates a minimal temp profile by copying only OneTab-specific data from the user's Chrome profile to avoid file locks while Chrome is running.

2. **Browser Launch** (`extract_onetab_html:94-112`): Launches Playwright's bundled Chromium with the temp profile, loading the real OneTab extension. Extensions require `headless=False`.

3. **HTML Extraction** (`extract_onetab_html:113-123`): Navigates to the OneTab extension URL and extracts the rendered HTML.

4. **Parsing** (`parse_onetab_html`): Uses BeautifulSoup to extract tab groups by date from the OneTab HTML structure:
   - Skips `div.tabGroup[data-id="root"]` (header)
   - Extracts dates from group text via regex `(<span class="math-inline">\d{1,2}/\d{1,2}/\d{4})\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M`
   - Collects `(url, title)` from `a.tabLink` elements

5. **Merge & Deduplication** (`merge_data`): Merges new data with existing Markdown output, deduplicating by URL within each date group. Existing links take precedence.

### Key Files

| File | Purpose |
|------|---------|
| `onetab_saver.py` | Main implementation with extraction, parsing, and merge logic |
| `config.json5` | User configuration (Chrome path, profile, extension URL, output path) |
| `run.bat` | Windows entry point that runs the module via `uv run` |

### Dependencies

- `playwright` - Browser automation
- `beautifulsoup4` - HTML parsing
- `json5` - Config with comments support

## Configuration

Edit `config.json5`:

```json5
{
    "chrome_user_data_dir": "C:\\Users\\<user>\\AppData\\Local\\Google\\Chrome\\User Data",
    "chrome_profile": "Default",
    "onetab_url": "chrome-extension://chphlpgkkbolifaimnlloiipkdnihall/onetab.html",
    "output_md": "kuaipan_onetab\\onetab_export.md"
}
```

## Extension ID

The OneTab extension ID is hardcoded: `chphlpgkkbolifaimnlloiipkdnihall`

If the user has a different OneTab version or fork, update `config.json5` with the correct `onetab_url`.
