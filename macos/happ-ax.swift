// Read and select servers in the installed macOS Happ Plus app via Accessibility.
// Only documented AX attributes/actions are used; subscription credentials are never read.
import AppKit
import ApplicationServices
import CryptoKit
import Foundation

struct Location: Encodable {
    let id: String
    let label: String
}
struct Subscription: Encodable {
    let id: String
    let label: String
    let locations: [Location]
}
struct Catalog: Encodable {
    let subscriptions: [Subscription]
    let current: String
    let currentSubscription: String
    let currentSubscriptionId: String
    let currentLocationId: String
}
struct ServerRow {
    let id: String
    let label: String
    let selected: Bool
    let element: AXUIElement
}
struct Group {
    let id: String
    let label: String
    let rows: [ServerRow]
}

func axAttribute(_ item: AXUIElement, _ key: CFString) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(item, key, &value) == .success else { return nil }
    return value
}
func axString(_ item: AXUIElement, _ key: CFString) -> String {
    axAttribute(item, key) as? String ?? ""
}
func axChildren(_ item: AXUIElement) -> [AXUIElement] {
    axAttribute(item, kAXChildrenAttribute as CFString) as? [AXUIElement] ?? []
}
func axActions(_ item: AXUIElement) -> [String] {
    var actions: CFArray?
    guard AXUIElementCopyActionNames(item, &actions) == .success else { return [] }
    return actions as? [String] ?? []
}
func stableId(_ text: String) -> String {
    let bytes = SHA256.hash(data: Data(text.utf8))
    return bytes.map { String(format: "%02x", $0) }.joined()
}

func walk(_ item: AXUIElement, depth: Int = 0, _ visit: (AXUIElement) -> Void) {
    guard depth < 35 else { return }
    visit(item)
    for child in axChildren(item) {
        walk(child, depth: depth + 1, visit)
    }
}
func extractRows(_ subscription: AXUIElement, groupId: String) -> [ServerRow] {
    var rows = [ServerRow]()
    walk(subscription) { element in
        let actions = axActions(element)
        guard actions.contains(kAXPressAction as String),
              actions.contains(where: { $0.contains("Выбрать сервер") || $0.contains("Select server") })
        else { return }
        var description = axString(element, kAXDescriptionAttribute as CFString)
        let selectedPrefix = description.hasPrefix("selected, ")
        let selectedSuffix = description.hasSuffix(", selected")
        let selected = (axAttribute(element, kAXSelectedAttribute as CFString) as? Bool ?? false)
            || selectedPrefix || selectedSuffix
        if selectedPrefix { description.removeFirst("selected, ".count) }
        if selectedSuffix { description.removeLast(", selected".count) }
        let name = String(description.components(separatedBy: ", ").first ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        let id = stableId("\(groupId):\(rows.count):\(name)")
        rows.append(ServerRow(id: id, label: name, selected: selected, element: element))
    }
    return rows
}
func readGroups() throws -> [Group] {
    guard AXIsProcessTrusted() else {
        throw NSError(domain: "happ_accessibility_denied", code: 3)
    }
    guard let app = NSWorkspace.shared.runningApplications.first(where: {
        $0.bundleIdentifier == "su.ffg.happ.plus"
    }) else {
        throw NSError(domain: "happ_not_running", code: 4)
    }
    let application = AXUIElementCreateApplication(app.processIdentifier)
    guard let windows = axAttribute(application, kAXWindowsAttribute as CFString) as? [AXUIElement],
          let window = windows.first(where: { axString($0, kAXTitleAttribute as CFString) == "Happ Plus" }) ?? windows.first
    else {
        throw NSError(domain: "happ_window_unavailable", code: 5)
    }
    var groups = [Group]()
    walk(window) { element in
        let description = axString(element, kAXDescriptionAttribute as CFString)
        guard description.hasPrefix("subscription: ") else { return }
        let name = String(description.dropFirst("subscription: ".count))
        let id = stableId("\(groups.count):\(name)")
        let rows = extractRows(element, groupId: id)
        if !rows.isEmpty { groups.append(Group(id: id, label: name, rows: rows)) }
    }
    guard !groups.isEmpty else {
        throw NSError(domain: "happ_servers_unavailable", code: 6)
    }
    return groups
}
func encode<T: Encodable>(_ value: T) throws {
    let data = try JSONEncoder().encode(value)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}
func catalog(_ groups: [Group]) -> Catalog {
    var current = ""
    var subscription = ""
    var subId = ""
    var locId = ""
    for group in groups {
        for row in group.rows where row.selected {
            current = row.label
            subscription = group.label
            subId = group.id
            locId = row.id
        }
    }
    return Catalog(
        subscriptions: groups.map { group in
            Subscription(id: group.id, label: group.label,
                         locations: group.rows.map { Location(id: $0.id, label: $0.label) })
        },
        current: current, currentSubscription: subscription,
        currentSubscriptionId: subId, currentLocationId: locId
    )
}

do {
    let args = Array(CommandLine.arguments.dropFirst())
    guard let command = args.first, ["list", "select"].contains(command) else {
        throw NSError(domain: "invalid_command", code: 2)
    }
    let groups = try readGroups()
    if command == "list" {
        try encode(catalog(groups))
    } else {
        guard args.count == 3,
              let group = groups.first(where: { $0.id == args[1] }),
              let row = group.rows.first(where: { $0.id == args[2] })
        else {
            throw NSError(domain: "happ_location_not_found", code: 7)
        }
        // AXPress invokes Happ's own "Выбрать сервер" UI action.
        // No direct modification of its preferences, cache, or tunnel.
        if !row.selected {
            let result = AXUIElementPerformAction(row.element, kAXPressAction as CFString)
            guard result == .success else {
                throw NSError(domain: "happ_ax_press_failed", code: Int(result.rawValue))
            }
        }
        try encode(["ok": true])
    }
} catch {
    fputs("\(error)\n", stderr)
    exit(1)
}
