"""OneTab Saver - Extract tabs from OneTab Chrome extension and save to Markdown."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from pathlib import Path

import json5
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json5"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge two dicts; values from override take precedence."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """Load configuration from config.json5 and merge with config.user.json5 (user config has higher priority)."""
    # 1. Load base config from config.json5
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json5.load(f)

    # 2. If config.user.json5 exists, load and merge (user config overrides base)
    user_config_path = SCRIPT_DIR / "config.user.json5"
    if user_config_path.exists():
        with user_config_path.open(encoding="utf-8") as f:
            user_cfg = json5.load(f)
        # Recursively merge dicts; user config values take precedence
        cfg = _deep_merge(cfg, user_cfg)

    # Resolve output_md relative to script dir if not absolute
    md_path = Path(cfg["output_md"])
    if not md_path.is_absolute():
        cfg["output_md"] = str(SCRIPT_DIR / md_path)
    return cfg


def extract_onetab_html(config: dict) -> str:
    """Extract OneTab HTML using Chrome with the user's real profile.

    Strategy:
    1. Copy only OneTab extension data to a temp profile (minimal copy).
    2. Launch a fresh Chrome instance with that temp profile + the real extension.
    3. Read the OneTab page HTML.
    """
    import shutil
    import tempfile

    user_data_dir = Path(config["chrome_user_data_dir"])
    profile = config.get("chrome_profile", "Default")
    onetab_url = config["onetab_url"]
    ext_id = "chphlpgkkbolifaimnlloiipkdnihall"

    # Build a minimal temp profile with just OneTab data
    tmp_root = Path(tempfile.mkdtemp(prefix="onetab_chrome_"))
    try:
        src_profile = user_data_dir / profile
        dst_profile = tmp_root / profile
        dst_profile.mkdir(parents=True, exist_ok=True)

        # Copy Local State (Chrome needs it to launch)
        local_state = user_data_dir / "Local State"
        if local_state.exists():
            try:
                shutil.copy2(local_state, tmp_root / "Local State")
            except OSError:
                pass

        # Copy OneTab's extension storage (where the saved tabs live)
        onetab_dirs = [
            f"Local Extension Settings/{ext_id}",
            f"IndexedDB/chrome-extension_{ext_id}_0.indexeddb.leveldb",
            f"Local Storage/leveldb",
        ]
        for rel_dir in onetab_dirs:
            src = src_profile / rel_dir
            dst = dst_profile / rel_dir
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst, dirs_exist_ok=True, ignore_dangling_symlinks=True)

        # Find the extension path (installed version)
        ext_base = user_data_dir / "Extensions" if (user_data_dir / "Extensions").exists() else src_profile / "Extensions"
        ext_path = ext_base / ext_id
        if not ext_path.exists():
            ext_path = src_profile / "Extensions" / ext_id
        # Get the latest version directory
        if ext_path.exists():
            versions = sorted(ext_path.iterdir(), reverse=True)
            ext_version_dir = str(versions[0]) if versions else str(ext_path)
        else:
            raise FileNotFoundError(f"OneTab extension not found at {ext_path}")

        # Copy Preferences file (needed for extension registration)
        for fname in ("Preferences", "Secure Preferences"):
            src = src_profile / fname
            if src.exists():
                try:
                    shutil.copy2(src, dst_profile / fname)
                except OSError:
                    pass

        with sync_playwright() as p:
            # Use Playwright's bundled Chromium (not system Chrome) to avoid
            # conflicts with already-running Chrome instances
            browser = p.chromium.launch_persistent_context(
                user_data_dir=str(tmp_root),
                headless=False,  # extensions require headed mode
                ignore_default_args=[
                    "--disable-extensions",
                    "--disable-component-extensions-with-background-pages",
                ],
                args=[
                    f"--disable-extensions-except={ext_version_dir}",
                    f"--load-extension={ext_version_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-sync",
                ],
                timeout=30_000,
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(onetab_url, wait_until="networkidle", timeout=30_000)
            time.sleep(3)  # Give extension extra time to populate content
            # Try to wait for common OneTab selectors
            for selector in ("#tabGroupsDiv", ".tabGroup", "#contentAreaDiv", "body"):
                try:
                    page.wait_for_selector(selector, timeout=5_000)
                    break
                except Exception:
                    continue
            html = page.content()
            browser.close()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    return html


def parse_onetab_html(html: str) -> OrderedDict[str, list[tuple[str, str]]]:
    """Parse OneTab HTML into {date_string: [(url, title), ...]} ordered by appearance.

    OneTab structure:
    - div.tabGroup[data-id] for each group (first one with data-id="root" is the header)
    - Inside each group: a div containing date text like "3/20/2026 6:51:58 PM - 4 days ago"
    - Links are in div.tab > a.tabLink
    """
    soup = BeautifulSoup(html, "html.parser")
    result: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()

    # Date pattern: M/D/YYYY H:MM:SS AM/PM
    date_re = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M")

    tab_groups = soup.find_all(class_="tabGroup")

    for group in tab_groups:
        # Skip the root group (header with "All" label)
        if group.get("data-id") == "root":
            continue

        # Extract date from text within the group
        date_str = "Unknown Date"
        for div in group.find_all("div"):
            text = div.get_text(strip=True)
            m = date_re.search(text)
            if m:
                date_str = m.group(1)  # Just "M/D/YYYY"
                break

        # Extract links from .tab elements
        links: list[tuple[str, str]] = []
        for tab_div in group.find_all(class_="tab"):
            a_tag = tab_div.select_one("a.tabLink")
            if a_tag:
                url = a_tag.get("href", "").strip()
                # Get title from the link text (class tabLinkText or inner span)
                title = a_tag.get_text(strip=True)
                if url and url.startswith(("http://", "https://")):
                    links.append((url, title or url))

        if links:
            if date_str in result:
                result[date_str].extend(links)
            else:
                result[date_str] = links

    return result


def parse_existing_md(md_path: str) -> OrderedDict[str, list[tuple[str, str]]]:
    """Parse an existing Markdown file back into {date: [(url, title), ...]}."""
    result: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
    path = Path(md_path)
    if not path.exists():
        return result

    current_date: str | None = None
    md_link_re = re.compile(r"^-\s*\[(.+?)]\((.+?)\)\s*$")

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("## "):
                current_date = line[3:].strip()
                if current_date not in result:
                    result[current_date] = []
            elif current_date and (m := md_link_re.match(line)):
                title, url = m.group(1), m.group(2)
                result[current_date].append((url, title))

    return result


def merge_data(
    existing: OrderedDict[str, list[tuple[str, str]]],
    new: OrderedDict[str, list[tuple[str, str]]],
) -> OrderedDict[str, list[tuple[str, str]]]:
    """Merge new data into existing, deduplicating by URL within each date group."""
    merged: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()

    # Collect all date keys preserving order (existing first, then new)
    all_dates: list[str] = []
    for d in existing:
        if d not in all_dates:
            all_dates.append(d)
    for d in new:
        if d not in all_dates:
            all_dates.append(d)

    for date in all_dates:
        seen_urls: set[str] = set()
        links: list[tuple[str, str]] = []

        # Existing links first (they take precedence)
        for url, title in existing.get(date, []):
            if url not in seen_urls:
                seen_urls.add(url)
                links.append((url, title))
        # Then new links
        for url, title in new.get(date, []):
            if url not in seen_urls:
                seen_urls.add(url)
                links.append((url, title))

        if links:
            merged[date] = links

    return merged


def write_md(data: OrderedDict[str, list[tuple[str, str]]], md_path: str) -> None:
    """Write tab data to a Markdown file."""
    path = Path(md_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for date_str, links in data.items():
        lines.append(f"## {date_str}")
        lines.append("")
        for url, title in links:
            lines.append(f"- [{title}]({url})")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Written {sum(len(v) for v in data.values())} links in {len(data)} groups to {path}")


def main() -> None:
    config = load_config()
    md_path = config["output_md"]

    print("Extracting OneTab content from Chrome...")
    html = extract_onetab_html(config)

    print("Parsing OneTab HTML...")
    new_data = parse_onetab_html(html)
    print(f"  Found {sum(len(v) for v in new_data.values())} links in {len(new_data)} groups")

    # Merge with existing if md file exists
    existing_data = parse_existing_md(md_path)
    if existing_data:
        existing_count = sum(len(v) for v in existing_data.values())
        print(f"  Existing md has {existing_count} links in {len(existing_data)} groups")
        merged = merge_data(existing_data, new_data)
        merged_count = sum(len(v) for v in merged.values())
        print(f"  After merge & dedup: {merged_count} total links ({merged_count - existing_count:+d})")
    else:
        merged = new_data

    write_md(merged, md_path)
    print("Done!")


if __name__ == "__main__":
    main()