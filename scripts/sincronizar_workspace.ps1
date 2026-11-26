<#
.SYNOPSIS
    Copia el workspace versionado de Pana al workspace local de OpenClaw en WSL.

.DESCRIPTION
    Origen:  openclaw\workspace\pana del repositorio.
    Destino: \\wsl$\OpenClawGateway\home\openclaw\.openclaw\workspaces\pana.

    Copia SOUL.md, AGENTS.md, USER.md, IDENTITY.md, las plantillas .example y
    los archivos nuevos. No borra ni sobrescribe MEMORY.md ni la bitacora real
    (memory\*.md que no sean .example). Tampoco copia las semillas
    (MEMORY.semilla.md ni memory\semilla.md): viven solo en el repositorio. Al
    final elimina BOOTSTRAP.md del destino.

.PARAMETER Origen
    Carpeta versionada del workspace. Por defecto, la del repositorio.

.PARAMETER Destino
    Carpeta del workspace dentro de WSL.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sincronizar_workspace.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sincronizar_workspace.ps1 `
        -Destino "C:\ruta\de\ensayo\pana"
#>
[CmdletBinding()]
param(
    [string]$Origen,
    [string]$Destino = '\\wsl$\OpenClawGateway\home\openclaw\.openclaw\workspaces\pana'
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Origen)) {
    $Origen = Join-Path (Split-Path -Parent $PSScriptRoot) 'openclaw\workspace\pana'
}

if (-not (Test-Path -LiteralPath $Origen -PathType Container)) {
    throw "No existe el origen: $Origen"
}

if (-not (Test-Path -LiteralPath $Destino -PathType Container)) {
    throw "No existe el destino: $Destino. Inicia WSL y OpenClaw, o pasa -Destino."
}

$origenRaiz = (Resolve-Path -LiteralPath $Origen).Path.TrimEnd('\')
$destinoRaiz = (Resolve-Path -LiteralPath $Destino).Path.TrimEnd('\')
$copiados = 0
$omitidos = 0

Get-ChildItem -LiteralPath $origenRaiz -Recurse -File | ForEach-Object {
    $archivo = $_
    $relativa = $archivo.FullName.Substring($origenRaiz.Length).TrimStart('\')

    # Las semillas son del repositorio: nunca viajan al workspace del agente.
    if ($archivo.Name -like '*.semilla.md' -or $archivo.Name -eq 'semilla.md') {
        $omitidos++
        return
    }

    # MEMORY.md es local: nunca se copia, se pisa ni se borra.
    if ($archivo.Name -eq 'MEMORY.md') {
        $omitidos++
        return
    }

    # La bitacora real (memory\*.md) es local; solo viajan las plantillas .example.
    if ($relativa -like 'memory\*' -and $archivo.Name -like '*.md' -and
        $archivo.Name -notlike '*.example') {
        $omitidos++
        return
    }

    $destinoArchivo = Join-Path $destinoRaiz $relativa
    $destinoCarpeta = Split-Path -Parent $destinoArchivo
    if (-not (Test-Path -LiteralPath $destinoCarpeta -PathType Container)) {
        New-Item -ItemType Directory -Path $destinoCarpeta -Force | Out-Null
    }

    Copy-Item -LiteralPath $archivo.FullName -Destination $destinoArchivo -Force
    $copiados++
}

$bootstrap = Join-Path $destinoRaiz 'BOOTSTRAP.md'
if (Test-Path -LiteralPath $bootstrap -PathType Leaf) {
    Remove-Item -LiteralPath $bootstrap -Force
    Write-Host 'BOOTSTRAP.md eliminado del destino.'
} else {
    Write-Host 'BOOTSTRAP.md no estaba en el destino.'
}

Write-Host "Workspace sincronizado: $copiados archivos copiados, $omitidos omitidos."
Write-Host "Origen:  $origenRaiz"
Write-Host "Destino: $destinoRaiz"
