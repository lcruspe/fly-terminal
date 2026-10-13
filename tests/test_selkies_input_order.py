"""Exercise the deployed Selkies worker with deliberately slow text injection."""
import ast
import asyncio
import unittest
from pathlib import Path
from tools.patch_selkies_xtest import patch_ordered_x11_input


class InputOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_spaces_shortcuts_and_backspace_keep_arrival_order(self):
        path = Path(__file__).parent / 'fixtures' / 'selkies_keyboard.py'
        source, _ = patch_ordered_x11_input(path.read_text())
        self.assertEqual(patch_ordered_x11_input(source), (source, False))
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WebRTCInput')
        methods = [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name in ('on_message', '_keyboard_worker')]
        namespace = dict(asyncio=asyncio, logger_webrtc_input=__import__('logging').getLogger(),
                         _fly_terminal_keysym_to_cyrillic_text=lambda k: chr(k & 0xffffff) if k > 0x1000000 else None)
        exec(compile(ast.Module(body=methods, type_ignores=[]), '<live-worker>', 'exec'), namespace)
        class Handler:
            is_wayland = False
            MODIFIER_KEYSYMS = {65507}
            ACTION_MODIFIER_KEYSYMS = {65507}
            def __init__(self):
                self.keyboard_queue = asyncio.Queue()
                self.active_modifiers = set()
                self.atomically_typed_keys = set()
                self.events = []
            async def _fly_terminal_type_text_x11(self, text):
                await asyncio.sleep(.03)
                self.events.extend(text)
            async def send_x11_keypress(self, key, down):
                self.events.append((key, down))
            async def reset_keyboard(self):
                self.events.append('reset')
        Handler.on_message = namespace['on_message']
        Handler._keyboard_worker = namespace['_keyboard_worker']
        h = Handler()
        task = asyncio.create_task(h._keyboard_worker())
        phrase = 'нужен код для VBA модуля, который выгрузит в отдельный файл '
        for char in phrase:
            key = ord(char) if ord(char) < 256 else 0x1000000 | ord(char)
            await h.on_message(f'kd,{key}')
            await h.on_message(f'ku,{key}')
            await asyncio.sleep(.001)
        await h.on_message('kd,65288')
        await h.on_message('ku,65288')
        await h.on_message('kd,65507')
        await h.on_message('kd,97')
        await h.on_message('ku,97')
        await h.on_message('ku,65507')
        await h.on_message('kr')
        await asyncio.wait_for(h.keyboard_queue.join(), 3)
        task.cancel()
        await task
        self.assertEqual(h.events, list(phrase) + [(65288, True), (65288, False), (65507, True), (97, True), (97, False), (65507, False)] + ['reset'])
