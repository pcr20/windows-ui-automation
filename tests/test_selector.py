import pytest

from uiauto import selector

NODES = [
    {"path": "0", "type": "Window", "name": "MailStore Home", "aid": "", "class": "WindowsForms10", "patterns": ["Window"]},
    {"path": "0.0", "type": "Button", "name": "Archive E-mail", "aid": "btnArchive", "class": "", "patterns": ["Invoke"]},
    {"path": "0.1", "type": "Button", "name": "Export E-mail", "aid": "", "class": "", "patterns": ["Invoke"]},
    {"path": "0.2", "type": "TreeItem", "name": "Inbox", "aid": "", "class": "", "patterns": ["SelectionItem"]},
]


def test_parse():
    assert selector.parse("type=Button; name~=mail; nth=1") == {"type": "Button", "name~": "mail", "nth": 1}
    assert selector.parse("name=a=b") == {"name": "a=b"}
    for bad in ("", "Button", "colour=red"):
        with pytest.raises(ValueError):
            selector.parse(bad)


def test_pick():
    pick = lambda s: selector.pick(NODES, selector.parse(s))["path"]
    assert pick("type=button;name~=E-MAIL") == "0.0"
    assert pick("type=Button;nth=1") == "0.1"
    assert pick("aid=btnArchive") == "0.0"
    assert pick("path=0.2") == "0.2"
    assert pick("has=selectionitem") == "0.2"
    assert pick("class=windowsforms") == "0"
    with pytest.raises(LookupError):
        pick("type=Button;nth=2")
