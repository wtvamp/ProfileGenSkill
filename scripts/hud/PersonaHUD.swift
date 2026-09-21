// PersonaHUD -- a small always-on-top avatar + name floating over the terminal window.
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
    // Upper and lower bounds on the orb's diameter. The actual size is derived on every tick
    // from the area the overlay is pinned to (the tmux pane, or the whole terminal window when
    // not under tmux) -- see Controller.avatarSize(for:) -- so a narrow pane gets a smaller orb
    // than a wide one instead of every pane wearing the same fixed disc regardless of how much
    // of it that covers. `avatar` is therefore the size for a roomy pane, not *the* size.
    var avatar: CGFloat = 48
    var avatarMin: CGFloat = 26
    // Where in the pinned area the badge sits, as <vertical><horizontal>: "tc" (top centre, the
    // default), "c" (dead centre), or any of tl/tr/bl/br/bc. Horizontally centred is the default
    // because the corners are where the terminal's own furniture lives -- scrollbar, resize grip,
    // the tail of long output -- and a badge parked in one has nowhere to move when it collides
    // with that. The top edge is where a pane's output is oldest and least likely to be the line
    // being read, which is what makes it less intrusive than dead centre.
    var position = "tc"
    var margin: CGFloat = 16
    var ownerName = "iTerm2"
    // The tmux pane this persona belongs to. Several tmux windows share one iTerm2 window, so
    // "is iTerm2 frontmost" is not enough to decide whether to show: without this, every running
    // persona's overlay would sit on top of whichever tmux window happens to be visible.
    var tmuxPane = ""
    var tmuxBin = ""
    // The /dev/ttyNNN of the iTerm2 window this persona's session actually lives in. Several
    // iTerm2 windows can be open at once, each potentially running its own session/persona --
    // this is what lets terminalWindowFrame() pick the *right* one instead of just grabbing
    // whichever iTerm2 window happens to be frontmost/first in on-screen z-order.
    var tty = ""
    // The session this overlay belongs to. It runs detached so it survives the command that
    // started it, which also means nothing else would ever clean it up -- watching this pid is
    // what makes it disappear when the session exits, with no hook to configure.
    var watchPid: pid_t = 0
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
        case "--avatar": o.avatar = CGFloat(Double(value()) ?? 48)
        case "--avatar-min": o.avatarMin = CGFloat(Double(value()) ?? 26)
        // --corner is the old spelling, kept working so an existing invocation doesn't break.
        case "--position", "--corner": o.position = value()
        case "--margin": o.margin = CGFloat(Double(value()) ?? 16)
        case "--owner": o.ownerName = value()
        case "--tmux-pane": o.tmuxPane = value()
        case "--tmux-bin": o.tmuxBin = value()
        case "--tty": o.tty = value()
        case "--watch-pid": o.watchPid = pid_t(Int32(value()) ?? 0)
        default: break
        }
    }
    return o
}

