"""Microsoft UI Automation via comtypes: tree walk and pattern-based actions.

Every action goes through a UIA control pattern (Invoke, Value, SelectionItem ...),
so the real mouse and keyboard are never touched.
"""
from __future__ import annotations

from . import selector

PATTERNS = ["Invoke", "Value", "SelectionItem", "ExpandCollapse", "Toggle", "Selection", "Scroll",
            "ScrollItem", "Grid", "GridItem", "Table", "Text", "RangeValue", "Window", "Transform",
            "LegacyIAccessible"]
# Patterns that let an agent *do* something. LegacyIAccessible is excluded: WinForms reports it on every element.
ACTION_PATTERNS = {"Invoke", "Value", "SelectionItem", "ExpandCollapse", "Toggle"}
EXPAND_STATES = {0: "collapsed", 1: "expanded", 2: "partial", 3: "leaf"}


class UIA:
    def __init__(self):
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as mod

        self.mod = mod
        self.uia = comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)
        self.walker = self.uia.ControlViewWalker
        self.type_names = {getattr(mod, n): n[4:-13] for n in dir(mod)
                           if n.startswith("UIA_") and n.endswith("ControlTypeId")}
        self.avail_ids = {p: getattr(mod, f"UIA_Is{p}PatternAvailablePropertyId")
                          for p in PATTERNS if hasattr(mod, f"UIA_Is{p}PatternAvailablePropertyId")}

    # ---- reading -------------------------------------------------------
    def from_hwnd(self, hwnd: int):
        return self.uia.ElementFromHandle(hwnd)

    def pattern(self, el, name: str):
        raw = el.GetCurrentPattern(getattr(self.mod, f"UIA_{name}PatternId"))
        if not raw:
            raise LookupError(f"element does not support the {name} pattern")
        return raw.QueryInterface(getattr(self.mod, f"IUIAutomation{name}Pattern"))

    def describe(self, el, path: str, depth: int) -> dict:
        def get(fn, default=None):
            try:
                return fn()
            except Exception:
                return default

        r = get(lambda: el.CurrentBoundingRectangle)
        node = {
            "path": path,
            "depth": depth,
            "type": self.type_names.get(get(lambda: el.CurrentControlType), "?"),
            "name": get(lambda: el.CurrentName, "") or "",
            "aid": get(lambda: el.CurrentAutomationId, "") or "",
            "class": get(lambda: el.CurrentClassName, "") or "",
            "framework": get(lambda: el.CurrentFrameworkId, "") or "",
            "rect": [r.left, r.top, r.right, r.bottom] if r else None,
            "enabled": bool(get(lambda: el.CurrentIsEnabled, False)),
            "offscreen": bool(get(lambda: el.CurrentIsOffscreen, False)),
            "patterns": [p for p, pid in self.avail_ids.items()
                         if get(lambda pid=pid: el.GetCurrentPropertyValue(pid), False)],
        }
        if "Value" in node["patterns"]:
            v = get(lambda: self.pattern(el, "Value"))
            if v is not None:
                node["value"] = (get(lambda: v.CurrentValue, "") or "")[:200]
                node["readonly"] = bool(get(lambda: v.CurrentIsReadOnly, True))
        if "ExpandCollapse" in node["patterns"]:
            node["state"] = EXPAND_STATES.get(
                get(lambda: self.pattern(el, "ExpandCollapse").CurrentExpandCollapseState), "?")
        if "SelectionItem" in node["patterns"]:
            node["selected"] = bool(get(lambda: self.pattern(el, "SelectionItem").CurrentIsSelected, False))
        return node

    def children(self, el) -> list:
        kids = []
        try:
            child = self.walker.GetFirstChildElement(el)
            while child:
                kids.append(child)
                child = self.walker.GetNextSiblingElement(child)
        except Exception:
            pass
        return kids

    def walk(self, root, max_depth: int = 12, max_nodes: int = 3000):
        """Pre-order walk of the control view. Returns (nodes, elements, truncated)."""
        nodes, els, truncated = [], [], False
        stack = [(root, "0", 0)]
        while stack:
            el, path, depth = stack.pop()
            if len(nodes) >= max_nodes:
                truncated = True
                break
            nodes.append(self.describe(el, path, depth))
            els.append(el)
            if depth < max_depth:
                kids = self.children(el)
                for i in reversed(range(len(kids))):
                    stack.append((kids[i], f"{path}.{i}", depth + 1))
        return nodes, els, truncated

    def find(self, root, sel_text: str, max_depth: int = 12):
        sel = selector.parse(sel_text)
        nodes, els, _ = self.walk(root, max_depth=max_depth)
        node = selector.pick(nodes, sel)
        return node, els[nodes.index(node)]

    # ---- acting --------------------------------------------------------
    def act(self, el, action: str, value: str | None = None):
        """Perform one pattern-based action. Returns a short result string."""
        if action == "invoke":
            self.pattern(el, "Invoke").Invoke()
        elif action == "default":
            self.pattern(el, "LegacyIAccessible").DoDefaultAction()
        elif action == "select":
            self.pattern(el, "SelectionItem").Select()
        elif action == "expand":
            self.pattern(el, "ExpandCollapse").Expand()
        elif action == "collapse":
            self.pattern(el, "ExpandCollapse").Collapse()
        elif action == "toggle":
            self.pattern(el, "Toggle").Toggle()
        elif action == "set-value":
            if value is None:
                raise ValueError("set-value needs --value")
            self.pattern(el, "Value").SetValue(value)
        elif action == "scroll-into-view":
            self.pattern(el, "ScrollItem").ScrollIntoView()
        elif action == "get-text":
            try:
                return self.pattern(el, "Text").DocumentRange.GetText(20000)
            except LookupError:
                return self.pattern(el, "Value").CurrentValue
        else:
            raise ValueError(f"unknown action {action!r}")
        return "ok"


ACTIONS = ["invoke", "default", "select", "expand", "collapse", "toggle", "set-value",
           "scroll-into-view", "get-text"]


def format_node(n: dict) -> str:
    bits = [f'{n["path"]:<14}', "  " * n["depth"] + n["type"]]
    if n["name"]:
        bits.append(repr(n["name"][:70]))
    if n["aid"]:
        bits.append(f'aid={n["aid"]}')
    for key in ("state", "value"):
        if n.get(key):
            bits.append(f"{key}={n[key]!r}")
    if n.get("selected"):
        bits.append("SELECTED")
    if not n["enabled"]:
        bits.append("disabled")
    if n["offscreen"]:
        bits.append("offscreen")
    if n["patterns"]:
        bits.append("[" + ",".join(n["patterns"]) + "]")
    return " ".join(bits)
