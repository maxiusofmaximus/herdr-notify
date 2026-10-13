<#
.SYNOPSIS
    Generate the release signing key and wire it into the Gradle build.

.DESCRIPTION
    Creates the one credential in this project that is genuinely irreplaceable,
    and is explicit about it.

    **Losing the keystore means the app can never be updated in place.** Not
    "you need to reinstall", which is not true: Android identifies an app by
    package name and verifies updates against the signing key. A new key means
    a different app, side by side, with a different data directory, and any
    future version signed with a new key cannot replace the installed one. This
    is the only credential in the project that has no rotation story, which is
    why the script prints where it is and refuses to overwrite.

    Two decisions are made here rather than asked about, and both are the
    agent-safe ones:

    **The password is generated, never typed, and never printed.** A password
    that a person chooses gets reused, gets written in a chat, and ends up in a
    password manager labelled "android". A generated one is read once by
    keytool. It is written to `keystore.properties`, which is gitignored, and
    the script deliberately does not echo it - so a transcript of this run, or
    a screenshot of the terminal, does not contain the secret.

    **The key is not overwritten if it already exists.** Re-running this must
    never destroy a key that signed a shipped release. That is the single most
    destructive thing a setup script like this could do, and it is guarded.

.PARAMETER Alias
    Key alias inside the keystore.

.PARAMETER StorePassword
    Supply to choose the password yourself. Omit to have one generated. If you
    supply it, it will appear in your shell history - the generated path avoids
    that, which is why it is the default.

.EXAMPLE
    .\setup-signing.ps1

.EXAMPLE
    .\setup-signing.ps1 -Alias upload -Organization "Maximus"
#>
[CmdletBinding()]
param(
    [string] $Alias = 'herdr-notify',
    [string] $Organization = 'maxiusofmaximus',
    [string] $CommonName = 'herdr-notify release',
    [string] $StorePassword,
    [int] $ValidityDays = 10950
)

$ErrorActionPreference = 'Stop'

