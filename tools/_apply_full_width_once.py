from pathlib import Path


INDEX = Path("index.html")
UI_DOC = Path("UI.md")
DISPATCH = Path(".github/workflows/gemini-dispatch.yml")


def update_index() -> None:
    text = INDEX.read_text(encoding="utf-8")
    old = "      height: 100vh;\n      padding: 14px;\n      position: relative;"
    new = "      height: 100vh;\n      padding: 14px 0;\n      position: relative;"
    if old not in text:
        if new in text:
            return
        raise SystemExit("Expected .shell padding block was not found")
    INDEX.write_text(text.replace(old, new, 1), encoding="utf-8")


def update_ui_doc() -> None:
    text = UI_DOC.read_text(encoding="utf-8").rstrip()
    if "## Edge-to-edge horizontal layout" not in text:
        text += (
            "\n\n## Edge-to-edge horizontal layout\n\n"
            "The Fly Terminal shell has no horizontal page padding. The terminal/browser "
            "workspace, tab bar, and main toolbar therefore span the full viewport width, "
            "while the 14 px vertical shell padding and 12 px vertical spacing between "
            "sections are preserved. Do not reintroduce horizontal padding on `.shell`; "
            "add any required spacing inside individual controls instead."
        )
    UI_DOC.write_text(text + "\n", encoding="utf-8")


def restore_dispatch_workflow() -> None:
    text = DISPATCH.read_text(encoding="utf-8")
    start_marker = "\n  apply-full-width:\n"
    end_marker = "\n  fallthrough:\n"
    start = text.find(start_marker)
    if start < 0:
        return
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit("Temporary apply-full-width block has no fallthrough anchor")
    DISPATCH.write_text(text[:start] + text[end:], encoding="utf-8")


update_index()
update_ui_doc()
restore_dispatch_workflow()
