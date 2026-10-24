// Control existing AmneziaVPN profiles via the app's macOS Accessibility UI.
// Never inspect/export VPN configuration, subscription URLs, keys, or passwords.
import AppKit
import ApplicationServices
import CryptoKit
import Foundation

struct Profile: Encodable { let id: String; let label: String }
struct Catalog: Encodable {
    let profiles: [Profile]
    let current: String
    let currentProfileId: String
    let state: String
}
struct Row { let id: String; let label: String; let element: AXUIElement }

func fail(_ code: String) -> Never {
    fputs(code + "\n", stderr)
    exit(1)
}
func attr(_ e: AXUIElement, _ key: CFString) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, key, &value) == .success ? value : nil
}
func name(_ e: AXUIElement, _ key: CFString = kAXTitleAttribute as CFString) -> String {
    return attr(e, key) as? String ?? ""
}
func children(_ e: AXUIElement) -> [AXUIElement] {
    return attr(e, kAXChildrenAttribute as CFString) as? [AXUIElement] ?? []
}
func role(_ e: AXUIElement) -> String { name(e, kAXRoleAttribute as CFString) }
func walk(_ e: AXUIElement, depth: Int = 0, _ action: (AXUIElement) -> Void) {
    guard depth < 8 else { return }
    action(e)
    for child in children(e) { walk(child, depth: depth + 1, action) }
}
func profileId(_ index: Int, _ label: String) -> String {
    SHA256.hash(data: Data("\(index):\(label)".utf8)).map { String(format: "%02x", $0) }.joined()
}
func window(_ app: AXUIElement) -> AXUIElement {
    guard let windows = attr(app, kAXWindowsAttribute as CFString) as? [AXUIElement],
          let win = windows.first(where: { name($0) == "AmneziaVPN" }) ?? windows.first else {
        fail("amnezia_window_unavailable")
    }
    return win
}
func homeButtons(_ win: AXUIElement) -> [AXUIElement] {
    guard let group = children(win).first(where: { role($0) == "AXGroup" }) else { return [] }
    return children(group).filter { role($0) == "AXButton" }
}
func currentHome(_ win: AXUIElement) -> String {
    let buttons = homeButtons(win)
    // AmneziaVPN 5.0.3 home screen: status, split-tunneling, auxiliary,
    // selected server, protocol. We verify its shape before using the index.
    guard buttons.count >= 5,
          ["Connected", "Disconnected", "Connecting", "Disconnecting", "Error"].contains(name(buttons[0])) else { return "" }
    return name(buttons[3])
}
func rows(_ win: AXUIElement) -> [Row] {
    var found: [Row] = []
    walk(win) { element in
        guard role(element) == "AXRadioButton",
              name(element, "AXIdentifier" as CFString).contains("tabBarStackView"),
              name(element, "AXIdentifier" as CFString).contains("VerticalRadioButton"),
              !name(element).isEmpty else { return }
        let title = name(element)
        found.append(Row(id: profileId(found.count, title), label: title, element: element))
    }
    return found
}
func menuItem(_ app: AXUIElement, _ titles: Set<String>) -> AXUIElement? {
    var result: AXUIElement?
    // The tray menu is exposed as a separate AXMenuBar below the app window.
    for bar in children(app) where role(bar) == "AXMenuBar" {
        walk(bar) { item in
            if role(item) == "AXMenuItem" && titles.contains(name(item)) { result = item }
        }
    }
    return result
}
func enabled(_ item: AXUIElement?) -> Bool {
    guard let item, let number = attr(item, kAXEnabledAttribute as CFString) as? NSNumber else { return false }
    return number.boolValue
}
func vpnState(_ app: AXUIElement) -> String {
    if enabled(menuItem(app, ["Disconnect", "Отключить"])) { return "Connected" }
    if enabled(menuItem(app, ["Connect", "Подключить"])) { return "Disconnected" }
    let buttons = homeButtons(window(app))
    if let first = buttons.first, !name(first).isEmpty { return name(first) }
    return "Unknown"
}
func press(_ element: AXUIElement, error: String) {
    guard AXUIElementPerformAction(element, kAXPressAction as CFString) == .success else { fail(error) }
}
func pressMenu(_ app: AXUIElement, names: Set<String>, error: String) {
    guard let item = menuItem(app, names), enabled(item) else { fail(error) }
    press(item, error: error)
}
func waitState(_ app: AXUIElement, _ desired: String, timeout: TimeInterval) -> Bool {
    let end = Date().addingTimeInterval(timeout)
    repeat {
        if vpnState(app) == desired { return true }
        Thread.sleep(forTimeInterval: 0.25)
    } while Date() < end
    return false
}
func pressEscapeAndRestore(_ app: NSRunningApplication) {
    // Qt's profile picker is dismissed with Escape. Restore the foreground app
    // so catalog reads do not leave AmneziaVPN stealing the user's keyboard.
    let previous = NSWorkspace.shared.frontmostApplication
    if previous?.processIdentifier != app.processIdentifier {
        _ = app.activate(options: [])
        Thread.sleep(forTimeInterval: 0.2)
    }
    if let down = CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: true),
       let up = CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: false) {
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
    }
    Thread.sleep(forTimeInterval: 0.1)
    if let previous, previous.processIdentifier != app.processIdentifier {
        _ = previous.activate(options: [])
    }
}
func profiles(_ app: AXUIElement, running: NSRunningApplication) -> (rows: [Row], current: String) {
    var win = window(app)
    var current = currentHome(win)
    if current.isEmpty && !rows(win).isEmpty {
        pressEscapeAndRestore(running)
        Thread.sleep(forTimeInterval: 0.15)
        win = window(app)
        current = currentHome(win)
    }
    var choices = rows(win)
    if choices.isEmpty {
        let buttons = homeButtons(win)
        guard buttons.count >= 5, !current.isEmpty else { fail("amnezia_profiles_unavailable") }
        press(buttons[3], error: "amnezia_profiles_unavailable")
        for _ in 0..<20 {
            Thread.sleep(forTimeInterval: 0.1)
            choices = rows(win)
            if !choices.isEmpty { break }
        }
    }
    guard !choices.isEmpty else { fail("amnezia_profiles_unavailable") }
    return (choices, current)
}
func catalog(_ app: AXUIElement, running: NSRunningApplication) -> Catalog {
    let status = vpnState(app)
    let result = profiles(app, running: running)
    pressEscapeAndRestore(running)
    let ids = result.rows.filter { $0.label == result.current }
    return Catalog(
        profiles: result.rows.map { Profile(id: $0.id, label: $0.label) },
        current: result.current,
        currentProfileId: ids.count == 1 ? ids[0].id : "",
        state: status
    )
}
func select(_ app: AXUIElement, running: NSRunningApplication, id: String) -> Catalog {
    let initial = profiles(app, running: running)
    guard let target = initial.rows.first(where: { $0.id == id }) else { fail("amnezia_profile_not_found") }
    let status = vpnState(app)
    if initial.current == target.label && status == "Connected" {
        pressEscapeAndRestore(running)
        return Catalog(profiles: initial.rows.map { Profile(id: $0.id, label: $0.label) },
                       current: target.label, currentProfileId: id, state: status)
    }
    // A connected AmneziaVPN cannot change its active server directly. Only
    // explicit POST is allowed to disconnect / choose / connect.
    if status == "Connected" {
        pressMenu(app, names: ["Disconnect", "Отключить"], error: "amnezia_disconnect_failed")
        guard waitState(app, "Disconnected", timeout: 15) else { fail("amnezia_disconnect_timeout") }
    } else if status != "Disconnected" {
        fail("amnezia_state_unavailable")
    }
    if initial.current != target.label || initial.current.isEmpty {
        // Disconnect may rebuild Qt's accessibility tree. Never press a stale row.
        let refreshed = profiles(app, running: running)
        guard let freshTarget = refreshed.rows.first(where: { $0.id == id }) else {
            fail("amnezia_profile_not_found")
        }
        press(freshTarget.element, error: "amnezia_select_failed")
        let end = Date().addingTimeInterval(5)
        while currentHome(window(app)) != target.label && Date() < end {
            Thread.sleep(forTimeInterval: 0.2)
        }
        guard currentHome(window(app)) == target.label else {
            // Preserve connectivity on failure where possible by reconnecting
            // the existing selected profile, rather than claiming success.
            if vpnState(app) == "Disconnected" {
                _ = menuItem(app, ["Connect", "Подключить"]).map {
                    AXUIElementPerformAction($0, kAXPressAction as CFString)
                }
            }
            fail("amnezia_selection_unconfirmed")
        }
    } else {
        pressEscapeAndRestore(running)
    }
    if vpnState(app) == "Disconnected" {
        pressMenu(app, names: ["Connect", "Подключить"], error: "amnezia_connect_failed")
    }
    guard waitState(app, "Connected", timeout: 30) else { fail("amnezia_connect_timeout") }
    return Catalog(profiles: initial.rows.map { Profile(id: $0.id, label: $0.label) },
                   current: target.label, currentProfileId: id, state: "Connected")
}

if let session = CGSessionCopyCurrentDictionary() as? [String: Any],
   let locked = session["CGSSessionScreenIsLocked"] as? NSNumber, locked.boolValue {
    fail("amnezia_screen_locked")
}
guard AXIsProcessTrusted() else { fail("amnezia_accessibility_denied") }
guard let running = NSWorkspace.shared.runningApplications.first(where: {
    $0.bundleIdentifier == "com.yourcompany.AmneziaVPN"
}) else { fail("amnezia_not_running") }
let app = AXUIElementCreateApplication(running.processIdentifier)
guard CommandLine.arguments.count >= 2 else { fail("amnezia_invalid_action") }
let result: Catalog
switch CommandLine.arguments[1] {
case "list": result = catalog(app, running: running)
case "select":
    guard CommandLine.arguments.count == 3 else { fail("amnezia_invalid_action") }
    result = select(app, running: running, id: CommandLine.arguments[2])
case "status":
    let current = currentHome(window(app))
    result = Catalog(profiles: [], current: current, currentProfileId: "", state: vpnState(app))
default: fail("amnezia_invalid_action")
}
do {
    let data = try JSONEncoder().encode(result)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
} catch { fail("amnezia_ax_unavailable") }
