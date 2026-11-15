"""Feasibility test: can an application be driven through UI Automation alone,
in the background, without taking the mouse, keyboard or focus?

The probes are navigation-only (expand/collapse and select tree items, then restore).
Nothing is invoked, typed or deleted.
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import subprocess
import time

from . import win32
from .uia import ACTION_PATTERNS, UIA, format_node


def is_transient(u: UIA, win, profile: dict) -> bool:
    """Splash screens and progress dialogs: listed in the profile, or a small window with a progress bar."""
    try:
        root = u.from_hwnd(win.hwnd)
        if (root.CurrentAutomationId or "") in profile.get("transient", []):
            return True
        kids = u.children(root)
        return len(kids) < 8 and any(u.type_names.get(k.CurrentControlType) == "ProgressBar" for k in kids)
    except Exception:
        return True


def wait_ready(profile: dict, timeout: float = 180, settle: float = 5) -> list:
    """Wait until the main window is not a transient one and has been the same window for `settle` seconds."""
    u = UIA()
    deadline, last, since = time.time() + timeout, None, time.time()
    while time.time() < deadline:
        wins = win32.windows_under(profile["root"])
        key = wins[0].hwnd if wins and not is_transient(u, wins[0], profile) else None
        if key != last:
            last, since = key, time.time()
        elif key and time.time() - since >= settle:
            return wins
        time.sleep(1)
    return []


def launch(profile: dict, timeout: float = 180) -> list:
    """Start the profile's application without activating it; wait for its main window."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = win32.SW_SHOWNOACTIVATE
    subprocess.Popen([os.path.join(profile["root"], profile["launch"])], cwd=profile["root"], startupinfo=si)
    return wait_ready(profile, timeout)


