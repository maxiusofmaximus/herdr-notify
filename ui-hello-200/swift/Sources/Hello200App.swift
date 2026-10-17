// hello200 — SwiftUI list of 200 rows for the RFC v8b Apple measurement.
// Shared by the macOS SwiftPM build (ui-hello-200/swift) and the iOS xcodegen project
// (ui-hello-200/swift-ios/project.yml), which points at this same file.
//
// Measures, from App init to the first CADisplayLink tick:
//   first_frame_ms  — time to first frame (written to first_frame.marker as BOOT_FIRST_FRAME_MS=...)
//   rss_mb          — resident memory (mach task_info)
// With `--scroll-benchmark <seconds>` it also drives a programmatic scroll over the 200 rows
// and records every display-link frame interval: p50 / p95 / p99 (ms) and % of frames over 16.7 ms.
// Output: one JSON line on stdout and in frames.json (cwd on macOS, Documents on iOS).
import SwiftUI
import QuartzCore
#if os(macOS)
import AppKit
#else
import UIKit
#endif

let rowCount = 200

let benchSeconds: Double? = {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: "--scroll-benchmark"), i + 1 < args.count else { return nil }
    return Double(args[i + 1])
}()

let outDir: URL = {
    #if os(macOS)
    return URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    #else
    return FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    #endif
}()

func residentMB() -> Double {
    var info = mach_task_basic_info()
    var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<natural_t>.size)
    let kr = withUnsafeMutablePointer(to: &info) { ptr in
        ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { raw in
            task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), raw, &count)
        }
    }
    return kr == KERN_SUCCESS ? Double(info.resident_size) / 1_048_576 : -1
}

func round2(_ x: Double) -> String { String(format: "%.2f", x) }

final class Bench: NSObject, ObservableObject {
    @Published var row = 0

    let launch = Date()
    private var link: CADisplayLink?
    private var firstFrameMs: Double?
    private var benchStart: CFTimeInterval?
    private var lastTick: CFTimeInterval = 0
    private var deltasMs: [Double] = []
    private var finished = false

    // Called once the probe view is attached to a window; the link fires on every frame.
    func startLink(_ view: AnyObject) {
        guard link == nil else { return }
        #if os(macOS)
        let l = (view as! NSView).displayLink(target: self, selector: #selector(tick(_:)))
        #else
        let l = CADisplayLink(target: self, selector: #selector(tick(_:)))
        #endif
        l.add(to: .main, forMode: .common)
        link = l
    }

    @objc func tick(_ l: CADisplayLink) {
        if firstFrameMs == nil {
            firstFrameMs = Date().timeIntervalSince(launch) * 1000
            let line = "BOOT_FIRST_FRAME_MS=\(Int(firstFrameMs ?? -1)) RSS_MB=\(round2(residentMB()))\n"
            FileHandle.standardError.write(line.data(using: .utf8)!)
            try? line.write(to: outDir.appendingPathComponent("first_frame.marker"), atomically: true, encoding: .utf8)
            guard benchSeconds != nil else { return }
            benchStart = l.timestamp
            lastTick = l.timestamp
            return
        }
        guard let start = benchStart, let seconds = benchSeconds, !finished else { return }

        let now = l.timestamp
        deltasMs.append((now - lastTick) * 1000)
        lastTick = now

        let elapsed = now - start
        if elapsed >= seconds {
            finish()
            return
        }
        // 40 rows per second, sweeping down and back up the list.
        let pos = Int(elapsed * 40) % (rowCount * 2)
        row = pos < rowCount ? pos : rowCount * 2 - pos - 1
    }

    private func finish() {
        finished = true
        link?.invalidate()
        link = nil
        let d = deltasMs.sorted()
        func pct(_ p: Double) -> Double {
            d.isEmpty ? 0 : d[min(d.count - 1, Int(Double(d.count) * p))]
        }
        let janky = d.filter { $0 > 16.7 }.count
        let jankyPct = d.isEmpty ? 0 : Double(janky) * 100 / Double(d.count)
        let json = "{\"impl\":\"swiftui-apple\",\"first_frame_ms\":\(round2(firstFrameMs ?? -1))," +
            "\"rss_mb_end\":\(round2(residentMB())),\"frames\":\(d.count)," +
            "\"frame_ms_p50\":\(round2(pct(0.5))),\"frame_ms_p95\":\(round2(pct(0.95)))," +
            "\"frame_ms_p99\":\(round2(pct(0.99))),\"janky_pct\":\(round2(jankyPct))}"
        print(json)
        try? (json + "\n").write(to: outDir.appendingPathComponent("frames.json"), atomically: true, encoding: .utf8)
        exit(0)
    }
}

#if os(macOS)
final class ProbeView: NSView {
    var onWindow: ((ProbeView) -> Void)?
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window != nil { onWindow?(self) }
    }
}

struct Probe: NSViewRepresentable {
    let bench: Bench
    func makeNSView(context: Context) -> ProbeView {
        let v = ProbeView()
        v.onWindow = { view in bench.startLink(view) }
        return v
    }
    func updateNSView(_ view: ProbeView, context: Context) {}
}
#else
final class ProbeView: UIView {
    var onWindow: ((ProbeView) -> Void)?
    override func didMoveToWindow() {
        super.didMoveToWindow()
        if window != nil { onWindow?(self) }
    }
}

struct Probe: UIViewRepresentable {
    let bench: Bench
    func makeUIView(context: Context) -> ProbeView {
        let v = ProbeView()
        v.onWindow = { view in bench.startLink(view) }
        return v
    }
    func updateUIView(_ view: ProbeView, context: Context) {}
}
#endif

struct ContentView: View {
    @ObservedObject var bench: Bench

    var body: some View {
        ScrollViewReader { proxy in
            List {
                ForEach(0..<rowCount, id: \.self) { i in
                    Text("Agent \(i) — status: idle — task-\(i)")
                        .font(.system(size: 14))
                        .frame(height: 28, alignment: .leading)
                        .id(i)
                }
            }
            .onChange(of: bench.row) { _, newRow in
                proxy.scrollTo(newRow, anchor: .top)
            }
        }
        .background(Probe(bench: bench))
    }
}

@main
struct Hello200App: App {
    @StateObject private var bench = Bench()

    init() {
        #if os(macOS)
        NSApplication.shared.setActivationPolicy(.regular)
        #endif
    }

    var body: some Scene {
        WindowGroup {
            ContentView(bench: bench)
                .frame(minWidth: 420, minHeight: 640)
        }
    }
}
