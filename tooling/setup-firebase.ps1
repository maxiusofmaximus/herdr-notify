<#
.SYNOPSIS
    Bootstrap the Firebase project, the Android app, and the push credentials.

.DESCRIPTION
    Automates every step `firebase-tools` can perform, and stops with a precise
    instruction for the one step it cannot: creating a service-account key.

    What is automated here:
      1. verify the CLI is authenticated
      2. create the Firebase project (or reuse an existing one)
      3. register the Android app and emit google-services.json
      4. locate the project's default service account

    What is NOT automated, and why:
      Issuing a service-account key is a privileged operation on the Google Cloud
      IAM API, and `firebase-tools` exposes no command for it. Do it from the
      Google Cloud console (IAM & Admin > Service Accounts > your project's
      account > Keys > Add key > JSON), or with gcloud. This script deliberately
      does not try to smuggle it through the CLI's own OAuth token: minting a
      long-lived credential from a developer login is exactly the habit the
      security audit will flag.

.PARAMETER ProjectId
    Firebase project id, e.g. herdr-notify. Created if it does not exist.

.PARAMETER PackageName
    The Android application id. Must match the `applicationId` in the app's
    build.gradle.kts exactly, or the pushed messages are rejected at delivery.

.PARAMETER DisplayName
    Human-readable project name.

.PARAMETER OutputDir
    The app module directory, i.e. `android/app`. Not the Gradle root: the Google
    Services plugin searches `app/google-services.json` and
    `app/src/<variant>/google-services.json`, and a file one level up is silently
    not found.

.PARAMETER DebugSuffix
    The `applicationIdSuffix` used by the debug build type. Must match
    `app/build.gradle.kts`.

.PARAMETER ReuseExisting
    Do not create a project; require that ProjectId already exists.

.EXAMPLE
    .\setup-firebase.ps1 -ProjectId herdr-notify -PackageName dev.herdrnotify.app

.EXAMPLE
    .\setup-firebase.ps1 -ProjectId herdr-notify -PackageName dev.herdrnotify.app -ReuseExisting
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9][a-z0-9-]{4,28}[a-z0-9]$')]
    [string] $ProjectId,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$')]
    [string] $PackageName,

    [string] $DisplayName = 'herdr notify',

    [string] $OutputDir = (Join-Path $PSScriptRoot '..\android\app'),

    [string] $DebugSuffix = '.debug',

    [switch] $ReuseExisting
)

$ErrorActionPreference = 'Stop'