/// The badge: a rounded-square picture tile and the persona's name, sitting together on a small
/// translucent card.
///
/// Three deliberate choices, all in service of "readable over arbitrary terminal output without
/// shouting":
///
///  - **A card behind everything.** Terminal output is high-contrast text in unpredictable
///    colours, and white text floating directly on it is illegible about half the time. The card
///    gives the name a consistent surface to sit on and makes the picture and the name read as one
///    object rather than two floating fragments. It's a blurred backdrop (`NSVisualEffectView`)
///    under a dark scrim: the blur keeps it from looking like a flat slab pasted over the
///    terminal, and the scrim is what stops it tinting -- vibrancy alone over a green diff hunk
///    turns the whole card olive, and the one thing this surface has to be is the same colour
///    every time, whatever it happens to be covering.
///  - **A rounded square, not a circle.** A square tile keeps the whole frame of the generated
///    portrait -- a circle crops the corners off a composition that was never framed for it -- and
///    it echoes the card's own rounded rectangle, so the two shapes agree. The radius is ~22% of
///    the side, the same ratio macOS uses for app icons, which reads as intentional where a sharp
///    square reads as unstyled. A picture that isn't square is *centre-cropped* to fill the tile,
///    never scaled to fit it: scaling a 16:9 portrait into a square visibly widens the face, and a
///    squashed persona is worse than a tightly framed one.
///  - **A strip, not a stack.** Name to the right of the tile, vertically centred against it: a
///    strip covers one or two lines of output where a stack covers several.
final class HUDView: NSView {
    let name: String
    private(set) var avatar: CGFloat
    private let imageView: NSImageView?
    /// The tile clips the picture; the picture itself is laid out *larger* than the tile on its
    /// long axis and centred, which is what crops a non-square portrait instead of squashing it.
    /// Clipping and scaling have to be two views to do that -- one view can only fit or stretch.
    private let tile = NSView()
    /// Width / height of the source picture, 1 when there isn't one.
    private let imageAspect: CGFloat
    private let label: NSTextField?
    private let shadowHost = NSView()
    private let backdrop = NSVisualEffectView()
    private let scrim = NSView()

    // Every measurement is a fraction of the tile's side, so the badge looks identical at any
    // size -- the overlay rescales itself to its pane, and proportions that only work at one size
    // would fall apart at the others.
    /// persona_hud.py carries the same five fractions, and tests/test_hud.py reads both files to
    /// check they still agree -- two implementations of one badge only look like one badge for as
    /// long as nobody tunes a number in a single place.
    static let tileRadiusFraction: CGFloat = 0.22
    static let paddingFraction: CGFloat = 0.13
    static let trailingPaddingFraction: CGFloat = 0.2
    static let gapFraction: CGFloat = 0.16
    static let fontFraction: CGFloat = 0.24

    static func padding(forAvatar avatar: CGFloat) -> CGFloat {
        max(5, (avatar * paddingFraction).rounded())
    }
    /// Trailing padding runs wider than the rest: text has its own optical sidebearing, so an
    /// equal measurement looks tight after the name.
    static func trailingPadding(forAvatar avatar: CGFloat) -> CGFloat {
        max(9, (avatar * trailingPaddingFraction).rounded())
    }
    static func gap(forAvatar avatar: CGFloat) -> CGFloat {
        max(6, (avatar * gapFraction).rounded())
    }
    static func tileRadius(forAvatar avatar: CGFloat) -> CGFloat {
        (avatar * tileRadiusFraction).rounded()
    }
    /// Concentric with the tile's corners: the card's radius is the tile's plus the padding
    /// between them, which is what makes the two curves stay parallel instead of the outer one
    /// bulging away from the inner. Picking the card's radius off its own height instead is what
    /// turns a short badge into a pill.
    static func cardRadius(forAvatar avatar: CGFloat) -> CGFloat {
        tileRadius(forAvatar: avatar) + padding(forAvatar: avatar)
    }

    static func fontSize(forAvatar avatar: CGFloat) -> CGFloat {
        max(10, (avatar * fontFraction).rounded())
    }

    static func font(forAvatar avatar: CGFloat) -> NSFont {
        NSFont.systemFont(ofSize: fontSize(forAvatar: avatar), weight: .semibold)
    }

    static func textSize(forAvatar avatar: CGFloat, name: String) -> NSSize {
        guard !name.isEmpty else { return .zero }
        let text = NSAttributedString(string: name, attributes: [.font: font(forAvatar: avatar)])
        let size = text.size()
        return NSSize(width: ceil(size.width), height: ceil(size.height))
    }

    /// Padding, tile, gap, the full name, trailing padding -- wide enough that a long name is
    /// never clipped.
    static func size(forAvatar avatar: CGFloat, name: String) -> NSSize {
        let pad = padding(forAvatar: avatar)
        var width = avatar + 2 * pad
        if !name.isEmpty {
            width = pad + avatar + gap(forAvatar: avatar)
                + textSize(forAvatar: avatar, name: name).width
                + trailingPadding(forAvatar: avatar)
        }
        return NSSize(width: width, height: avatar + 2 * pad)
    }

