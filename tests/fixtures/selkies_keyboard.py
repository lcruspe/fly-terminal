# Selkies keyboard source before ordered X11 patch; retained for regression tests.
class WebRTCInput:
    async def _keyboard_worker(self):
        unicode_buffer = []

        async def flush_buffer():
            if unicode_buffer:
                combined_text = "".join(unicode_buffer)
                unicode_buffer.clear()

                if self.is_wayland:
                    if getattr(self, 'use_clipboard_fallback', False):
                        await self._inject_unicode_via_clipboard(combined_text)
                    else:
                        try:
                            cmd = ["wtype", "--", combined_text]
                            proc = await subprocess.create_subprocess_exec(
                                *cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                env=self._get_wl_env()
                            )
                            await asyncio.wait_for(proc.communicate(), timeout=2.0)
                        except Exception as e:
                            logger_webrtc_input.warning(f"Batched wtype failed: {e}")
                else:
                    await self._fly_terminal_type_text_x11(combined_text)

        while True:
            try:
                if unicode_buffer:
                    try:
                        msg_type, data = await asyncio.wait_for(self.keyboard_queue.get(), timeout=0.05)
                    except asyncio.TimeoutError:
                        await flush_buffer()
                        continue
                else:
                    msg_type, data = await self.keyboard_queue.get()

                try:
                    keysym = data if msg_type in ("kd", "ku") else None
                    is_unicode_fallback = False
                    if keysym is not None:
                        is_unicode_fallback = (0xA0 <= keysym <= 0xFF) or keysym == 0x20AC or ((keysym & 0xFF000000) == 0x01000000)

                    if msg_type == "kd":
                        if is_unicode_fallback and not self.active_modifiers:
                            unicode_codepoint = keysym & 0x00FFFFFF if (keysym & 0xFF000000) == 0x01000000 else keysym
                            try:
                                char_to_type = chr(unicode_codepoint)
                                unicode_buffer.append(char_to_type)
                                continue
                            except ValueError:
                                pass
                        
                        if keysym == 65288 and unicode_buffer:
                            unicode_buffer.pop() 
                            continue
                            
                        await flush_buffer()
                        
                        if keysym in self.MODIFIER_KEYSYMS:
                            self.active_modifiers.add(keysym)
                        
                        await self.send_x11_keypress(keysym, down=True)

                    elif msg_type == "ku":
                        if is_unicode_fallback:
                            continue

                        if keysym in self.MODIFIER_KEYSYMS:
                            self.active_modifiers.discard(keysym)
                        if keysym in self.atomically_typed_keys:
                            self.atomically_typed_keys.discard(keysym)
                        else:
                            await self.send_x11_keypress(keysym, down=False)

                    elif msg_type == "kr":
                        await flush_buffer()
                        await self.reset_keyboard()

                    elif msg_type == "co_end":
                        unicode_buffer.append(data)

                    elif msg_type == "text":
                        unicode_buffer.append(data)

                finally:
                    self.keyboard_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger_webrtc_input.error(f"Error in keyboard worker: {e}", exc_info=True)

    async def on_message(self, msg: str, display_id='primary'):
        toks = msg.split(",")
        msg_type = toks[0]

        if msg_type == "pong":
            if self.ping_start is None: logger_webrtc_input.warning("received pong before ping"); return
            self.on_ping_response(float("%.3f" % ((time.time() - self.ping_start) / 2 * 1000)))
        elif msg_type == "kd":
            keysym = int(toks[1])
            if self.is_wayland:
                self.keyboard_queue.put_nowait(("kd", keysym))
            else:
                is_printable = (0x20 <= keysym <= 0xFF) or ((keysym & 0xFF000000) == 0x01000000)
                if keysym in self.MODIFIER_KEYSYMS:
                    self.active_modifiers.add(keysym)

                cyrillic_text = None
                if not (self.active_modifiers & self.ACTION_MODIFIER_KEYSYMS):
                    cyrillic_text = _fly_terminal_keysym_to_cyrillic_text(keysym)

                if cyrillic_text:
                    self.keyboard_queue.put_nowait(("text", cyrillic_text))
                    self.atomically_typed_keys.add(keysym)
                elif keysym == 65288:
                    self.keyboard_queue.put_nowait(("kd", keysym))
                elif is_printable and not self.active_modifiers:
                    unicode_codepoint = keysym & 0x00FFFFFF if (keysym & 0xFF000000) == 0x01000000 else keysym
                    try:
                        char_to_type = chr(unicode_codepoint)
                        if not char_to_type.isalpha() and char_to_type != ' ':
                            await self.on_message(f"co,end,{char_to_type}")
                            self.atomically_typed_keys.add(keysym)
                        else:
                            await self.send_x11_keypress(keysym, down=True)
                    except (ValueError, TypeError):
                        await self.send_x11_keypress(keysym, down=True)
                else:
                    await self.send_x11_keypress(keysym, down=True)
        elif msg_type == "ku":
            keysym = int(toks[1])
            if self.is_wayland:
                self.keyboard_queue.put_nowait(("ku", keysym))
            else:
                if keysym in self.MODIFIER_KEYSYMS:
                    self.active_modifiers.discard(keysym)
                if keysym in self.atomically_typed_keys:
                    self.atomically_typed_keys.discard(keysym)
                    pass
                elif keysym == 65288:
                    self.keyboard_queue.put_nowait(("ku", keysym))
                else:
                    await self.send_x11_keypress(keysym, down=False)
        elif msg_type == "kr":
            if self.is_wayland:
                self.keyboard_queue.put_nowait(("kr", None))
            else:
                await self.reset_keyboard()
        elif msg_type in ["m", "m2"]:
            pass