function Step { param([string] $Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Ok   { param([string] $Message) Write-Host "    $Message" -ForegroundColor Green }
function Note { param([string] $Message) Write-Host "    $Message" -ForegroundColor Yellow }
function Die  { param([string] $Message) Write-Host "    $Message" -ForegroundColor Red; exit 1 }

function Invoke-FirebaseJson {
    <#
    .SYNOPSIS
        Run a firebase command and parse its JSON result.

    .DESCRIPTION
        Three things about `firebase --json` make a naive `| ConvertFrom-Json`
        fail silently, and each one costs real time to diagnose because the
        script then believes the thing it asked about does not exist:

        1. The payload is `{"status":"success","result":[...]}`, not a bare
           array, so `Where-Object { $_.projectId -eq ... }` inspects the wrapper
           and never matches.
        2. The CLI writes progress spinners with ANSI escapes to stdout ahead of
           the JSON, so the parse fails before it starts.
        3. On Windows the CLI can crash during teardown, appending a libuv
           assertion to stdout AFTER the JSON - the same
           `Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)` that makes
           `firebase login` appear to hang. The JSON is complete; only the text
           after it is garbage.

        So: take from the first brace to the last, and unwrap `.result`. Slicing
        between the outermost braces is what makes the exit-time crash
        survivable, and the payload is always a single top-level object.
    #>
    param([Parameter(ValueFromRemainingArguments)] [string[]] $Args)

    $raw = (& firebase @Args 2>$null | Out-String)
    $start = $raw.IndexOf('{')
    $end = $raw.LastIndexOf('}')
    if ($start -lt 0 -or $end -le $start) { return $null }

    $parsed = $raw.Substring($start, $end - $start + 1) | ConvertFrom-Json -ErrorAction SilentlyContinue
    if ($null -eq $parsed) { return $null }
    if ($parsed.PSObject.Properties.Name -contains 'result') { return $parsed.result }
    return $parsed
}

# -- 0. toolchain ----------------------------------------------------------

Step 'Checking the Firebase CLI'
if (-not (Get-Command firebase -ErrorAction SilentlyContinue)) {
    Die 'firebase not found on PATH. Install it with: pnpm add -g firebase-tools'
}
$version = (firebase --version 2>&1 | Out-String).Trim()
Ok "firebase-tools $version"

# -- 1. authentication -----------------------------------------------------

Step 'Verifying authentication'
# `login:list --json` prints the account's full OAuth token set, refresh token
# included. It is parsed and discarded here and never echoed, never written to a
# file, and never passed to another command's arguments - a bootstrap script is a
# bad place for a long-lived credential to pass through.
$accounts = @(Invoke-FirebaseJson login:list --json)
if (-not $accounts -or $accounts.Count -eq 0) {
    Die @'
No authenticated account. Run:
    firebase login --no-localhost
and follow the URL it prints, then complete with:
    firebase login <authorizationCode>
'@
}
foreach ($account in $accounts) { Ok "signed in as $($account.user.email)" }

# -- 2. project ------------------------------------------------------------

Step "Resolving project '$ProjectId'"
$existing = @(Invoke-FirebaseJson projects:list --json)
$known = $existing | Where-Object { $_.projectId -eq $ProjectId }

if ($known) {
    Ok "project already exists"
} elseif ($ReuseExisting) {
    Die "project '$ProjectId' does not exist and -ReuseExisting was set"
} else {
    Note "creating '$ProjectId' ..."
    firebase projects:create $ProjectId --display-name $DisplayName 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { Die 'firebase projects:create failed' }
    Ok "created"
}

# -- 3. android apps --------------------------------------------------------

function Register-AndroidApp {
    <#
    .SYNOPSIS
        Ensure one Android package is registered, and return its app id.

    .DESCRIPTION
        The field holding the package is `namespace`, not `packageName`.
        Matching the wrong name is silent - the filter finds nothing, the script
        tries to create a second app with the same package, and the API rejects
        it with a message about the project rather than about the duplicate.

        The platform is a POSITIONAL argument, not `--platform`; passing the flag
        fails with "unknown option", which reads like a version problem when it
        is a syntax one.
    #>
    param(
        [string] $Package,
        [string] $Label
    )

    $existing = @(Invoke-FirebaseJson apps:list --project $ProjectId --json) |
        Where-Object { $_.namespace -eq $Package } |
        Select-Object -First 1

    if ($existing) {
        Ok "$Label already registered (appId $($existing.appId))"
        return $existing.appId
    }

    Note "registering $Label ($Package)"
    firebase apps:create ANDROID $Label --project $ProjectId --package-name $Package 2>&1 |
        ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { Die "firebase apps:create failed for $Package" }

    $appId = (@(Invoke-FirebaseJson apps:list --project $ProjectId --json) |
        Where-Object { $_.namespace -eq $Package } |
        Select-Object -First 1).appId
    if (-not $appId) { Die "the app $Package was created but could not be read back" }
    Ok "$Label registered"
    return $appId
}

function Write-SdkConfig {
    <#
    .SYNOPSIS
        Emit one variant's google-services.json.

    .DESCRIPTION
        The plugin searches `app/google-services.json` and then
        `app/src/<variant>/google-services.json`. Keeping the debug config in
        `src/debug/` is the supported way to have two app ids in one project, and
        it is what makes `:app:assembleDebug` work alongside `:app:assembleRelease`
        without either of them falling back to the other's registration.
    #>
    param(
        [string] $AppId,
        [string] $Target
    )

    $raw = & firebase apps:sdkconfig ANDROID $AppId 2>$null | Out-String
    # The CLI can crash during teardown and append a libuv assertion to stdout
    # after the JSON. Slice the payload out instead of handing the garbage to
    # the parser.
    $start = $raw.IndexOf('{'); $end = $raw.LastIndexOf('}')
    if ($start -lt 0 -or $end -le $start) { Die "sdkconfig for $AppId returned nothing parseable" }
    $json = $raw.Substring($start, $end - $start + 1)

    # Validate before writing. A file that is not the JSON the plugin expects
    # fails at build time with a parse error that points at the build, not at
    # the bootstrap, which is a miserable thing to debug.
    try { $null = $json | ConvertFrom-Json -ErrorAction Stop }
    catch { Die "sdkconfig for $AppId is not valid JSON: $($_.Exception.Message)" }

    $dir = Split-Path -Parent $Target
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Set-Content -Path $Target -Value $json -Encoding utf8
    Ok "written to $Target"
}

Step "Registering the release app '$PackageName'"
$releaseAppId = Register-AndroidApp -Package $PackageName -Label $DisplayName

# The debug build type appends an applicationIdSuffix, so its package is a
# different one. The Google Services plugin matches strictly on that package, so
# without a second registration `assembleDebug` fails with "No matching client
# found" while the release build is perfectly happy - a confusing asymmetry that
# only shows up on the build you run most often.
$debugPackage = "$PackageName$DebugSuffix"
Step "Registering the debug app '$debugPackage'"
$debugAppId = Register-AndroidApp -Package $debugPackage -Label "$DisplayName (debug)"

# -- 4. google-services.json ----------------------------------------------

Step 'Emitting google-services.json'
Write-SdkConfig -AppId $releaseAppId -Target (Join-Path $OutputDir 'google-services.json')
Write-SdkConfig -AppId $debugAppId   -Target (Join-Path $OutputDir 'src\debug\google-services.json')
Note 'gitignored; never commit it.'

# -- 5. service account ----------------------------------------------------

$account = "$ProjectId@appspot.gserviceaccount.com"
$keyPath = Join-Path $PSScriptRoot '..\secrets\service-account.json'

Step 'Service-account key (manual step)'
Note "The project has a default service account: $account"
Note 'firebase-tools cannot mint a key, and this script will not do it for you'
Note 'using a developer login token, because that manufactures a long-lived'
Note 'credential from a short-lived session.'
Write-Host ''
Write-Host '    Do one of these:' -ForegroundColor Cyan
Write-Host "      console  https://console.cloud.google.com/iam-admin/serviceAccounts?project=$ProjectId" -ForegroundColor Gray
Write-Host '               -> the account above -> Keys -> Add key -> JSON'
Write-Host "      gcloud   gcloud iam service-accounts keys create `"$keyPath`" ``" -ForegroundColor Gray
Write-Host "                     --iam-account=$account"
Write-Host ''
Write-Host "    Then point the gateway at it:" -ForegroundColor Cyan
Write-Host "      `$env:GOOGLE_APPLICATION_CREDENTIALS = '$keyPath'" -ForegroundColor Gray

# -- summary ---------------------------------------------------------------

Step 'Summary'
Write-Host "    project       $ProjectId"
Write-Host "    release pkg   $PackageName"
Write-Host "    release cfg   $OutputDir\google-services.json"
Write-Host "    debug pkg     $debugPackage"
Write-Host "    debug cfg     $OutputDir\src\debug\google-services.json"
Write-Host "    service acct  $account"
Write-Host "    key           $(if (Test-Path $keyPath) { $keyPath } else { 'MISSING - see above' })"
Write-Host ''
Ok 'Done.'
