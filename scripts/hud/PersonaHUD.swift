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
    // 0 is the session's own badge; an agent-team member's badge sits in slot 1, 2, ... -- stacked
    // away from the edge the badges hug, so a team sharing one terminal shows every member at once.
    var slot = 0
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
        case "--slot": o.slot = max(0, Int(value()) ?? 0)
        // Identifies this overlay to hud.py's stop(), which finds it by command line; unused here.
        case "--hud-id": _ = value()
        default: break
        }
    }
    return o
}

/// Rebuilds where each split pane of an iTerm2 tab sits, from nothing but the panes' sizes.
///
/// iTerm2's AppleScript gives each session its `columns` and `rows`, in the depth-first order of
/// the tab's split tree, but no position -- and the Python API that does report frames needs a
/// websocket client, protobuf and an auth cookie. The sizes are enough, though: iTerm2 splits a
/// tab as a guillotine tree, where side-by-side siblings share one height and stacked siblings
/// share one width, so the depth-first order plus those equalities pins the tree down. Each pane
/// also carries its own title bar once a tab is split (about one row). Where both orientations fit
/// at the root (two equal panes, say), the window's shape picks the one that implies a plausible
/// cell shape. Returns nil when no tree fits, and the caller stacks badges instead of guessing.
enum SplitLayout {
    struct Node {
        var w: CGFloat, h: CGFloat
        var leaves: [CGRect]  // in cells, top-left origin, relative to this node
    }

    static let titleRows: CGFloat = 1
    static let dividerCols: CGFloat = 1
    /// A typical terminal cell's width over its height (Menlo/SF Mono at common sizes: 0.43-0.5).
    static let cellAspect: CGFloat = 0.47

    static func close(_ a: CGFloat, _ b: CGFloat) -> Bool {
        abs(a - b) <= max(2, 0.08 * max(a, b))
    }

    /// Each pane's rectangle as fractions of the tab's area (top-left origin), in input order.
    static func solve(_ sizes: [(cols: Int, rows: Int)], window: CGSize) -> [CGRect]? {
        guard !sizes.isEmpty else { return nil }
        if sizes.count == 1 { return [CGRect(x: 0, y: 0, width: 1, height: 1)] }
        let leaves = sizes.map { Node(w: CGFloat($0.cols), h: CGFloat($0.rows) + titleRows,
                                      leaves: [CGRect(x: 0, y: 0, width: CGFloat($0.cols),
                                                      height: CGFloat($0.rows) + titleRows)]) }
        var memo: [String: Node?] = [:]

        // A splitter over leaves i...j: `sideBySide` true means its children sit left to right.
        func node(_ i: Int, _ j: Int, _ sideBySide: Bool) -> Node? {
            let key = "\(i),\(j),\(sideBySide)"
            if let hit = memo[key] { return hit }
            var found: Node? = nil
            outer: for m in i..<j {
                guard let first = child(i, m, sideBySide) else { continue }
                // The rest is either more siblings of this same splitter, or the last child.
                for rest in [m + 1 < j ? node(m + 1, j, sideBySide) : nil, child(m + 1, j, sideBySide)] {
                    guard let rest = rest, let joined = join(first, rest, sideBySide) else { continue }
                    found = joined
                    break outer
                }
            }
            memo[key] = found
            return found
        }

        func child(_ i: Int, _ j: Int, _ parentSideBySide: Bool) -> Node? {
            i == j ? leaves[i] : node(i, j, !parentSideBySide)
        }

        func join(_ a: Node, _ b: Node, _ sideBySide: Bool) -> Node? {
            if sideBySide {
                guard close(a.h, b.h) else { return nil }
                let dx = a.w + dividerCols
                return Node(w: dx + b.w, h: max(a.h, b.h),
                            leaves: a.leaves + b.leaves.map { $0.offsetBy(dx: dx, dy: 0) })
            }
            guard close(a.w, b.w) else { return nil }
            return Node(w: max(a.w, b.w), h: a.h + b.h,
                        leaves: a.leaves + b.leaves.map { $0.offsetBy(dx: 0, dy: a.h) })
        }

        let n = sizes.count - 1
        let fits = [node(0, n, true), node(0, n, false)].compactMap { $0 }
        guard !fits.isEmpty, window.width > 0, window.height > 0 else { return nil }
        // The cell shape each candidate implies for this window; the plausible one wins.
        func misfit(_ root: Node) -> CGFloat {
            let implied = (window.width / root.w) / (window.height / root.h)
            return abs(log(implied / cellAspect))
        }
        let root = fits.min { misfit($0) < misfit($1) }!
        return root.leaves.map {
            CGRect(x: $0.minX / root.w, y: $0.minY / root.h,
                   width: $0.width / root.w, height: $0.height / root.h)
        }
    }
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
    // The tmux client tty this overlay is pinned to: starts as --tty, then follows focus. See
    // currentTTY().
    var tty: String
    var ttyCheckedAt = Date.distantPast