    /// The picture is an NSImageView rather than a manual `image.draw(in:)` specifically so an
    /// animated GIF persona actually animates -- drawing an NSImage by hand only ever renders its
    /// first frame. Rounding is done on the view's layer so it applies to every frame.
    init(image: NSImage?, name: String, avatar: CGFloat) {
        self.name = name
        self.avatar = avatar

        if let image = image {
            let imageView = NSImageView(frame: .zero)
            imageView.image = image
            imageView.animates = true
            // The frame place() gives this view already carries the picture's aspect ratio, so
            // filling it exactly is what preserves the proportions -- the crop comes from the
            // tile clipping the overflow, not from the scaling.
            imageView.imageScaling = .scaleAxesIndependently
            self.imageView = imageView
            let size = image.size
            imageAspect = size.height > 0 ? size.width / size.height : 1
        } else {
            self.imageView = nil
            imageAspect = 1
        }

        if name.isEmpty {
            self.label = nil
        } else {
            let field = NSTextField(labelWithString: name)
            field.textColor = .white
            field.isBezeled = false
            field.drawsBackground = false
            field.isEditable = false
            field.isSelectable = false
            // The card carries most of the legibility, but a card over a bright patch of output
            // is still bright -- the shadow is what keeps the name readable in that case.
            let shadow = NSShadow()
            shadow.shadowColor = NSColor.black.withAlphaComponent(0.65)
            shadow.shadowBlurRadius = 3
            shadow.shadowOffset = NSSize(width: 0, height: -1)
            field.shadow = shadow
            self.label = field
        }

        super.init(frame: NSRect(origin: .zero, size: Self.size(forAvatar: avatar, name: name)))

        // The card is built as a masked backdrop inside an unmasked host: the mask that rounds the
        // card's corners would clip its own shadow away if both lived on one layer.
        shadowHost.wantsLayer = true
        shadowHost.layer?.masksToBounds = false
        shadowHost.layer?.shadowColor = NSColor.black.cgColor
        shadowHost.layer?.shadowOpacity = 0.32
        shadowHost.layer?.shadowRadius = 8
        shadowHost.layer?.shadowOffset = CGSize(width: 0, height: -2)

        backdrop.material = .hudWindow
        backdrop.blendingMode = .behindWindow
        backdrop.state = .active
        backdrop.wantsLayer = true
        backdrop.layer?.masksToBounds = true
        backdrop.layer?.borderWidth = 1
        backdrop.layer?.borderColor = NSColor(white: 1, alpha: 0.16).cgColor

        scrim.wantsLayer = true
        scrim.layer?.backgroundColor = NSColor(white: 0.05, alpha: 0.74).cgColor

        backdrop.addSubview(scrim)
        tile.wantsLayer = true
        tile.layer?.masksToBounds = true
        // A hairline inner edge, not a ring: it separates the picture from the card without
        // becoming a feature of its own.
        tile.layer?.borderWidth = 1
        tile.layer?.borderColor = NSColor(white: 1, alpha: 0.22).cgColor

        shadowHost.addSubview(backdrop)
        addSubview(shadowHost)
        if let imageView = imageView {
            tile.addSubview(imageView)
            addSubview(tile)
        }
        if let label = label { addSubview(label) }
        place()
    }

    required init?(coder: NSCoder) { fatalError() }

    /// Re-fit everything to a new tile size. The controller calls this whenever the area the
    /// overlay is pinned to changes size (a pane split or resized, the window dragged smaller),
    /// so the badge follows the pane instead of staying one fixed size. Cheap: the image view
    /// rescales its own frames, nothing is re-decoded.
    func relayout(avatar: CGFloat) {
        guard avatar != self.avatar else { return }
        self.avatar = avatar
        setFrameSize(Self.size(forAvatar: avatar, name: name))
        place()
    }

