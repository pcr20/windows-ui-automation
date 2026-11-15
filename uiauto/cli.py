"""Command line: python -m uiauto <command> ...

Output is JSON (except `tree`, which is text unless --json) so an agent can parse it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading

from . import win32
from .uia import ACTIONS, UIA, format_node

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_profiles(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, "profiles.json"), encoding="utf-8") as f:
        return json.load(f)


def emit(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def resolve(args) -> win32.Window:
    """Pick the target window from --hwnd, or --profile (optionally narrowed by --window)."""
    if args.hwnd:
        return win32.window_info(int(args.hwnd, 0))
    if not args.profile:
        sys.exit("give --profile NAME or --hwnd 0x...")
    profiles = load_profiles(args.profiles)
    if args.profile not in profiles:
        sys.exit(f"unknown profile {args.profile!r}; known: {', '.join(profiles)}")
    wins = win32.windows_under(profiles[args.profile]["root"])
    if args.window:
        wins = [w for w in wins if args.window.lower() in w.title.lower()]
    if not wins:
        sys.exit("no matching window; is the application running? (try `launch`)")
    return wins[0]


def cmd_profiles(args):
    emit(load_profiles(args.profiles))


def cmd_windows(args):
    if args.profile:
        wins = win32.windows_under(load_profiles(args.profiles)[args.profile]["root"])
    else:
        wins = [w for w in win32.enum_windows() if w.title]
    emit([w.as_dict() for w in wins])


def cmd_launch(args):
    from .feasibility import launch

    profile = load_profiles(args.profiles)[args.profile]
    wins = win32.windows_under(profile["root"]) or launch(profile, args.timeout)
    emit([w.as_dict() for w in wins])


def cmd_close(args):
    from .feasibility import close

    emit({"closed": close(load_profiles(args.profiles)[args.profile])})


def cmd_tree(args):
    win = resolve(args)
    u = UIA()
    nodes, _, truncated = u.walk(u.from_hwnd(win.hwnd), args.depth, args.max_nodes)
    if args.json:
        emit(nodes)
    else:
        print(f"# {win.title!r} {hex(win.hwnd)}" + ("  (truncated)" if truncated else ""))
        print("\n".join(format_node(n) for n in nodes))


def cmd_shot(args):
    win = resolve(args)
    if win.iconic:
        win32.show_noactivate(win.hwnd)
    img = win32.capture(win.hwnd)
    img.save(args.out)
    emit({"file": os.path.abspath(args.out), "size": img.size, "blank": win32.is_blank(img),
          "window_rect": list(win.rect)})


def cmd_park(args):
    win = resolve(args)
    if args.x is None:
        win32.park(win.hwnd)
    else:
        win32.move(win.hwnd, args.x, args.y or 0)
    emit(win32.window_info(win.hwnd).as_dict())


def cmd_act(args):
    win = resolve(args)
    fg, cur = win32.foreground(), win32.cursor()
    result: dict = {}

    def work():
        try:
            import comtypes

            comtypes.CoInitialize()
            u = UIA()
            node, el = u.find(u.from_hwnd(win.hwnd), args.selector, args.depth)
            result["element"] = {k: node[k] for k in ("path", "type", "name", "aid")}
            result["result"] = u.act(el, args.action, args.value)
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"

    # Invoke on a button that opens a modal dialog does not return until the dialog
    # closes, so run the call on a worker thread and stop waiting after --timeout.
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(args.timeout)
    if t.is_alive():
        result["result"] = "pending: the call has not returned, a modal dialog probably opened (check `windows`)"
    fg_now = win32.foreground()
    result["focus_changed"] = fg_now != fg
    result["cursor_moved"] = win32.cursor() != cur
    emit(result)
    sys.stdout.flush()
    os._exit(1 if "error" in result else 0)


def cmd_feasibility(args):
    from .feasibility import Run

    profiles = load_profiles(args.profiles)
    names = list(profiles) if args.profile == "all" else [args.profile]
    code = 0
    for name in names:
        if name not in profiles:
            sys.exit(f"unknown profile {name!r}; known: {', '.join(profiles)}")
        code |= Run(name, profiles[name], args.out).execute(not args.no_launch, not args.no_probe, args.depth, args.keep_open)
    sys.exit(code)


def main(argv=None):
    if not win32.WIN:
        sys.exit("uiauto only runs on Windows")
    p = argparse.ArgumentParser(prog="uiauto", description="Background UI Automation test harness")
    p.add_argument("--profiles", help="path to profiles.json (default: repo root)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def target(sp, depth=True):
        sp.add_argument("--profile")
        sp.add_argument("--hwnd")
        sp.add_argument("--window", help="title substring, to pick a dialog within the profile")
        if depth:
            sp.add_argument("--depth", type=int, default=12)

    sub.add_parser("profiles").set_defaults(fn=cmd_profiles)
    sp = sub.add_parser("windows"); sp.add_argument("--profile"); sp.set_defaults(fn=cmd_windows)
    sp = sub.add_parser("launch"); sp.add_argument("profile"); sp.add_argument("--timeout", type=float, default=180)
    sp.set_defaults(fn=cmd_launch)
    sp = sub.add_parser("close"); sp.add_argument("profile"); sp.set_defaults(fn=cmd_close)
    sp = sub.add_parser("tree"); target(sp); sp.add_argument("--json", action="store_true")
    sp.add_argument("--max-nodes", type=int, default=3000); sp.set_defaults(fn=cmd_tree)
    sp = sub.add_parser("shot"); target(sp, depth=False); sp.add_argument("out"); sp.set_defaults(fn=cmd_shot)
    sp = sub.add_parser("park"); target(sp, depth=False); sp.add_argument("--x", type=int); sp.add_argument("--y", type=int)
    sp.set_defaults(fn=cmd_park)
    sp = sub.add_parser("act"); target(sp); sp.add_argument("selector"); sp.add_argument("action", choices=ACTIONS)
    sp.add_argument("--value"); sp.add_argument("--timeout", type=float, default=8); sp.set_defaults(fn=cmd_act)
    sp = sub.add_parser("feasibility"); sp.add_argument("profile", help="profile name, or 'all'")
    sp.add_argument("--out", default=os.path.join(HERE, "out")); sp.add_argument("--depth", type=int, default=12)
    sp.add_argument("--no-launch", action="store_true"); sp.add_argument("--no-probe", action="store_true")
    sp.add_argument("--keep-open", action="store_true", help="do not close an application the test started")
    sp.set_defaults(fn=cmd_feasibility)

    args = p.parse_args(argv)
    win32.set_dpi_aware()
    args.fn(args)


if __name__ == "__main__":
    main()
