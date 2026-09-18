import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const client = fs.readFileSync(new URL('../vendor/novnc/webrtc.html', import.meta.url), 'utf8');
const streamer = fs.readFileSync(new URL('../macos/fly-mac-streamer.py', import.meta.url), 'utf8');

test('native RDC maps platform copy/paste shortcuts to clipboard protocol', () => {
  assert.match(client, /CLIENT_IS_APPLE/);
  assert.match(client, /isPrimaryShortcut\(e, "c"\)/);
  assert.match(client, /type: "clipboard_pull"/);
  assert.match(client, /isPrimaryShortcut\(e, "v"\)/);
  assert.match(client, /clipboardSink\.addEventListener\("paste", handleNativePaste\)/);
  assert.match(client, /navigator\.clipboard\?\.writeText/);
});

test('native RDC streams pasted files to macOS in bounded chunks', () => {
  assert.match(client, /CLIPBOARD_CHUNK_BYTES = 48 \* 1024/);
  assert.match(client, /type: "clipboard_files_begin"/);
  assert.match(client, /type: "clipboard_files_chunk"/);
  assert.match(client, /type: "clipboard_files_end"/);
  assert.match(streamer, /CLIPBOARD_MAX_TOTAL_BYTES/);
  assert.match(streamer, /base64\.b64decode/);
  assert.match(streamer, /def set_file_clipboard/);
  assert.match(streamer, /NSPasteboard\.generalPasteboard/);
  assert.match(streamer, /inject_key\("KeyV", "v", True, \{"meta": True\}\)/);
});

test('native RDC pulls copied text from macOS back into the client clipboard', () => {
  assert.match(streamer, /def copy_remote_clipboard_text/);
  assert.match(streamer, /\["pbpaste"\]/);
  assert.match(streamer, /"type": "clipboard_snapshot"/);
  assert.match(client, /msg\.type === "clipboard_snapshot"/);
  assert.match(client, /writeLocalClipboardText/);
});
