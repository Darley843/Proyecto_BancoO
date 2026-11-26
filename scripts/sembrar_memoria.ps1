<#
.SYNOPSIS
    Siembra la memoria y la bitacora de Pana desde las semillas versionadas.

.DESCRIPTION
    Escribe dos archivos legibles y editables en el workspace de OpenClaw:

      - MEMORY.md        a partir de openclaw\workspace\pana\MEMORY.semilla.md
      - memory\<fecha>.md a partir de openclaw\workspace\pana\memory\semilla.md

    Las semillas se versionan y no llevan datos personales; el script solo
    reemplaza {{FECHA}} en la bitacora y comprueba que el resultado no parezca
    tener un correo ni un numero de siete digitos o mas. Sirve para regenerar
    los archivos reales despues de `make limpiar-evento` y para restaurar el
    contenido por defecto si alguien lo edito por error.

    No sobrescribe archivos existentes salvo con -Forzar: asi una edicion a
    mano no se pierde por accidente. Los archivos reales siguen fuera de Git.

.PARAMETER Fecha
    Fecha de la bitacora, en formato AAAA-MM-DD. Por defecto, hoy.

.PARAMETER Origen
    Carpeta versionada del workspace. Por defecto, la del repositorio.

.PARAMETER Destino
    Workspace de OpenClaw dentro de WSL.

.PARAMETER Forzar
    Sobrescribe MEMORY.md y la bitacora si ya existen.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sembrar_memoria.ps1

    Siembra la memoria y la bitacora de hoy.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sembrar_memoria.ps1 `
        -Fecha 2026-11-26 -Forzar

    Vuelve a dejar los dos archivos como las semillas, con esa fecha.
#>
[CmdletBinding()]
param(
    [string]$Fecha = (Get-Date -Format 'yyyy-MM-dd'),
    [string]$Origen,
    [string]$Destino = '\\wsl$\OpenClawGateway\home\openclaw\.openclaw\workspaces\pana',
    [switch]$Forzar
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ([string]::IsNullOrWhiteSpace($Origen)) {
    $Origen = Join-Path (Split-Path -Parent $PSScriptRoot) 'openclaw\workspace\pana'
}

if ($Fecha -notmatch '^\d{4}-\d{2}-\d{2}$') {
    throw "Fecha invalida: $Fecha. Usa el formato AAAA-MM-DD."
}

if (-not (Test-Path -LiteralPath $Origen -PathType Container)) {
    throw "No existe el origen: $Origen"
}

if (-not (Test-Path -LiteralPath $Destino -PathType Container)) {
    throw "No existe el destino: $Destino. Inicia WSL y OpenClaw, o pasa -Destino."
}

$Semillas = @(
    [pscustomobject]@{
        Semilla = Join-Path $Origen 'MEMORY.semilla.md'
        Destino = Join-Path $Destino 'MEMORY.md'
    },
    [pscustomobject]@{
        Semilla = Join-Path (Join-Path $Origen 'memory') 'semilla.md'
        Destino = Join-Path (Join-Path $Destino 'memory') "$Fecha.md"
    }
)

function Assert-SinDatosPersonales {
    <#
        Falla si el texto sembrado parece tener un correo o un numero de siete
        digitos o mas (telefono, documento o monto sin separadores). Nunca
        imprime el valor encontrado, solo el nombre del patron y la semilla.
    #>
    param(
        [string]$Texto,
        [string]$Ruta
    )

    $patrones = @(
        @{ Nombre = 'correo'; Expresion = '[\w.+-]+@[\w-]+\.[\w.-]+' },
        @{ Nombre = 'numero de siete digitos o mas'; Expresion = '\d{7,}' }
    )

    foreach ($patron in $patrones) {
        if ($Texto -match $patron.Expresion) {
            throw "La semilla $Ruta parece tener un $($patron.Nombre). No se escribe nada: corrige la semilla."
        }
    }
}

$faltan = @($Semillas | Where-Object {
    -not (Test-Path -LiteralPath $_.Semilla -PathType Leaf)
})
if ($faltan.Count -gt 0) {
    $rutas = ($faltan | ForEach-Object { $_.Semilla }) -join ', '
    throw "Faltan semillas: $rutas"
}

$existentes = @($Semillas | Where-Object {
    (Test-Path -LiteralPath $_.Destino -PathType Leaf) -and -not $Forzar
})
if ($existentes.Count -gt 0) {
    $rutas = ($existentes | ForEach-Object { $_.Destino }) -join ', '
    throw "Ya existen: $rutas. Edita esos archivos a mano o pasa -Forzar para reemplazarlos desde las semillas."
}

$escritas = 0
foreach ($par in $Semillas) {
    $texto = [System.IO.File]::ReadAllText($par.Semilla)
    $texto = $texto -replace "`r`n", "`n"
    $texto = $texto.Replace('{{FECHA}}', $Fecha)

    Assert-SinDatosPersonales -Texto $texto -Ruta $par.Semilla

    $carpeta = Split-Path -Parent $par.Destino
    if (-not (Test-Path -LiteralPath $carpeta -PathType Container)) {
        New-Item -ItemType Directory -Path $carpeta -Force | Out-Null
    }

    [System.IO.File]::WriteAllText(
        $par.Destino,
        $texto,
        (New-Object System.Text.UTF8Encoding($false))
    )
    $escritas++
    Write-Host "Escrito: $($par.Destino)"
}

Write-Host ''
Write-Host "Memoria sembrada: $escritas archivos desde $Origen"
Write-Host 'Se editan a mano en el workspace. Al cerrar el evento se borran los'
Write-Host 'archivos reales (no las semillas) con: make limpiar-evento CONFIRMAR=1'
