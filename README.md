# windows-ui-automation

Test harness for driving Windows GUI applications **in the background** through
Microsoft UI Automation (UIA), so an agent can operate them without taking over
the mouse, keyboard or foreground window.

Everything goes through UIA control patterns (Invoke, Value, SelectionItem,
ExpandCollapse ...) and `PrintWindow` capture. No synthetic input is sent.

First target: MailStore Home (two portable installs, see `profiles.json`).

## Run the feasibility test

```bat
run_feasibility.bat            & rem all profiles
run_feasibility.bat mailstore  & rem one profile
```

This creates `.venv`, installs `comtypes` and `Pillow`, launches the application
if it is not running, and writes `out\<profile>-<timestamp>\`:

| File | Content |
|---|---|
| `report.md` | Verdict and pass/fail table |
| `tree.txt` / `tree.json` | Every UIA element with its path, type, name, AutomationId and patterns |
| `before.png` / `after.png` | Background captures before and after the select probe |

Checks:

1. **Element tree**: how many elements are both actionable and identifiable.
2. **Background capture**: `PrintWindow` returns real content while the window is not in front.
3. **Expand/collapse** and **Select item**: navigation-only probes on tree items, restored afterwards.
4. **Focus kept / Cursor untouched**: the application never took the foreground and the pointer did not move.

The probes only navigate. Nothing is invoked, typed or deleted. Leave the PC
alone for the few seconds the probes run, or the cursor check will warn.

## Command line

```bat
.venv\Scripts\python -m uiauto windows --profile mailstore
.venv\Scripts\python -m uiauto tree --profile mailstore --depth 8
.venv\Scripts\python -m uiauto shot --profile mailstore out\shot.png
.venv\Scripts\python -m uiauto act --profile mailstore "type=TreeItem;name~=inbox" select
.venv\Scripts\python -m uiauto act --profile mailstore "aid=searchBox" set-value --value "invoice"
.venv\Scripts\python -m uiauto park --profile mailstore
```

- Target: `--profile NAME` (largest window of that install), `--window "title"` for a dialog, or `--hwnd 0x...`.
- Selector terms, joined with `;`: `path=`, `type=`, `name=`, `name~=` (contains), `aid=`, `class=`, `has=<pattern>`, `nth=`.
- Actions: `invoke`, `default`, `select`, `expand`, `collapse`, `toggle`, `set-value`, `scroll-into-view`, `get-text`.
- `act` reports `focus_changed` and `cursor_moved`. If a call opens a modal dialog it returns `pending` after `--timeout`; list `windows` to find the dialog.
- `park` moves the window off the right edge of the desktop, where it still renders and can be captured.

## Known limits

- A minimised window cannot be captured; the tools restore it without activating.
- Custom-drawn controls may expose no patterns; `tree.txt` shows what is reachable.
- Paths (`path=0.3.1`) change when the UI changes; prefer name or AutomationId.

## Tests

`python -m pytest tests` covers the selector logic and runs on any OS.