    private func place() {
        let pad = Self.padding(forAvatar: avatar)
        let cardRadius = Self.cardRadius(forAvatar: avatar)

        shadowHost.frame = bounds
        backdrop.frame = bounds
        backdrop.layer?.cornerRadius = cardRadius
        // Inside the backdrop, so the card's own rounding clips it -- a separately rounded scrim
        // would show a hairline of un-scrimmed blur at the corners.
        scrim.frame = backdrop.bounds
        // An explicit path, so the shadow is the card's rounded silhouette rather than something
        // Core Animation has to derive from the blurred content every frame.
        shadowHost.layer?.shadowPath = CGPath(roundedRect: bounds,
                                              cornerWidth: cardRadius, cornerHeight: cardRadius,
                                              transform: nil)

        tile.frame = NSRect(x: pad, y: pad, width: avatar, height: avatar)
        tile.layer?.cornerRadius = Self.tileRadius(forAvatar: avatar)
        // Fill the tile on the short axis and overflow on the long one, centred: the tile's own
        // clipping then trims the overflow off both ends, which is a centre crop.
        var width = avatar, height = avatar
        if imageAspect >= 1 {
            width = (avatar * imageAspect).rounded()
        } else {
            height = (avatar / imageAspect).rounded()
        }
        imageView?.frame = NSRect(x: ((avatar - width) / 2).rounded(),
                                  y: ((avatar - height) / 2).rounded(),
                                  width: width, height: height)

        if let label = label {
            label.font = Self.font(forAvatar: avatar)
            label.sizeToFit()
            label.setFrameOrigin(NSPoint(x: pad + avatar + Self.gap(forAvatar: avatar),
                                         y: (bounds.height - label.frame.height) / 2))
        }
        needsDisplay = true
    }
}

final class Controller: NSObject {
    let opts: Options
    let panel: NSPanel
    let view: HUDView

