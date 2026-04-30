param()

$ErrorActionPreference = "Stop"

function Write-HookLog([string]$Message) {
  Write-Host "[cursor-auto-commit] $Message"
}

try {
  # Cursor sends JSON via stdin for hooks, but we don't need it for this behavior.
  # Do NOT read stdin here; it can block in some terminal environments.

  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-HookLog "git not found on PATH; skipping."
    exit 0
  }

  if (-not (Test-Path ".git")) {
    Write-HookLog "not a git repo; skipping."
    exit 0
  }

  if ($env:CURSOR_AUTO_COMMIT -eq "0") {
    Write-HookLog "CURSOR_AUTO_COMMIT=0; skipping."
    exit 0
  }

  Write-HookLog "detecting branch..."
  $branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
  if (-not $branch) { $branch = "unknown" }

  $allowMain = ($env:CURSOR_AUTO_COMMIT_ALLOW_MAIN -eq "1")
  if (-not $allowMain -and $branch -in @("main", "master")) {
    Write-HookLog "on '$branch'; skipping auto-commit to avoid direct pushes."
    exit 0
  }

  Write-HookLog "checking working tree status..."
  $porcelain = git status --porcelain=v1
  if (-not $porcelain) {
    Write-HookLog "no changes; skipping."
    exit 0
  }

  Write-HookLog "listing changed/untracked files..."
  $changedFiles = @(git diff --name-only)
  $untrackedFiles = @(git ls-files --others --exclude-standard)
  $allFiles = @($changedFiles + $untrackedFiles) | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique

  # Skip committing if changes include likely-secrets files.
  $blockedPatterns = @(
    '(^|/)\.env($|\.)',
    '(^|/)id_rsa($|\.)',
    '(^|/)credentials\.json$',
    '(^|/)secrets?\.ya?ml$',
    '(^|/)\.pfx$',
    '(^|/)\.pem$'
  )
  foreach ($f in $allFiles) {
    foreach ($pat in $blockedPatterns) {
      if ($f -match $pat) {
        Write-HookLog "blocked file detected ($f); skipping auto-commit."
        exit 0
      }
    }
  }

  # Avoid committing large/binary artifacts (e.g. design zips). You can still commit manually.
  $skipExtensions = @(".zip", ".7z", ".rar", ".exe", ".dll", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".pdf")
  $filteredFiles = @()
  foreach ($f in $allFiles) {
    $ext = [IO.Path]::GetExtension($f).ToLowerInvariant()
    if ($skipExtensions -contains $ext) {
      Write-HookLog "skipping binary/asset file: $f"
      continue
    }
    $filteredFiles += $f
  }

  if (-not $filteredFiles -or $filteredFiles.Count -eq 0) {
    Write-HookLog "only binary/asset changes detected; skipping."
    exit 0
  }

  # Stage filtered files only.
  Write-HookLog "staging filtered files..."
  foreach ($f in $filteredFiles) {
    git add -- "$f" | Out-Null
  }

  # If staging didn't result in anything, bail.
  Write-HookLog "verifying staged changes..."
  $staged = git diff --cached --name-only
  if (-not $staged) {
    Write-HookLog "nothing staged after filtering; skipping."
    exit 0
  }

  $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $msg = "chore(cursor): auto-commit after agent stop ($timestamp)"

  Write-HookLog "committing..."
  git commit -m "$msg" | Out-Null

  # Push to the current branch, but NEVER allow interactive prompts (hooks must not hang).
  # If auth is missing, this will fail fast and we keep the local commit.
  $oldPrompt = $env:GIT_TERMINAL_PROMPT
  $oldAskpass = $env:GIT_ASKPASS
  $env:GIT_TERMINAL_PROMPT = "0"
  $env:GIT_ASKPASS = "echo"
  try {
    Write-HookLog "pushing..."
    git push origin HEAD | Out-Null
  }
  catch {
    Write-HookLog "push failed (non-interactive): $($_.Exception.Message)"
  }
  finally {
    if ($null -eq $oldPrompt) { Remove-Item Env:\GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue } else { $env:GIT_TERMINAL_PROMPT = $oldPrompt }
    if ($null -eq $oldAskpass) { Remove-Item Env:\GIT_ASKPASS -ErrorAction SilentlyContinue } else { $env:GIT_ASKPASS = $oldAskpass }
  }

  Write-HookLog "committed and pushed to '$branch'."
  exit 0
}
catch {
  # Fail open: don't block Cursor from completing.
  Write-HookLog "error: $($_.Exception.Message)"
  exit 0
}

