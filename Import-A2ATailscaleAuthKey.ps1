[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$CiphertextPath,

    [switch]$KeepCiphertext
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$identityPath = Join-Path $env:LOCALAPPDATA 'AnritsuA2A\secrets\tailscale-poc-age-identity.txt'
$destinationPath = 'C:\ProgramData\Tailscale\anritsu-a2a-poc-auth.key'
$agePackagePath = Join-Path $env:LOCALAPPDATA `
    'Microsoft\WinGet\Packages\FiloSottile.age_Microsoft.Winget.Source_8wekyb3d8bbwe\age\age.exe'

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Import must run from an elevated Administrator PowerShell.'
    }
}

function Resolve-AgeExecutable {
    $command = Get-Command 'age.exe' -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    if (Test-Path -LiteralPath $agePackagePath -PathType Leaf) {
        return $agePackagePath
    }
    throw 'age.exe is not installed. Install winget package FiloSottile.age first.'
}

function Assert-IdentityIsRestricted {
    if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
        throw "The Anritsu age identity is missing: $identityPath"
    }
    $item = Get-Item -LiteralPath $identityPath -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'The Anritsu age identity cannot be a symbolic link or reparse point.'
    }

    $allowedSids = @(
        [Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
        'S-1-5-18'
    )
    $acl = Get-Acl -LiteralPath $identityPath
    if (-not $acl.AreAccessRulesProtected) {
        throw 'The Anritsu age identity inherits filesystem permissions.'
    }
    foreach ($rule in $acl.Access) {
        $sid = $rule.IdentityReference.Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value
        if ($rule.AccessControlType -eq 'Allow' -and $sid -notin $allowedSids) {
            throw 'The Anritsu age identity is readable by an unexpected account.'
        }
    }
}

function Set-RestrictedAuthKeyAcl {
    param([Parameter(Mandatory)][string]$Path)
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sidValue in @('S-1-5-18', 'S-1-5-32-544')) {
        $sid = [Security.Principal.SecurityIdentifier]::new($sidValue)
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

Assert-Administrator
Assert-IdentityIsRestricted
$age = Resolve-AgeExecutable
$ciphertext = Get-Item -LiteralPath $CiphertextPath -Force
if ($ciphertext.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'The ciphertext cannot be a symbolic link or reparse point.'
}
if ($ciphertext.Extension -ne '.age' -or $ciphertext.Length -le 0 -or $ciphertext.Length -gt 1MB) {
    throw 'The ciphertext must be a non-empty .age file no larger than 1 MiB.'
}

$destinationRoot = Split-Path -Parent $destinationPath
New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
$temporaryPath = "$destinationPath.tmp.$([guid]::NewGuid().ToString('N'))"
$importSucceeded = $false
try {
    & $age --decrypt --identity $identityPath --output $temporaryPath $ciphertext.FullName 2>$null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temporaryPath -PathType Leaf)) {
        throw 'age could not decrypt the Tailscale auth key ciphertext.'
    }

    $key = [IO.File]::ReadAllText($temporaryPath).Trim()
    try {
        if ($key.Length -gt 512 -or $key -notmatch '^tskey-auth-[^\s]+$') {
            throw 'The decrypted content is not one valid Tailscale auth key.'
        }
        [IO.File]::WriteAllText($temporaryPath, $key, [Text.UTF8Encoding]::new($false))
    }
    finally {
        $key = $null
    }

    Set-RestrictedAuthKeyAcl -Path $temporaryPath
    Move-Item -LiteralPath $temporaryPath -Destination $destinationPath -Force
    $importSucceeded = $true
    Write-Output "A2A_TAILSCALE_AUTH_KEY_IMPORTED path=$destinationPath plaintextDisplayed=false"
}
finally {
    Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    if ($importSucceeded -and -not $KeepCiphertext) {
        Remove-Item -LiteralPath $ciphertext.FullName -Force -ErrorAction SilentlyContinue
    }
}
