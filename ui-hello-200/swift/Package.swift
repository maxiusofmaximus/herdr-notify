// swift-tools-version:5.9
// hello200 macOS SwiftUI app (RFC v8b). Build: swift build -c release
// Needs macOS 14 for NSView.displayLink(target:selector:).
import PackageDescription

let package = Package(
    name: "hello200",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "hello200", path: "Sources")
    ]
)
