<#
.SYNOPSIS
    Give the gateway credentials for FCM, without minting a long-lived key.

.DESCRIPTION
    The gateway sends push through `firebase-admin`, which authenticates with
    Google Application Default Credentials. There are two ways to satisfy that,
    and this script exists to make the difference impossible to miss:

    **Application Default Credentials (the default here).** `gcloud auth
    application-default login` opens a browser once and writes a refreshable
    OAuth credential to a well-known path. No private key is ever created, so
    there is nothing to leak, nothing to rotate, and nothing to revoke
    separately - you revoke it from your Google account like any other session.
    This is what Google now recommends, and what this script does.

    **A service-account key (opt-in, discouraged).** `gcloud iam
    service-accounts keys create` writes a JSON file containing a permanent RSA
    private key. Google has been steering customers away from these since 2024
    and added an organization policy,
    `iam.disableServiceAccountKeyCreation`, specifically to stop them. It is
    offered here only because some tools still insist on the file, and only
    behind an explicit switch, with the reason printed.

    The difference is not stylistic. A key file is a bearer credential: anyone
    holding the file can send as the service account until someone notices and
    deletes the key. An ADC credential is bound to a session you can end from a
    browser.

.PARAMETER UseServiceAccountKey
    Mint a key file instead of using ADC. Read the .DESCRIPTION first.

.EXAMPLE
    .\setup-firebase-credentials.ps1

.EXAMPLE
    .\setup-firebase-credentials.ps1 -UseServiceAccountKey
#>
[CmdletBinding()]
param(
    [string] $ProjectId = 'herdr-notify',
    [switch] $UseServiceAccountKey
)

$ErrorActionPreference = 'Stop'

function Step { param([string] $m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok   { param([string] $m) Write-Host "    $m" -ForegroundColor Green }
function Note { param([string] $m) Write-Host "    $m" -ForegroundColor Yellow }
function Die  { param([string] $m) Write-Host "    $m" -ForegroundColor Red; exit 1 }

$adcPath = if ($env:APPDATA) { Join-Path $env:APPDATA 'gcloud\application_default_credentials.json' }
           else { "$HOME/.config/gcloud/application_default_credentials.json" }
$keyPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'secrets\service-account.json'

# -- 0. gcloud -------------------------------------------------------------

Step 'Checking for the Google Cloud CLI'

# Search rather than trust PATH. The Windows installer lands in at least three
# different places depending on whether it was per-user or per-machine, and
# which one it chose also decides whether a *new* shell has it on PATH. A
# freshly started process does not see a PATH entry added after it launched, so
# "not on PATH" is the normal state right after installing and is not evidence
# that gcloud is missing.
$gcloud = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloud) {
    $candidates = @(
        "$env:ProgramFiles\Google\Cloud SDK\bin\gcloud.cmd",
        "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "$env:LOCALAPPDATA\Google\Cloud SDK\bin\gcloud.cmd",
        "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { $gcloud = (Get-Item $candidate).FullName; break }
    }
}
if (-not $gcloud) {
    Die @'
gcloud is not installed, and it is not in any of the usual locations.

Install it with:

    winget install --id Google.CloudSDK --exact

This needs an elevated shell. Note the per-machine installer lands under
"Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin" on some machines,
which is not on PATH until a new shell is opened.
'@
}
# A string from here on, not a command object: the discovered path is invoked
# explicitly below, so a PATH that has not been refreshed cannot break it.
$gcloud = if ($gcloud -is [string]) { $gcloud } else { $gcloud.Source }
Ok "gcloud: $gcloud"

# -- 1. which strategy -----------------------------------------------------

if ($UseServiceAccountKey) {
    Step 'Minting a service-account key (you asked for this)'
    Note 'Google is steering away from these. You now have to justify the'
    Note 'exceptions with an explicit approval process, and can be prevented'
    Note 'from creating more at the organization level.'

    if (Test-Path $keyPath) {
        Ok "already exists: $keyPath"
    } else {
        $secretsDir = Split-Path -Parent $keyPath
        if (-not (Test-Path $secretsDir)) { New-Item -ItemType Directory -Path $secretsDir -Force | Out-Null }
        $account = "$ProjectId@appspot.gserviceaccount.com"
        & $gcloud iam service-accounts keys create $keyPath --iam-account $account 2>&1 |
            ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) { Die 'gcloud could not create the key' }
        Ok "written to $keyPath"
    }

    Step 'Restricting the key'
    Note 'A freshly minted key can send as the service account and nothing else.'
    Note 'FCM sending needs no extra IAM role, so if the project default is more'
    Note 'than "send", this key is more powerful than it needs to be. Check with:'
    Note ''
    Note "    gcloud projects get-iam-policy $ProjectId"
    Note ''
    Note 'and remove roles the gateway does not need.'

    Step 'Pointing the gateway at it'
    Write-Host "    `$env:GOOGLE_APPLICATION_CREDENTIALS = '$keyPath'" -ForegroundColor Cyan
    Write-Host ''
    Note 'Gitignored. Never commit it.'
    Ok 'Done.'
    exit 0
}

