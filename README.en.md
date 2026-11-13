# WorkTimer

A tiny always-on-top Windows desktop countdown for **flexible work hours**.

Tap to log today’s arrival window (e.g. **8:30–9:30**), compute leave time from a 9.5-hour flex day, and keep a transparent card that only shows **time left until you can leave**.

- **Website / download:** https://zddhhh.github.io/worktimer-subscribe/
- **Source (this mirror):** https://github.com/zddhhh/work-timer
- **Primary repo & releases (OTA):** https://gitcode.com/mdslanruo/work-timer
- **License:** [MIT](LICENSE)

> Installers and in-app updates are published on **GitCode Releases**. This GitHub repo is the public source mirror and accepts pull requests.

## Why it exists

Many offices use a flex window (arrive between 8:30 and 9:30, work 9.5 hours). WorkTimer turns that rule into a calm desktop countdown—no browser tab, no spreadsheet.

## Features (short)

- Transparent, topmost countdown card
- Flex arrival → leave-time calculation
- Work log / activity notes (optional)
- Themes and light desktop ornaments
- Auto-update from GitCode releases (Win10/11 and Win7 packages)

## Run from source (Windows)

```powershell
# Python 3.12 venv recommended
.\.venv\Scripts\Activate
python main.py
```

Use the interpreter inside `.venv`.

## Installers

Built artifacts (uploaded to GitCode Release, not this GitHub Releases page):

| Package | OS |
|---|---|
| `WorkTimer-Setup.exe` | Windows 8.1 / 10 / 11 (64-bit) |
| `WorkTimer-Win7-Setup.exe` | Windows 7 SP1 (64-bit) |

Download page: https://zddhhh.github.io/worktimer-subscribe/

## Contribute

PRs welcome on GitHub. Maintainers merge into the GitCode `main` first, then mirror here—please do not expect the GitHub “Merge” button to be the source of truth.

Please do **not** change `version.py`, the top section of `docs/更新说明.md`, or `RELEASE_NOTE` in `scripts/gitcode_release.py` on feature branches (release-only).

```powershell
git switch -c feat/short-description
# edit…
.\.venv\Scripts\python.exe -m unittest discover -s tests
git push -u origin feat/short-description
```

Full Chinese docs and maintainer notes: [README.md](README.md).

## Feedback

In the installed app: right-click → About → submit feedback (lands as a GitCode Issue). For code discussion, GitHub Issues are fine too.
