# Apple SwiftUI benchmark (hello200) — how to run

Status: **pendiente de runner**. The workflow and sources were written and YAML-validated on
Windows, but they have not been executed (no macOS host). Numbers exist only after a run in CI.

## What runs

Workflow: `.github/workflows/rfc-v8b-apple-bench.yml`

- Triggers: push to branch `ci/apple-bench`, or manual `workflow_dispatch`.
- Job `macos` (`macos-latest`): SwiftPM build of `ui-hello-200/swift`, 5 cold starts (first frame ms and RSS at first frame), binary size and idle RSS, 10 s programmatic scroll over 200 rows.
- Job `ios` (`macos-latest`): `xcodegen generate` from `ui-hello-200/swift-ios/project.yml`, build for the iPhone 16 simulator, 3 cold launches, 10 s scroll benchmark.
- Results: artifacts `rfc-v8b-macos-results` and `rfc-v8b-ios-sim-results`, plus the job summary.

## How to launch

1. Push the branch: `git push origin HEAD:ci/apple-bench` (or push to an existing `ci/apple-bench`).
2. Or open Actions → `rfc-v8b-apple-bench` → Run workflow.

## Local launch (macOS 14+ with Xcode)

```sh
cd ui-hello-200/swift
swift build -c release
.build/release/hello200 --scroll-benchmark 10   # writes frames.json in the cwd
```

The first frame writes `first_frame.marker` (`BOOT_FIRST_FRAME_MS=... RSS_MB=...`) to the cwd.

## Caveats

- The iOS simulator uses the host GPU; its numbers are not device numbers.
- The Swift sources were not compiled before being committed. The first CI run is the compile check.
- Shared source: `ui-hello-200/swift/Sources/Hello200App.swift` is used by both SwiftPM and xcodegen.