    init(opts: Options) {
        self.opts = opts
        tty = opts.tty
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
        /// Which of its tab's split panes this session is (0-based, in iTerm2's own order), and the
        /// size of every pane in that tab -- what SplitLayout.solve() rebuilds the split from.
        var paneIndex = 0
        var paneSizes: [(cols: Int, rows: Int)] = []
        /// Whether the tab holding this session is the one its window is showing. A window's other
        /// tabs share its bounds, so without this a background tab's badge draws over this one.
        var tabVisible = true
    }

    /// Under tmux, the tty of the client the user is looking at, re-asked about once a second.
    ///
    /// Several tmux clients can be attached to the same session from different iTerm2 windows (a
    /// stale `tmux attach` left in a background window, say), and the one the user is looking at
    /// changes as they switch windows -- so the --tty resolved at launch goes stale. Same choice
    /// as hud.py's _pick_client(): the focused client, else the most recently active one. Keeps
    /// the last answer when tmux can't be asked.
    func currentTTY() -> String {
        guard !opts.tmuxPane.isEmpty, !opts.tmuxBin.isEmpty,
              Date().timeIntervalSince(ttyCheckedAt) >= 1 else { return tty }
        ttyCheckedAt = Date()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: opts.tmuxBin)
        process.arguments = ["list-clients", "-t", opts.tmuxPane,
                             "-F", "#{client_flags} #{client_activity} #{client_tty}"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return tty }
        process.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        var best: (Int, Int)? = nil
        for line in (String(data: data, encoding: .utf8) ?? "").split(separator: "\n") {
            let parts = line.split(separator: " ")
            guard parts.count == 3, let activity = Int(parts[1]) else { continue }
            let rank = (parts[0].split(separator: ",").contains("focused") ? 1 : 0, activity)
            if best == nil || rank > best! {
                best = rank
                tty = String(parts[2])
            }
        }
        return tty
    }

    func windowFrame(forTTY tty: String) -> WindowLookup? {
        guard !tty.isEmpty else { return nil }
        let escaped = tty.replacingOccurrences(of: "\\", with: "\\\\")
                          .replacingOccurrences(of: "\"", with: "\\\"")
        // Returns "x1,y1,x2,y2,windowIndex,paneIndex;CxR;CxR;...;tabIsCurrent". iTerm2's tabs have
        // no gettable id or index, so "is this the current tab" is asked as "is the current tab's
        // current session one of this tab's sessions".
        let source = """
        tell application "iTerm2"
            repeat with i from 1 to count of windows
                set w to item i of windows
                set ts to tabs of w
                repeat with j from 1 to count of ts
                    set ss to sessions of (item j of ts)
                    repeat with k from 1 to count of ss
                        if (tty of (item k of ss)) as string is "\(escaped)" then
                            set b to bounds of w
                            set curTTY to (tty of current session of current tab of w) as string
                            set cur to false
                            set out to ((item 1 of b) as string) & "," & ((item 2 of b) as string) & "," & ((item 3 of b) as string) & "," & ((item 4 of b) as string) & "," & (i as string) & "," & (k as string)
                            repeat with s in ss
                                if ((tty of s) as string) is curTTY then set cur to true
                                set out to out & ";" & ((columns of s) as string) & "x" & ((rows of s) as string)
                            end repeat
                            return out & ";" & (cur as string)
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
        let sections = str.split(separator: ";").map { $0.trimmingCharacters(in: .whitespaces) }
        let parts = sections[0].split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        guard parts.count == 6,
              let x1 = Double(parts[0]), let y1 = Double(parts[1]),
              let x2 = Double(parts[2]), let y2 = Double(parts[3]),
              let index = Int(parts[4]), let pane = Int(parts[5])
        else { return nil }
        let sizes: [(cols: Int, rows: Int)] = sections.dropFirst().compactMap { item in
            let cr = item.split(separator: "x")
            guard cr.count == 2, let c = Int(cr[0]), let r = Int(cr[1]) else { return nil }
            return (c, r)
        }
        return WindowLookup(frame: CGRect(x: x1, y: y1, width: x2 - x1, height: y2 - y1),
                            isFrontmost: index == 1,
                            paneIndex: pane - 1,
                            paneSizes: sizes,
                            tabVisible: sections.last != "false")
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
        var split: WindowLookup? = nil
        if opts.ownerName == "iTerm2", let lookup = windowFrame(forTTY: currentTTY()) {
            // Two iTerm2 windows can occupy nearly identical screen bounds (one maximized behind
            // another) -- "iTerm2 is frontmost" alone can't tell those apart, only this can.
            guard lookup.isFrontmost, lookup.tabVisible else {
                panel.orderOut(nil)
                return
            }
            quartz = lookup.frame
            split = lookup
        } else if let fallback = fallbackWindowFrame() {
            quartz = fallback
        } else {
            panel.orderOut(nil)
            return
        }

        let term = toCocoa(quartz)
        let content = CGRect(x: term.minX, y: term.minY,
                             width: term.width, height: term.height - Self.titleBarHeight)

        // Default target is the whole terminal window. When the iTerm2 tab is split, narrow it to
        // this session's own split pane -- otherwise every pane's badge (an agent team in iTerm2
        // split panes, say) lands on the same spot of the window. If the split can't be rebuilt,
        // fall back to the whole window but stack by pane order, so they still don't overlap.
        var target = content
        var slot = opts.slot
        if let split = split, split.paneSizes.count > 1,
           split.paneSizes.indices.contains(split.paneIndex) {
            if let rects = SplitLayout.solve(split.paneSizes, window: content.size) {
                let f = rects[split.paneIndex]
                target = CGRect(x: content.minX + f.minX * content.width,
                                y: content.maxY - f.maxY * content.height,
                                width: f.width * content.width,
                                height: f.height * content.height)
            } else {
                slot += split.paneIndex
            }
        }
        // Under tmux, narrow it further to the tmux pane within that.
        if let pane = tmuxPaneGeometry() {
            guard pane.visible else {
                panel.orderOut(nil)
                return
            }
            // Cell fractions are measured from the top; Cocoa's y axis runs the other way.
            let outer = target
            target = CGRect(
                x: outer.minX + pane.fx0 * outer.width,
                y: outer.maxY - pane.fy1 * outer.height,
                width: (pane.fx1 - pane.fx0) * outer.width,
                height: (pane.fy1 - pane.fy0) * outer.height)
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
        // Slots stack away from the edge: down from a top edge (and from the middle), up from a
        // bottom one. Cocoa's y axis runs upward.
        let step = CGFloat(slot) * (s.height + max(4, m / 4))
        let y: CGFloat
        switch opts.position.count > 1 ? opts.position.first : nil {
        case "t": y = target.maxY - s.height - m - step
        case "b": y = target.minY + m + step
        default: y = target.midY - s.height / 2 - step
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

// `--solve-layout "106x41;106x5;..." --window 1512x851` prints SplitLayout.solve()'s answer, one
// "x0,y0,x1,y1" line per pane (or "nil"), and exits without drawing anything -- for the tests.
if let i = CommandLine.arguments.firstIndex(of: "--solve-layout"), i + 1 < CommandLine.arguments.count {
    let sizes: [(cols: Int, rows: Int)] = CommandLine.arguments[i + 1].split(separator: ";").compactMap {
        let cr = $0.split(separator: "x")
        guard cr.count == 2, let c = Int(cr[0]), let r = Int(cr[1]) else { return nil }
        return (c, r)
    }
    var window = CGSize(width: 1500, height: 850)
    if let w = CommandLine.arguments.firstIndex(of: "--window"), w + 1 < CommandLine.arguments.count {
        let wh = CommandLine.arguments[w + 1].split(separator: "x").compactMap { Double($0) }
        if wh.count == 2 { window = CGSize(width: wh[0], height: wh[1]) }
    }
    if let rects = SplitLayout.solve(sizes, window: window) {
        for r in rects {
            print(String(format: "%.3f,%.3f,%.3f,%.3f", r.minX, r.minY, r.maxX, r.maxY))
        }
    } else {
        print("nil")
    }
    exit(0)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = Controller(opts: parseArgs())
controller.run()
app.run()