    init(opts: Options) {
        self.opts = opts
        let image = opts.imagePath.isEmpty ? nil : NSImage(contentsOfFile: opts.imagePath)
        // Starts at the maximum; the first tick shrinks it to fit before it's ever shown.
        view = HUDView(image: image, name: opts.name, avatar: opts.avatar)

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

    /// Bounds of the specific iTerm2 window whose tty matches `opts.tty`, plus whether that window
    /// is the frontmost of iTerm2's *own* windows (index 1 of `windows`, which iTerm2 -- like most
    /// scriptable Cocoa apps -- returns in front-to-back order). Asking iTerm2 directly (rather
    /// than guessing from on-screen z-order) is what makes the bounds correct when more than one
    /// iTerm2 window is open. The frontmost flag matters separately: two iTerm2 windows can sit at
    /// nearly identical screen bounds (one maximized behind another), in which case "iTerm2 is the
    /// frontmost app" is true for both of their overlays at once -- only this flag tells an overlay
    /// whose window is actually occluded that it should hide rather than draw on top of the one
    /// that's really on screen.
    struct WindowLookup {
        var frame: CGRect
        var isFrontmost: Bool
    }

    func windowFrame(forTTY tty: String) -> WindowLookup? {
        guard !tty.isEmpty else { return nil }
        let escaped = tty.replacingOccurrences(of: "\\", with: "\\\\")
                          .replacingOccurrences(of: "\"", with: "\\\"")
        let source = """
        tell application "iTerm2"
            repeat with i from 1 to count of windows
                set w to item i of windows
                repeat with t in tabs of w
                    repeat with s in sessions of t
                        if (tty of s) as string is "\(escaped)" then
                            set b to bounds of w
                            return ((item 1 of b) as string) & "," & ((item 2 of b) as string) & "," & ((item 3 of b) as string) & "," & ((item 4 of b) as string) & "," & (i as string)
                        end if
                    end repeat
                end repeat
            end repeat
        end tell
        """
        guard let script = NSAppleScript(source: source) else { return nil }
        var errorInfo: NSDictionary?
        let result = script.executeAndReturnError(&errorInfo)
        guard errorInfo == nil, let str = result.stringValue else { return nil }
        let parts = str.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        guard parts.count == 5,
              let x1 = Double(parts[0]), let y1 = Double(parts[1]),
              let x2 = Double(parts[2]), let y2 = Double(parts[3]),
              let index = Int(parts[4])
        else { return nil }
        return WindowLookup(frame: CGRect(x: x1, y: y1, width: x2 - x1, height: y2 - y1),
                             isFrontmost: index == 1)
    }

    /// First on-screen window belonging to the terminal app, in Quartz (top-left origin) space.
    /// Used only when the tty lookup above isn't available (non-iTerm2 owner, tty unresolved, or
    /// the AppleScript call failed) -- picking "first in on-screen z-order" is a guess that's wrong
    /// the instant more than one such window is open, but it's the best fallback available then.
    func fallbackWindowFrame() -> CGRect? {
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

    /// Where this persona's pane sits, as fractions of the terminal window, plus whether it's on
    /// screen at all.
    ///
    /// Two separate things make this necessary. tmux multiplexes many *windows* into one terminal
    /// window, so the terminal being frontmost says nothing about whether this persona's window is
    /// the one displayed. And a window can be split into several *panes*, each potentially running
    /// its own agent with its own persona -- pinning every overlay to the terminal window's corner
    /// would stack them on top of each other. Positioning each overlay over its own pane is both
    /// unambiguous and what makes "which agent is in which pane" readable at a glance.
    struct PaneGeometry {
        var fx0: CGFloat, fy0: CGFloat, fx1: CGFloat, fy1: CGFloat
        var visible: Bool
    }

    func tmuxPaneGeometry() -> PaneGeometry? {
        guard !opts.tmuxPane.isEmpty, !opts.tmuxBin.isEmpty else { return nil }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: opts.tmuxBin)
        process.arguments = [
            "display-message", "-pt", opts.tmuxPane,
            "#{pane_left},#{pane_top},#{pane_right},#{pane_bottom},"
                + "#{window_width},#{window_height},#{window_active},#{session_attached}",
        ]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return PaneGeometry(fx0: 0, fy0: 0, fx1: 1, fy1: 1, visible: false) }
        process.waitUntilExit()

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let out = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let parts = out.split(separator: ",").map { Double($0) ?? -1 }
        guard parts.count == 8, !parts.contains(-1), parts[4] > 0, parts[5] > 0 else {
            return PaneGeometry(fx0: 0, fy0: 0, fx1: 1, fy1: 1, visible: false)
        }

        let cols = CGFloat(parts[4]), rows = CGFloat(parts[5])
        // pane_right/pane_bottom are inclusive cell indices, hence the +1 for the far edges.
        return PaneGeometry(
            fx0: CGFloat(parts[0]) / cols,
            fy0: CGFloat(parts[1]) / rows,
            fx1: (CGFloat(parts[2]) + 1) / cols,
            fy1: (CGFloat(parts[3]) + 1) / rows,
            visible: parts[6] == 1 && parts[7] == 1
        )
    }

    /// Rough height of the window's title bar, which the Quartz window bounds include but the
    /// terminal's text area does not.
    static let titleBarHeight: CGFloat = 28