function Step { param([string] $m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok   { param([string] $m) Write-Host "    $m" -ForegroundColor Green }
function Note { param([string] $m) Write-Host "    $m" -ForegroundColor Yellow }
function Die  { param([string] $m) Write-Host "    $m" -ForegroundColor Red; exit 1 }

function Invoke-Native {
    <#
    .SYNOPSIS
        Run an external command without letting its stderr kill the script.

    .DESCRIPTION
        `$ErrorActionPreference = 'Stop'` turns *any* line a native command
        writes to stderr into a terminating error. `keytool` writes its normal
        progress narration - "Generating RSA keypair" - to stderr, so a
        perfectly successful run aborts the script on its first line of output
        and leaves no keystore behind. That is the confusing version: the command
        worked, the script died, and nothing was written.

        So the preference is relaxed for the duration of the call and restored
        after, and the real signal - the exit code - is returned instead.
    #>
    param(
        [Parameter(Mandatory)] [string] $Command,
        [Parameter(ValueFromRemainingArguments)] [string[]] $CommandArgs
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command @CommandArgs 2>&1 | ForEach-Object { Write-Host "    $_" }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

$root = Split-Path -Parent $PSScriptRoot
$keystoreDir = Join-Path $root 'keystores'
$keystorePath = Join-Path $keystoreDir 'release.jks'
$propertiesPath = Join-Path $root 'keystore.properties'

# -- 0. refuse to destroy an existing key ---------------------------------

Step 'Checking for an existing signing key'
if (Test-Path $keystorePath) {
    Ok "found $keystorePath"
    Note 'This key already exists and is NOT being touched.'
    Note 'If a release has shipped with it, replacing it would make every future'
    Note 'update uninstallable. If you mean to start over, delete the file by hand.'
    exit 0
}
Ok 'no existing key'

# -- 1. toolchain ----------------------------------------------------------

Step 'Checking the toolchain'
$keytool = Get-Command keytool -ErrorAction SilentlyContinue
if (-not $keytool) { Die 'keytool not on PATH. Install a JDK 17 and retry.' }
Ok "keytool: $($keytool.Source)"

# -- 2. password -----------------------------------------------------------

Step 'Preparing the keystore password'
# Generated rather than chosen. See the .DESCRIPTION for why: a password that
# passes through a human gets reused and written down somewhere, and this one
# only ever needs to be read twice, by keytool and by Gradle.
if ($StorePassword) {
    Note 'using the password you supplied'
} else {
    # RandomNumberGenerator.Fill is .NET Core and does not exist in Windows
    # PowerShell 5.1, which is what this script runs under. The instance API is
    # the one that works on both, and it is seeded by the OS, not by a clock.
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $StorePassword = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', 'A').Replace('/', 'B')
    Ok 'generated a 32-byte random password'
    # Deliberately not echoed. `keystore.properties` is the only place it lands.
}

# -- 3. generate -----------------------------------------------------------

Step 'Generating the release key'
if (-not (Test-Path $keystoreDir)) { New-Item -ItemType Directory -Path $keystoreDir -Force | Out-Null }

# keytool reads the password from an argument, so it is briefly visible in the
# process table to other processes running as the same user. That is a narrower
# exposure than writing it to a file, and the alternative - the interactive
# prompt - cannot be automated at all.
$code = Invoke-Native keytool `
    -genkeypair `
    -keystore $keystorePath `
    -storetype PKCS12 `
    -alias $Alias `
    -keyalg RSA `
    -keysize 4096 `
    -sigalg SHA256withRSA `
    -validity $ValidityDays `
    -storepass $StorePassword `
    -keypass $StorePassword `
    -dname "CN=$CommonName, OU=Android, O=$Organization, C=CO"

if ($code -ne 0) { Die "keytool failed with exit code $code" }
if (-not (Test-Path $keystorePath)) { Die "keytool reported success but $keystorePath is missing" }
Ok "written to $keystorePath"

# -- 4. wire it up ---------------------------------------------------------

Step 'Writing keystore.properties'
# storeFile is absolute on purpose. A relative path here resolves against the
# module directory, not the repository root, and the resulting "file not found"
# does not name the file it looked for.
@"
# Generated by tooling/setup-signing.ps1. Never commit this file: it holds the
# store and key passwords in plain text. It is in .gitignore, and that is the
# first line of defence rather than the last.
storeFile=$($keystorePath -replace '\\', '\\')
storePassword=$StorePassword
keyAlias=$Alias
keyPassword=$StorePassword
"@ | Set-Content -Path $propertiesPath -Encoding utf8
Ok "written to $propertiesPath"

# PKCS12 requires the key password to equal the store password. Asserting it
# here means a future switch to JKS - which allows them to differ - does not
# silently change the file's expectations.
Note 'PKCS12: keyPassword equals storePassword by format requirement.'

# -- 5. verify -------------------------------------------------------------

Step 'Verifying the key'
$code = Invoke-Native keytool -list -v -keystore $keystorePath -storepass $StorePassword
if ($code -ne 0) { Die 'the generated key cannot be reopened' }
Ok 'key reopens cleanly'

# -- 6. what to do with it -------------------------------------------------

Step 'What to do with this key'
@'

    This file is the app's identity for the rest of its life. Back it up
    somewhere you will still have in five years, in a place that is not this
    laptop:

      keystores\release.jks
      keystore.properties

    Both are needed together; the file alone is useless without the passwords.

    Losing them means future versions cannot update the installed app. Android
    matches updates by signing key, so a new key produces a separate app rather
    than an upgrade, and the installed one becomes unreachable without a
    factory reset.

    Do NOT commit either file. To release from CI instead, put the base64 of
    the keystore in a GitHub Actions secret and the passwords alongside it;
    see docs/android-release.md.
'@ | ForEach-Object { Write-Host $_ -ForegroundColor Gray }

Write-Host ''
Ok 'Done.'