def close(profile: dict, timeout: float = 60) -> bool:
    """Ask every top-level window of the profile to close; True once they are all gone."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = win32.windows_under(profile["root"])
        if not wins:
            return True
        for w in wins:
            win32.close_window(w.hwnd)
        time.sleep(2)
    return False


class Run:
    def __init__(self, name: str, profile: dict, out_root: str):
        self.name, self.profile = name, profile
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out = os.path.join(out_root, f"{name}-{stamp}")
        os.makedirs(self.out, exist_ok=True)
        self.checks: list[tuple[str, str, str]] = []
        self.notes: list[str] = []

    def check(self, name: str, status: str, detail: str) -> None:
        self.checks.append((name, status, detail))
        print(f"  [{status:4}] {name}: {detail}")

    def target_has_focus(self) -> bool:
        fg = win32.foreground()
        return bool(fg) and win32.window_info(fg).pid in {w.pid for w in win32.windows_under(self.profile["root"])}

    def guarded(self, label: str, fn):
        """Run fn and record whether focus or the cursor moved while it ran."""
        had, cur = self.target_has_focus(), win32.cursor()
        result = fn()
        time.sleep(0.7)
        if not had and self.target_has_focus():
            self.stolen.append(label)
        if win32.cursor() != cur:
            self.cursor_moved.append(label)
        return result

    def execute(self, do_launch: bool = True, probe: bool = True, depth: int = 12, keep_open: bool = False) -> int:
        launched_before = bool(win32.windows_under(self.profile["root"]))
        try:
            return self._execute(do_launch, probe, depth)
        finally:
            if not launched_before and not keep_open and win32.windows_under(self.profile["root"]):
                print("  closing the application (it was started by the test)" if close(self.profile)
                      else "  WARNING: the application did not close")

    def _execute(self, do_launch: bool, probe: bool, depth: int) -> int:
        win32.set_dpi_aware()
        root = self.profile["root"]
        self.stolen, self.cursor_moved = [], []
        print(f"Feasibility test: {self.name} ({root})")

        if win32.windows_under(root):
            wins = wait_ready(self.profile, timeout=60)
        elif do_launch:
            wins = self.guarded("launch", lambda: launch(self.profile))
            self.notes.append("Application was launched by the test and closed afterwards unless --keep-open.")
        else:
            wins = []
        if not wins:
            self.check("Window found", "FAIL", "no settled main window (not running, still starting after the "
                       "timeout, or another instance blocked the launch)")
            return self.finish()
        main = wins[0]
        self.check("Window found", "PASS", f"{len(wins)} window(s); main = {main.title!r} {hex(main.hwnd)}")
        if main.iconic:
            self.guarded("restore", lambda: win32.show_noactivate(main.hwnd))
            self.notes.append("Main window was minimised; restored without activating (capture needs it un-minimised).")
            main = win32.window_info(main.hwnd)

        # 1. element tree ---------------------------------------------------
        u = UIA()
        t0 = time.time()
        nodes, els, truncated = u.walk(u.from_hwnd(main.hwnd), max_depth=depth)
        secs = time.time() - t0
        with open(os.path.join(self.out, "tree.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(format_node(n) for n in nodes))
        with open(os.path.join(self.out, "tree.json"), "w", encoding="utf-8") as f:
            json.dump(nodes, f, indent=1)
        actionable = [n for n in nodes if n["enabled"] and ACTION_PATTERNS & set(n["patterns"])]
        identifiable = [n for n in actionable if n["name"] or n["aid"]]
        self.stats = {
            "elements": len(nodes), "truncated": truncated, "walk_seconds": round(secs, 1),
            "actionable": len(actionable), "actionable_identifiable": len(identifiable),
            "by_type": collections.Counter(n["type"] for n in nodes).most_common(12),
            "frameworks": collections.Counter(n["framework"] or "?" for n in nodes).most_common(),
            "patterns": collections.Counter(p for n in nodes for p in n["patterns"]).most_common(),
        }
        status = "PASS" if len(identifiable) >= 10 else "WARN" if identifiable else "FAIL"
        self.check("Element tree", status,
                   f"{len(nodes)} elements in {secs:.1f}s; {len(identifiable)} actionable and identifiable "
                   f"(of {len(actionable)} actionable)")

        # 2. background capture ---------------------------------------------
        before = None
        try:
            before = win32.capture(main.hwnd)
            before.save(os.path.join(self.out, "before.png"))
            blank = win32.is_blank(before)
            self.check("Background capture", "FAIL" if blank else "PASS",
                       f"{before.size[0]}x{before.size[1]} via PrintWindow; " + ("image is blank" if blank else "has content"))
        except Exception as e:
            self.check("Background capture", "FAIL", str(e))

        # 3. navigation probes ----------------------------------------------
        if probe:
            self.probe_expand(u, nodes, els)
            self.probe_select(u, nodes, els, main.hwnd, before)
        else:
            self.check("Action probes", "SKIP", "--no-probe")

        # 4. focus and cursor -----------------------------------------------
        if "launch" in self.stolen:
            self.check("Focus on launch", "WARN", "the application took the foreground while starting; "
                       "start it once and leave it running (parked) to avoid this")
        acted = [s for s in self.stolen if s != "launch"]
        self.check("Focus kept", "FAIL" if acted else "PASS",
                   "focus moved to the application during: " + ", ".join(acted) if acted
                   else "no action gave the application the foreground")
        self.check("Cursor untouched", "WARN" if self.cursor_moved else "PASS",
                   "cursor moved during: " + ", ".join(self.cursor_moved) + " (ignore if you were using the mouse)"
                   if self.cursor_moved else "cursor position unchanged")
        self.windows = [w.as_dict() for w in win32.windows_under(root)]
        return self.finish()

    def probe_expand(self, u: UIA, nodes, els) -> None:
        idx = next((i for i, n in enumerate(nodes) if n["type"] == "TreeItem" and n["enabled"]
                    and n.get("state") in ("collapsed", "expanded")), None)
        if idx is None:
            self.check("Expand/collapse", "SKIP", "no expandable tree item found (see tree.txt)")
            return
        n, el = nodes[idx], els[idx]
        first, back = ("expand", "collapse") if n["state"] == "collapsed" else ("collapse", "expand")
        try:
            self.guarded("expand/collapse", lambda: u.act(el, first))
            changed = u.describe(el, n["path"], n["depth"]).get("state") != n["state"]
            self.guarded("expand/collapse", lambda: u.act(el, back))
            restored = u.describe(el, n["path"], n["depth"]).get("state") == n["state"]
            self.check("Expand/collapse", "PASS" if changed and restored else "FAIL",
                       f"{n['name']!r}: {first} changed state={changed}, restored={restored}")
        except Exception as e:
            self.check("Expand/collapse", "FAIL", f"{n['name']!r}: {e}")

    def probe_select(self, u: UIA, nodes, els, hwnd: int, before) -> None:
        items = [i for i, n in enumerate(nodes) if n["type"] == "TreeItem" and n["enabled"]
                 and "SelectionItem" in n["patterns"]]
        orig = next((i for i in items if nodes[i].get("selected")), None)
        cands = [i for i in items if i != orig]
        pick = next((i for i in cands if not nodes[i]["offscreen"]), cands[0] if cands else None)
        if pick is None:
            self.check("Select item", "SKIP", "no selectable tree item found (see tree.txt)")
            return
        n, el = nodes[pick], els[pick]
        try:
            self.guarded("select", lambda: u.act(el, "select"))
            time.sleep(1.0)
            selected = bool(u.describe(el, n["path"], n["depth"]).get("selected"))
            detail = f"{n['name']!r}: selected={selected}"
            try:
                from PIL import ImageChops

                after = win32.capture(hwnd)
                after.save(os.path.join(self.out, "after.png"))
                if before is not None and after.size == before.size:
                    detail += f"; capture changed={ImageChops.difference(before, after).getbbox() is not None}"
            except Exception as e:
                detail += f"; capture after failed: {e}"
            if orig is not None:
                self.guarded("select", lambda: u.act(els[orig], "select"))
                detail += "; original selection restored"
            self.check("Select item", "PASS" if selected else "FAIL", detail)
        except Exception as e:
            self.check("Select item", "FAIL", f"{n['name']!r}: {e}")

    def finish(self) -> int:
        statuses = {c[0]: c[1] for c in self.checks}
        fails = [k for k, v in statuses.items() if v == "FAIL"]
        core = all(statuses.get(k) == "PASS" for k in ("Element tree", "Background capture", "Focus kept"))
        verdict = ("VIABLE: tree, background capture and focus all pass" if core and not fails
                   else "NOT VIABLE as tested: failed " + ", ".join(fails) if fails
                   else "PARTLY VIABLE: review the WARN/SKIP rows and tree.txt")
        lines = [f"# UI Automation feasibility: {self.name}", "",
                 f"- Run: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
                 f"- Root: `{self.profile['root']}`", f"- **Verdict: {verdict}**", "",
                 "| Check | Result | Detail |", "|---|---|---|"]
        lines += [f"| {n} | {s} | {d.replace('|', '/')} |" for n, s, d in self.checks]
        stats = getattr(self, "stats", None)
        if stats:
            lines += ["", "## Tree statistics", "",
                      f"- Elements: {stats['elements']}" + (" (truncated)" if stats["truncated"] else ""),
                      f"- Actionable: {stats['actionable']}; with a name or AutomationId: {stats['actionable_identifiable']}",
                      "- Frameworks: " + ", ".join(f"{k} {v}" for k, v in stats["frameworks"]),
                      "- Control types: " + ", ".join(f"{k} {v}" for k, v in stats["by_type"]),
                      "- Patterns: " + ", ".join(f"{k} {v}" for k, v in stats["patterns"])]
        if getattr(self, "windows", None):
            lines += ["", "## Windows", ""] + [f"- `{w['hwnd']}` {w['title']!r} ({w['class']})" for w in self.windows]
        if self.notes:
            lines += ["", "## Notes", ""] + [f"- {n}" for n in self.notes]
        lines += ["", "Files: `tree.txt`, `tree.json`, `before.png`, `after.png`."]
        with open(os.path.join(self.out, "report.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(self.out, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"profile": self.name, "verdict": verdict, "checks": self.checks, "stats": stats,
                       "notes": self.notes}, f, indent=1)
        print(f"\n{verdict}\nReport: {os.path.join(self.out, 'report.md')}")
        return 1 if fails else 0
