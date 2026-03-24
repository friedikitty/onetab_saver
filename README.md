# OneTab Saver

Automatically extract all saved tabs from the Chrome [OneTab](https://chromewebstore.google.com/detail/onetab/chphlpgkkbolifaimnlloiipkdnihall?hl=en&pli=1) extension and export them to a clean Markdown file. Supports incremental merge with deduplication by URL.

## Usage

* copy `config.json5` to `config.user.json5`, fill it correctly

```json
{
    // Path to Chrome user data directory
    "chrome_user_data_dir": "C:\\Users\\youname\\AppData\\Local\\Google\\Chrome\\User Data",
    // Chrome profile directory name (e.g. "Default", "Profile 1")
    "chrome_profile": "Default",
    // OneTab extension page URL
    "onetab_url": "chrome-extension://you_url/onetab.html",
    // Output markdown file path (relative to this config file's directory, or absolute)
    "output_md": "the_folder_you_want_to_save\\onetab_export.md"
}
```

* Double-click `run.bat`, or from the command line:

```bash
run.bat
```

* `output_md` you can set to a folder with apples' cloud drive or onedrive or anything that automatically sync to the cloud, then you get the onetab sync.

    you can use your openclaw or simple system schedule to make this become a repeat task

## How It Works

The core challenge is that OneTab stores its data inside a `chrome-extension://` page that can't be accessed from outside the browser. This tool solves it in 4 stages:

### 1. Profile Cloning (avoid Chrome lock conflicts)

Chrome locks its user data directory while running, so we can't use it directly. Instead, the tool creates a **minimal temp profile** by copying only the files OneTab needs:

- `Local Extension Settings/<ext_id>/` - OneTab's LevelDB storage (the actual saved tabs)
- `IndexedDB/chrome-extension_<ext_id>_*/` - alternative storage location
- `Local Storage/leveldb/` - extension local storage
- `Preferences` / `Secure Preferences` - extension registration
- `Local State` - Chrome launch requirement

This is much faster than copying the entire profile (~seconds vs minutes).

### 2. Browser Automation (Playwright + Chromium)

The tool uses **Playwright's bundled Chromium** (not system Chrome) to avoid conflicts with any running Chrome instance. Key flags:

- `--load-extension=<path>` - loads the real OneTab extension from the system install
- `--disable-extensions-except=<path>` - prevents other extensions from loading
- `ignore_default_args=["--disable-extensions"]` - overrides Playwright's default which disables all extensions
- `headless=False` - required because Chrome extensions don't work in headless mode

The browser navigates to `chrome-extension://chphlpgkkbolifaimnlloiipkdnihall/onetab.html` and waits for the content to render.

### 3. HTML Parsing (BeautifulSoup)

OneTab's page structure:

```
div#contentAreaDiv
  +-- div.tabGroup[data-id="root"]     <- header group (skipped)
  +-- div.tabGroup[data-id="..."]      <- one per saved session
        +-- div (date text: "3/20/2026 6:51:58 PM - 4 days ago")
        \-- div.tab[data-id="..."]      <- one per saved tab
              \-- a.tabLink[href="..."]   <- the actual link + title
```

The parser:
- Skips the `data-id="root"` group (it's just the UI header)
- Extracts dates via regex `(\d{1,2}/\d{1,2}/\d{4})` from group text
- Collects `(url, title)` pairs from `a.tabLink` elements
- Ignores all `<img>` / favicon elements

### 4. Merge & Dedup

When the output `.md` already exists, the tool:

1. Parses the existing file back into `{date: [(url, title), ...]}` structure
2. For each date group present in both old and new data:
   - Keeps all existing links (they take precedence)
   - Appends new links whose URL hasn't been seen yet
3. Date groups unique to either side are included as-is
4. Writes the merged result back

This makes the tool safe to run repeatedly - it never creates duplicate entries.

## Configuration

Edit `config.json5`:

```json5
{
    // Path to Chrome user data directory
    "chrome_user_data_dir": "C:\\Users\\<your_username>\\AppData\\Local\\Google\\Chrome\\User Data",
    // Chrome profile directory name (e.g. "Default", "Profile 1")
    "chrome_profile": "Default",
    // OneTab extension page URL, use your chrome to open it to see
    "onetab_url": "chrome-extension://xxxxxxxx/onetab.html",
    // Output markdown file path (relative to this config file's directory, or absolute)
    "output_md": "onetab_export.md"
}
```

## Output Format

```markdown
## 3/20/2026

- [Page Title](https://example.com)
- [Another Page](https://another.com)

## 3/19/2026

- [Older Page](https://old.com)
```

## Dependencies

- `playwright` - browser automation
- `beautifulsoup4` - HTML parsing
- `json5` - config file with comments support

