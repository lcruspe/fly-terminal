"""Hermetic tests for the macOS injection logic (no AppKit or desktop access)."""
import ast
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / "macos" / "fly-mac-streamer.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
namespace = {
    "kCGEventFlagMaskCommand": 0x00100000,
    "kCGEventFlagMaskShift": 0x00020000,
    "kCGEventFlagMaskControl": 0x00040000,
    "kCGEventFlagMaskAlternate": 0x00080000,
}

# Load just the modifier constants and pure functions, without importing CoreGraphics
# or starting the streamer on the CI host.
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "MODIFIER_KEY_FLAGS" for t in node.targets
    ):
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    if isinstance(node, ast.FunctionDef) and node.name == "keyboard_event_flags":
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)


class NativeModifierInjectionTests(unittest.TestCase):
    def test_alt_keyup_clears_option_flag_even_if_original_keydown_had_it(self):
        mask = namespace["kCGEventFlagMaskAlternate"]
        flags = namespace["keyboard_event_flags"]
        self.assertEqual(flags("AltLeft", True, {"alt": True}), mask)
        self.assertEqual(flags("AltLeft", False, {"alt": True}), 0)
        self.assertEqual(flags("AltRight", False, {"alt": True, "shift": True}),
                         namespace["kCGEventFlagMaskShift"])

    def test_ordinary_keydown_retains_required_modifiers(self):
        flags = namespace["keyboard_event_flags"]
        self.assertEqual(flags("KeyA", True, {"alt": True, "shift": True}),
                         namespace["kCGEventFlagMaskAlternate"] | namespace["kCGEventFlagMaskShift"])
        self.assertEqual(flags("KeyA", False, {"meta": True}), namespace["kCGEventFlagMaskCommand"])
        self.assertEqual(flags("ControlLeft", False, {"ctrl": True}), 0)
        self.assertEqual(flags("MetaRight", False, {"meta": True, "shift": True}),
                         namespace["kCGEventFlagMaskShift"])

    def test_stale_modifier_reconciliation_before_unicode_input(self):
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "StreamServer")
        release = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_release_stale_modifiers")
        namespace["inject_key"] = Mock()
        exec(compile(ast.Module(body=[release], type_ignores=[]), str(SOURCE), "exec"), namespace)

        state = types.SimpleNamespace(pressed_keys={
            "AltLeft": ("Alt", {"alt": True}),
            "ShiftLeft": ("Shift", {"shift": True}),
            "KeyX": ("x", {"alt": True}),
        })
        namespace["_release_stale_modifiers"](object(), state)
        self.assertEqual(state.pressed_keys, {"KeyX": ("x", {"alt": True})})
        self.assertEqual(namespace["inject_key"].call_count, 2)
        self.assertTrue(all(call.args[2] is False for call in namespace["inject_key"].call_args_list))

    def test_key_injection_always_explicitly_sets_event_flags(self):
        inject = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "inject_key")
        source = ast.unparse(inject)
        self.assertIn("cg.CGEventSetFlags(ev, keyboard_event_flags(code, is_down, modifiers))", source)


if __name__ == "__main__":
    unittest.main()