    /// The orb is sized off the pinned area's *width* first: what a too-big orb costs is the text
    /// it covers, and text runs horizontally, so a third-width pane wants a third-width orb even
    /// when it's as tall as the window. (Sizing off the shorter side was tried first and never
    /// bit -- a 480 pt-wide, 540 pt-tall pane still capped out at the maximum.) At 5% a
    /// half-width pane in a ~1500 pt window lands at the 48 pt default, a third-width pane gets
    /// ~33 pt, and a sidebar drops to the floor. The height term only matters for short, wide
    /// panes (a bottom split a dozen rows tall), where the badge would otherwise eat most of the
    /// pane. Both are the *tile's* side, not the card's -- the card adds its padding on top, so
    /// the fractions are set a little under what the finished badge is allowed to cover. Clamped
    /// to `[avatarMin, avatar]`.
    static let avatarWidthFraction: CGFloat = 0.05
    static let avatarHeightFraction: CGFloat = 0.15

    func avatarSize(for target: CGRect) -> CGFloat {
        let wanted = min(target.width * Self.avatarWidthFraction,
                         target.height * Self.avatarHeightFraction)
        return min(opts.avatar, max(opts.avatarMin, wanted)).rounded()
    }

    /// Whether the session that owns this overlay is still running. `kill(pid, 0)` sends no
    /// signal -- it only reports whether the process can be signalled, i.e. whether it exists.
    func ownerAlive() -> Bool {
        guard opts.watchPid > 0 else { return true }
        if kill(opts.watchPid, 0) == 0 { return true }
        return errno == EPERM  // exists, but not ours to signal
    }

    @objc func tick() {
        guard ownerAlive() else {
            NSApp.terminate(nil)
            return
        }
        let frontmostApp = NSWorkspace.shared.frontmostApplication?.localizedName
        guard frontmostApp == opts.ownerName else {
            panel.orderOut(nil)
            return
        }

        let quartz: CGRect
        if opts.ownerName == "iTerm2", let lookup = windowFrame(forTTY: opts.tty) {
            // Two iTerm2 windows can occupy nearly identical screen bounds (one maximized behind
            // another) -- "iTerm2 is frontmost" alone can't tell those apart, only this can.
            guard lookup.isFrontmost else {
                panel.orderOut(nil)
                return
            }
            quartz = lookup.frame
        } else if let fallback = fallbackWindowFrame() {
            quartz = fallback
        } else {
            panel.orderOut(nil)
            return
        }

        let term = toCocoa(quartz)
        let content = CGRect(x: term.minX, y: term.minY,
                             width: term.width, height: term.height - Self.titleBarHeight)

        // Default target is the whole terminal window; under tmux, narrow it to this pane.
        var target = content
        if let pane = tmuxPaneGeometry() {
            guard pane.visible else {
                panel.orderOut(nil)
                return
            }
            // Cell fractions are measured from the top; Cocoa's y axis runs the other way.
            target = CGRect(
                x: content.minX + pane.fx0 * content.width,
                y: content.maxY - pane.fy1 * content.height,
                width: (pane.fx1 - pane.fx0) * content.width,
                height: (pane.fy1 - pane.fy0) * content.height)
        }

        // Size to the pane (or window) before placing, so the corner offset uses the new size.
        let avatar = avatarSize(for: target)
        if avatar != view.avatar {
            view.relayout(avatar: avatar)
            panel.setContentSize(view.frame.size)
        }

        // Each axis is independently either centred in the target or inset from one of its edges.
        // The inset scales with the orb: a 36 pt margin that looks right around a full-size orb
        // leaves a shrunken one floating away from the edge it's supposed to hug. A centred axis
        // ignores the margin entirely -- there's no edge to inset from.
        let s = panel.frame.size
        let m = max(8, (opts.margin * avatar / max(opts.avatar, 1)).rounded())
        let x: CGFloat
        switch opts.position.last {
        case "l": x = target.minX + m
        case "r": x = target.maxX - s.width - m
        default: x = target.midX - s.width / 2
        }
        let y: CGFloat
        switch opts.position.count > 1 ? opts.position.first : nil {
        case "t": y = target.maxY - s.height - m
        case "b": y = target.minY + m
        default: y = target.midY - s.height / 2
        }
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
