// PersonaHUD -- a small always-on-top avatar + name pinned to a corner of the terminal window.
//
// Why a separate window rather than anything terminal-native: every in-terminal channel either
// fails or isn't ours to take. Inline images die inside tmux (tmux's screen model tracks only text
// cells, so it loses the bitmap on the next repaint). iTerm2's badge is text-only. iTerm2's
// background image works, but it's a *user-owned setting* -- claiming it destroys whatever
// background the user configured and can't be restored faithfully. An overlay window is a surface
// we own outright: it consumes no terminal rows, touches no user configuration, and is unaffected
// by tmux, the shell, or which terminal emulator is in use.
//
// The window is non-activating and click-through, so it never steals focus or input, and it hides
// whenever iTerm2 isn't frontmost so it doesn't float over unrelated apps.

import Cocoa

struct Options {
    var imagePath = ""
    var name = ""
    var avatar: CGFloat = 104
    var corner = "tr"
    var margin: CGFloat = 16
    var ownerName = "iTerm2"
    // The tmux pane this persona belongs to. Several tmux windows share one iTerm2 window, so
    // "is iTerm2 frontmost" is not enough to decide whether to show: without this, every running
    // persona's overlay would sit on top of whichever tmux window happens to be visible.
    var tmuxPane = ""
    var tmuxBin = ""
}

func parseArgs() -> Options {
    var o = Options()
    var args = Array(CommandLine.arguments.dropFirst())
    while let flag = args.first {
        args.removeFirst()
        func value() -> String { args.isEmpty ? "" : args.removeFirst() }
        switch flag {
        case "--image": o.imagePath = value()
        case "--name": o.name = value()
        case "--avatar": o.avatar = CGFloat(Double(value()) ?? 104)
        case "--corner": o.corner = value()
        case "--margin": o.margin = CGFloat(Double(value()) ?? 16)
        case "--owner": o.ownerName = value()
        case "--tmux-pane": o.tmuxPane = value()
        case "--tmux-bin": o.tmuxBin = value()
        default: break
        }
    }
    return o
}

final class HUDView: NSView {
    let name: String
    let avatar: CGFloat

    /// The avatar is an NSImageView rather than a manual `image.draw(in:)` specifically so an
    /// animated GIF persona actually animates -- drawing an NSImage by hand only ever renders its
    /// first frame. Circular masking is done on the view's layer so it applies to every frame.
    init(image: NSImage?, name: String, avatar: CGFloat, size: NSSize) {
        self.name = name
        self.avatar = avatar
        super.init(frame: NSRect(origin: .zero, size: size))

        guard let image = image else { return }
        let box = NSRect(x: (size.width - avatar) / 2, y: size.height - avatar,
                         width: avatar, height: avatar)
        let imageView = NSImageView(frame: box)
        imageView.image = image
        imageView.animates = true
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.wantsLayer = true
        imageView.layer?.cornerRadius = avatar / 2
        imageView.layer?.masksToBounds = true
        imageView.layer?.borderWidth = 1.5
        imageView.layer?.borderColor = NSColor(white: 1, alpha: 0.55).cgColor
        addSubview(imageView)
    }

    required init?(coder: NSCoder) { fatalError() }

    override func draw(_ dirtyRect: NSRect) {
        let labelHeight: CGFloat = name.isEmpty ? 0 : 20
        guard !name.isEmpty else { return }
        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.9)
        shadow.shadowBlurRadius = 3
        shadow.shadowOffset = NSSize(width: 0, height: -1)
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12, weight: .semibold),
            .foregroundColor: NSColor.white,
            .shadow: shadow,
        ]
        let text = NSAttributedString(string: name, attributes: attrs)
        let size = text.size()
        text.draw(at: NSPoint(x: (bounds.width - size.width) / 2,
                              y: bounds.height - avatar - labelHeight + 4))
    }
}

final class Controller: NSObject {
    let opts: Options
    let panel: NSPanel
    let view: HUDView

    init(opts: Options) {
        self.opts = opts
        let image = opts.imagePath.isEmpty ? nil : NSImage(contentsOfFile: opts.imagePath)
        let labelHeight: CGFloat = opts.name.isEmpty ? 0 : 20
        let width = max(opts.avatar, 90)
        let height = opts.avatar + labelHeight

        view = HUDView(image: image, name: opts.name, avatar: opts.avatar,
                       size: NSSize(width: width, height: height))

        panel = NSPanel(contentRect: view.frame,
                        styleMask: [.borderless, .nonactivatingPanel],
                        backing: .buffered, defer: false)
        panel.contentView = view
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.ignoresMouseEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.hidesOnDeactivate = false
        super.init()
    }

    /// Frontmost normal window belonging to the terminal app, in Quartz (top-left origin) space.
    func terminalWindowFrame() -> CGRect? {
        let opt: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let list = CGWindowListCopyWindowInfo(opt, kCGNullWindowID) as? [[String: Any]]
        else { return nil }
        for info in list {
            guard (info[kCGWindowOwnerName as String] as? String) == opts.ownerName,
                  (info[kCGWindowLayer as String] as? Int) == 0,
                  let dict = info[kCGWindowBounds as String] as? [String: Any],
                  let rect = CGRect(dictionaryRepresentation: dict as CFDictionary),
                  rect.width > 200, rect.height > 120
            else { continue }
            return rect
        }
        return nil
    }

    /// Quartz coordinates are top-left origin; Cocoa window frames are bottom-left origin off the
    /// primary screen, so the y axis has to be flipped against that screen's height.
    func toCocoa(_ q: CGRect) -> CGRect {
        let primary = NSScreen.screens.first { $0.frame.origin == .zero } ?? NSScreen.main
        let h = primary?.frame.height ?? 0
        return CGRect(x: q.origin.x, y: h - q.origin.y - q.size.height,
                      width: q.size.width, height: q.size.height)
    }

    /// Whether this persona's tmux window is the one currently on screen. tmux multiplexes many
    /// windows into a single terminal window, so without asking tmux directly there's no way to
    /// tell that this persona's window has been switched away from -- the terminal app is still
    /// frontmost either way. Returns true when not running under tmux at all.
    func tmuxWindowIsVisible() -> Bool {
        guard !opts.tmuxPane.isEmpty, !opts.tmuxBin.isEmpty else { return true }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: opts.tmuxBin)
        process.arguments = [
            "display-message", "-pt", opts.tmuxPane, "#{window_active}#{session_attached}",
        ]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return false }
        process.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let out = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return out == "11"  // window is active in its session, and that session is attached
    }

    @objc func tick() {
        let frontmost = NSWorkspace.shared.frontmostApplication?.localizedName
        guard frontmost == opts.ownerName,
              tmuxWindowIsVisible(),
              let quartz = terminalWindowFrame()
        else {
            panel.orderOut(nil)
            return
        }
        let term = toCocoa(quartz)
        let s = panel.frame.size
        let m = opts.margin
        let x = opts.corner.hasSuffix("l") ? term.minX + m : term.maxX - s.width - m
        // top corners sit below the title bar, which the Quartz bounds include
        let y = opts.corner.hasPrefix("t") ? term.maxY - s.height - m - 28 : term.minY + m
        panel.setFrameOrigin(NSPoint(x: x, y: y))
        if !panel.isVisible { panel.orderFrontRegardless() }
    }

    func run() {
        let timer = Timer(timeInterval: 0.25, target: self, selector: #selector(tick),
                          userInfo: nil, repeats: true)
        RunLoop.main.add(timer, forMode: .common)
        tick()
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = Controller(opts: parseArgs())
controller.run()
app.run()
