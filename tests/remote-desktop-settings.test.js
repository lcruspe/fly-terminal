import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const settingsBlock = html.match(/<details class="settings" id="settingsMenu">[\s\S]*?<\/details>\s*<details class="settings tools-menu"/)?.[0] || '';
const toolsBlock = html.match(/<details class="settings tools-menu" id="toolsMenu">[\s\S]*?<\/details>\s*<details class="dropdown overflow-menu"/)?.[0] || '';

function panel(section) {
  return settingsBlock.match(new RegExp(`<section[^>]*data-settings-panel="${section}"[\\s\\S]*?<\\/section>`))?.[0] || '';
}

test('Settings uses three explicit navigation sections', () => {
  for (const section of ['appearance', 'workspace', 'remote']) {
    assert.match(settingsBlock, new RegExp(`data-settings-section="${section}"`));
    assert.match(settingsBlock, new RegExp(`data-settings-panel="${section}"`));
  }
  assert.match(settingsBlock, /role="tablist"[^>]*aria-label="Разделы настроек"/);
  assert.doesNotMatch(settingsBlock, /class="remote-desktop-settings"/);
});

test('preference controls are grouped by user intent', () => {
  for (const id of ['uiDensity', 'fontSize', 'fontFamily']) assert.match(panel('appearance'), new RegExp(`id="${id}"`));
  assert.match(panel('appearance'), /class="theme-grid"/);
  for (const id of ['toolbarOrientation', 'windowTitle']) assert.match(panel('workspace'), new RegExp(`id="${id}"`));
  for (const id of ['desktopMode', 'desktopResolution', 'desktopScaleMode', 'desktopFps']) assert.match(panel('remote'), new RegExp(`id="${id}"`));
});

test('display resolution operations live in Tools, not Settings', () => {
  assert.doesNotMatch(settingsBlock, /id="(?:main|virtual)DisplayResolution"/);
  assert.match(toolsBlock, /class="[^"]*tools-displays-section[^"]*"/);
  for (const id of ['mainDisplayResolution', 'virtualDisplayResolution']) {
    assert.match(toolsBlock, new RegExp(`id="${id}"`));
  }
});

test('Settings section controller exposes one active panel at a time', () => {
  assert.match(html, /function activateSettingsSection\(section\)/);
  assert.match(html, /button\.setAttribute\("aria-selected", String\(active\)\)/);
  assert.match(html, /settingsPanels\.forEach\(panel => panel\.hidden = panel\.dataset\.settingsPanel !== section\)/);
});

test('touch Settings navigation becomes a horizontal scrollable selector', () => {
  assert.match(html, /@media \(hover: none\), \(pointer: coarse\)[\s\S]*?\.settings-navigation\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(max-content, 1fr\)\)/);
  assert.match(html, /\.settings-navigation\s*\{[^}]*overflow-x:\s*auto/);
});

test('compact vertical toolbar hides only top-level Settings chevrons', () => {
  assert.match(html, /\.sidebar-compact \.settings > summary::after\s*\{\s*display:\s*none;/);
  assert.doesNotMatch(html, /\.sidebar-compact \.settings summary::after\s*\{\s*display:\s*none;/);
});


test('Tools uses explicit operation sections instead of one long column', () => {
  assert.match(toolsBlock, /role="tablist"[^>]*aria-label="Разделы инструментов"/);
  for (const section of ['vpn', 'files', 'displays', 'system']) {
    assert.match(toolsBlock, new RegExp(`data-tools-section="${section}"`));
    assert.match(toolsBlock, new RegExp(`data-tools-panel="${section}"`));
  }
});

test('Tools section controller exposes one operation panel at a time', () => {
  assert.match(html, /function activateToolsSection\(section\)/);
  assert.match(html, /toolsPanels\.forEach\(panel => panel\.hidden = panel\.dataset\.toolsPanel !== section\)/);
});
