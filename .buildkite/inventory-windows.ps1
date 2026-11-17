$ErrorActionPreference = 'Stop'
function Access-Path([string]$Path) {
  $exists = Test-Path -LiteralPath $Path
  $read = $false; $write = $null; $acl = $null
  if ($exists) {
    try { $null = Get-Item -LiteralPath $Path; $acl = (Get-Acl -LiteralPath $Path).AccessToString; $read = $true } catch {}
  }
  return [ordered]@{ path=$Path; exists=$exists; read=$read; write=$write; acl=$acl }
}
$r = [ordered]@{
  utc=[DateTime]::UtcNow.ToString('o'); phase='host-before-compatibility-runtime'
  identity=(& whoami); architecture=$env:PROCESSOR_ARCHITECTURE
  os=(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture)
  environment=[ordered]@{}; executors=@(); search_roots=@(); errors=@(); node_candidates=@(); tool_caches=@(); mise_roots=@()
}
foreach ($k in @('RUNNER_TOOL_CACHE','AGENT_TOOLSDIRECTORY','USERPROFILE','ImageOS','ImageVersion','MISE_DATA_DIR','MISE_INSTALLS_DIR')) {
  $r.environment[$k] = [Environment]::GetEnvironmentVariable($k)
}
$r.machine_tool_cache = [Environment]::GetEnvironmentVariable('RUNNER_TOOL_CACHE','Machine')
$nodes = @{}
$roots = @('C:\actions-runner','C:\runner','C:\runners','C:\actions','C:\a','C:\buildkite-agent','C:\Program Files\GitHub Actions Runner','C:\ProgramData\buildkite-agent','C:\Users\runneradmin','C:\Users\runner','D:\a')
$r.drive_roots = @(Get-PSDrive -PSProvider FileSystem | Select-Object Name,Root)
$r.root_directories = @(Get-ChildItem C:\ -Directory -Force -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
foreach ($root in $roots) {
  $r.search_roots += Access-Path $root
  if (!(Test-Path -LiteralPath $root -PathType Container)) { continue }
  $queue = [Collections.Generic.Queue[object]]::new(); $queue.Enqueue(@($root,0))
  while ($queue.Count -gt 0) {
    $entry=$queue.Dequeue(); $path=[string]$entry[0]; $depth=[int]$entry[1]
    $dirs=@(Get-ChildItem -LiteralPath $path -Directory -Force -ErrorAction SilentlyContinue)
    if ((Split-Path $path -Leaf) -eq 'externals') {
      $r.executors += [ordered]@{ externals=$path; children=@($dirs.Name) }
      foreach ($dir in $dirs) {
        if ($dir.Name -like 'node*') {
          $node=Join-Path $dir.FullName 'bin\node.exe'
          if (Test-Path -LiteralPath $node) { $nodes[$node]='action-executor' }
        }
      }
      continue
    }
    if ($depth -ge 6) { continue }
    foreach ($dir in $dirs) {
      if ($dir.Name -notin @('.git','node_modules','hostedtoolcache','tool-cache','mise','.cache','AppData','builds','cache') -and !($dir.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        $queue.Enqueue(@($dir.FullName,($depth+1)))
      }
    }
  }
}
$cacheRoots=@($env:RUNNER_TOOL_CACHE,$env:AGENT_TOOLSDIRECTORY,'C:\hostedtoolcache\windows','C:\hostedtoolcache','D:\hostedtoolcache') | Where-Object { $_ } | Select-Object -Unique
foreach ($root in $cacheRoots) {
  $cache=Access-Path $root; $cache.entries=@()
  if (Test-Path -LiteralPath $root -PathType Container) {
    foreach ($tool in @(Get-ChildItem -LiteralPath $root -Directory)) {
      $versions=@()
      foreach ($version in @(Get-ChildItem -LiteralPath $tool.FullName -Directory)) {
        $architectures=@()
        foreach ($arch in @(Get-ChildItem -LiteralPath $version.FullName)) {
          if ($arch.PSIsContainer -or $arch.Name -like '*.complete') {
            $architectures += [ordered]@{ name=$arch.Name; directory=[bool]$arch.PSIsContainer }
            if ($tool.Name -eq 'node' -and $arch.PSIsContainer) {
              $node=Join-Path $arch.FullName 'node.exe'
              if (Test-Path -LiteralPath $node) { $nodes[$node]='setup-action-tool-cache' }
            }
          }
        }
        $versions += [ordered]@{ version=$version.Name; architectures_and_markers=$architectures }
      }
      $cache.entries += [ordered]@{ tool=$tool.Name; versions=$versions }
    }
  }
  $r.tool_caches += $cache
}
$pathNode=Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$r.path_node=if ($pathNode) { $pathNode.Source } else { $null }
if ($pathNode -and !$nodes.ContainsKey($pathNode.Source)) { $nodes[$pathNode.Source]='PATH' }
foreach ($path in @($nodes.Keys | Sort-Object)) {
  $item=Access-Path $path; $item.kind=$nodes[$path]
  try { $item.version=(& $path --version | Out-String).Trim(); $item.exit=$LASTEXITCODE; $item.sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() } catch { $item.error=$_.Exception.Message }
  $r.node_candidates += $item
}
foreach ($root in @("$env:USERPROFILE\AppData\Local\mise","$env:USERPROFILE\.local\share\mise",'C:\mise')) { $r.mise_roots += Access-Path $root }
$out=if ($env:INVENTORY_OUTPUT) { $env:INVENTORY_OUTPUT } else { 'windows-inventory.json' }
$json=$r | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText((Join-Path (Get-Location) $out), $json)
Write-Output $json
