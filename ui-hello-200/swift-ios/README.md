# hello200 — iOS simulator project (xcodegen)

`project.yml` generates `hello200.xcodeproj` and points at the shared SwiftUI source in `../swift/Sources`.

```sh
brew install xcodegen
xcodegen generate
xcodebuild -project hello200.xcodeproj -scheme hello200 -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 16' -derivedDataPath build build
```

Measurement flow and results: see `../APPLE-BENCH.md` and the `ios` job in `.github/workflows/rfc-v8b-apple-bench.yml`.
Status: pendiente de runner (not executed locally).