# -- 2. ADC ----------------------------------------------------------------

Step 'Checking for Application Default Credentials'
if (Test-Path $adcPath) {
    Ok "found: $adcPath"
} else {
    Note 'not found. Creating it now - this opens a browser.'
    Write-Host ''
    # Interactive by nature: it is a consent screen on a Google account. An
    # agent cannot and should not click through someone's OAuth consent.
    & $gcloud auth application-default login 2>&1 |
        ForEach-Object { Write-Host "    $_" }

    if (-not (Test-Path $adcPath)) {
        Die "no credential file at $adcPath after login. Check the browser step completed."
    }
    Ok "created: $adcPath"
}

Step 'Verifying the credential can actually send'
# The active project is unset unless `gcloud init` was run, and the gateway does
# not need it - firebase-admin takes the project from the credential. So this is
# reported, not required.
#
# The error preference has to be relaxed for the call. gcloud.cmd is a batch
# file, and PowerShell promotes its stderr to a terminating error under
# `Stop`; `2>$null` alone does not prevent that, because the failure happens in
# the native-command wrapper rather than in the stream. `(unset)` on stderr is
# normal output, not a problem to report.
$relaxed = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$project = (& $gcloud config get-value project 2>$null | Out-String).Trim()
$ErrorActionPreference = $relaxed
if ($project -and $project -ne '(unset)') {
    Ok "gcloud's active project is '$project'"
} else {
    Note "no active gcloud project set - not required, the gateway names its own"
}


# A credential that exists but cannot reach the project is the failure mode
# that matters, and it is not visible from the file's presence. So exercise it.
$probe = @'
import sys
try:
    from firebase_admin import credentials, messaging
except ImportError as exc:
    print(f"firebase-admin is not importable: {exc}")
    sys.exit(2)

try:
    cred = credentials.ApplicationDefault()
except Exception as exc:
    print(f"ADC unusable: {type(exc).__name__}: {exc}")
    sys.exit(1)

project = getattr(cred, "project_id", None)
print(f"credential ok, project={project}")
sys.exit(0)
'@

$probePath = Join-Path $env:TEMP 'hn-adc-probe.py'
$probe | Set-Content -Path $probePath -Encoding utf8

$venv = Join-Path (Split-Path -Parent $PSScriptRoot) 'gateway\.venv\Scripts\python.exe'
$python = if (Test-Path $venv) { $venv } else { 'python' }

Step 'Checking the credential with firebase-admin'
# Same reason as above: google-auth writes a UserWarning to stderr when the
# credential has no quota project, and that must not abort a check that is
# actually succeeding. The warning is filtered out of the output rather than
# merged, because "it worked, but here is a caveat" and "it failed" should not
# look the same in a log.
$relaxed = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$probeOutput = (& $python $probePath 2>$null | Out-String).Trim()
$probeOk = $LASTEXITCODE -eq 0
$ErrorActionPreference = $relaxed
if ($probeOutput) { $probeOutput -split "`n" | ForEach-Object { Write-Host "    $($_.Trim())" } }
Remove-Item $probePath -ErrorAction SilentlyContinue

if (-not $probeOk) {
    Note 'The credential exists but could not be used. Common causes:'
    Note '  - firebase-admin is not installed:  pip install firebase-admin'
    Note '  - the account has no role on the project:'
    Note "        gcloud projects add-iam-policy-binding $ProjectId ``"
    Note "          --member='user:$(whoami)@gmail.com' --role='roles/editor'"
    Note '  - the API is not enabled:'
    Note "        gcloud services enable firebase.googleapis.com --project $ProjectId"
    exit 1
}

Step 'What the gateway needs now'
Write-Host '    Nothing. firebase-admin finds this credential on its own.' -ForegroundColor Gray
Write-Host ''
Write-Host '    Start the gateway as usual:'
Write-Host '        cd gateway; .venv\Scripts\python -m herdr_notify.cli serve' -ForegroundColor Gray
Write-Host ''
Note 'No environment variable is required, and that is the point: the'
Note 'credential lives in a standard location, is refreshable, and is revoked'
Note 'by signing out of your Google account rather than by deleting a file'
Note 'somewhere and hoping you remember.'
Write-Host ''
Ok 'Done.'
