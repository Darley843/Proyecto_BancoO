<#
.SYNOPSIS
    Borra los datos de los invitados del agente pana al terminar el evento.

.DESCRIPTION
    Cierra la decision 9 del design de agente-openclaw ("al cerrar el evento se
    borran perfiles, memorias y bitacoras; solo quedan metricas agregadas") para
    la parte que vive del lado de OpenClaw y en el computador de la demo.

    Por defecto corre en modo de prueba: no borra nada y solo muestra cuantas
    sesiones, memorias y archivos se borrarian. Para borrar de verdad hay que
    pasar -Confirmar.

    Pasos, en este orden:

    1. Enumera las sesiones del agente pana con
       "openclaw sessions list --agent pana --limit all --json" y las borra en
       lotes con "openclaw sessions delete <claves...> --agent pana --yes".
       En modo de prueba usa --dry-run y no toca el gateway.

    2. Olvida las memorias derivadas de esas sesiones con
       "openclaw memory forget --agent pana --session <clave>", una clave por
       argumento y en lotes. "memory forget" es offline-only: exige propiedad
       exclusiva del estado; por eso, solo con -Confirmar, el script detiene el
       gateway, ejecuta el olvido, limpia el indice derivado con
       "openclaw memory reset --agent pana --yes" y vuelve a levantar el
       gateway. Si algo falla, el gateway se levanta igual (bloque finally).

       Se prefiere --session por clave y no --since porque borra exactamente lo
       derivado de las sesiones que se acaban de eliminar, sin arrastrar
       memorias de otras sesiones del mismo agente.

    3. Borra los archivos locales de memoria del workspace de WSL:
       MEMORY.md, DREAMS.md y todo el contenido de memory\ (bitacora diaria,
       dreaming y .dreams\session-corpus). Nunca toca los .example ni los
       archivos versionados SOUL.md, AGENTS.md, USER.md e IDENTITY.md.

    4. Borra en Windows data\asistente\trazas\herramientas.jsonl y
       data\evaluacion\inyeccion.json si existen.

    El canal de WhatsApp no se toca: los perfiles, consentimientos y casos son
    de Darley y se borran aparte. El script tampoco lee el token ni imprime el
    contenido de las sesiones; solo cuenta.

.NOTES
    Archivos archivados de las sesiones borradas:

    "openclaw sessions delete" archiva el transcript dentro de la base SQLite
    del agente (openclaw-agent.sqlite, tablas session_transcript_archives y
    session_transcript_cold_archives) y esos archivos retenidos pueden seguir
    siendo elegibles para la busqueda de memoria. "openclaw memory forget"
    borra las memorias y los artefactos derivados de las sesiones indicadas, y
    "openclaw memory reset" limpia el indice derivado y la cache de embeddings
    sin tocar las sesiones.

    En OpenClaw 2026.11.6 no hay un comando que purgue el blob archivado del
    transcript. Ese blob queda local, dentro de WSL, y no sale del equipo. Si
    de verdad hay que purgarlo, el procedimiento manual (no lo hace este
    script) es: detener el gateway con "openclaw daemon stop", respaldar
    openclaw-agent.sqlite, borrar las filas de esas dos tablas por session_id y
    volver a arrancar el gateway. La ruta de la base es
    \home\openclaw\.openclaw\agents\pana\agent\openclaw-agent.sqlite.

.PARAMETER Confirmar
    Borra de verdad. Sin este interruptor el script solo muestra el resumen.

.PARAMETER Distro
    Distribucion de WSL donde corre el gateway. Por defecto OpenClawGateway.

.PARAMETER Agente
    Agente de OpenClaw. Por defecto pana.

.PARAMETER Workspace
    Workspace de Pana dentro de WSL, visto desde Windows. Por defecto
    \\wsl$\OpenClawGateway\home\openclaw\.openclaw\workspaces\pana.

.PARAMETER LoteSesiones
    Claves por llamada a "sessions delete". Por defecto 25.

.PARAMETER LoteMemorias
    Claves por llamada a "memory forget". Por defecto 20.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\limpiar_evento.ps1

    Modo de prueba: muestra cuantas sesiones y archivos se borrarian.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\limpiar_evento.ps1 -Confirmar

    Borra de verdad. Detiene el gateway un momento para olvidar las memorias y
    lo vuelve a levantar al final.
#>
[CmdletBinding()]
param(
    [switch]$Confirmar,
    [string]$Distro = 'OpenClawGateway',
    [string]$Agente = 'pana',
    [string]$Workspace = '\\wsl$\OpenClawGateway\home\openclaw\.openclaw\workspaces\pana',
    [int]$LoteSesiones = 25,
    [int]$LoteMemorias = 20
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RaizRepo = Split-Path -Parent $PSScriptRoot
$ArchivosWindows = @(
    (Join-Path $RaizRepo 'data\asistente\trazas\herramientas.jsonl'),
    (Join-Path $RaizRepo 'data\evaluacion\inyeccion.json')
)
$ArchivosVersionados = @('SOUL.md', 'AGENTS.md', 'USER.md', 'IDENTITY.md')
$Fallos = New-Object System.Collections.Generic.List[string]

function Invoke-OpenClaw {
    <#
        Ejecuta openclaw dentro de WSL y devuelve codigo y salida estandar.
        El error estandar se descarta: nunca se imprime el contenido de una
        sesion y los avisos del servicio ensucian el JSON.
    #>
    param([string[]]$Argumentos)

    $lineas = & wsl -d $Distro -- openclaw @Argumentos 2>$null
    $texto = (@($lineas) | ForEach-Object { [string]$_ }) -join "`n"
    return [pscustomobject]@{
        Codigo = $LASTEXITCODE
        Texto  = $texto
    }
}

function Get-Sesiones {
    <#
        Devuelve las claves y los identificadores de las sesiones del agente.
        Solo se leen key y sessionId; nada del contenido.
    #>
    $resultado = Invoke-OpenClaw -Argumentos @(
        'sessions', 'list', '--agent', $Agente, '--limit', 'all', '--json'
    )
    if ($resultado.Codigo -ne 0) {
        throw "No se pudieron listar las sesiones (codigo $($resultado.Codigo)). Revisa que el gateway responda: wsl -d $Distro -- openclaw health"
    }

    try {
        $datos = $resultado.Texto | ConvertFrom-Json
    } catch {
        throw 'La salida de sessions list no es JSON valido.'
    }

    $sesiones = @()
    if ($null -ne $datos.sessions) {
        $sesiones = @($datos.sessions | Where-Object { $_.key })
    }
    return $sesiones
}

function Test-GatewayArriba {
    <#
        Devuelve $true si el gateway responde. La salida se descarta.
    #>
    $null = & wsl -d $Distro -- openclaw health 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Esperar-Gateway {
    <#
        Espera a que el gateway este arriba o abajo, como maximo los segundos
        indicados. Devuelve $true si llego al estado pedido.
    #>
    param(
        [bool]$Arriba,
        [int]$Segundos = 45
    )

    for ($i = 0; $i -lt $Segundos; $i++) {
        if ((Test-GatewayArriba) -eq $Arriba) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-ArchivosWorkspace {
    <#
        Lista solo los archivos de memoria derivados del workspace. Protege los
        .example y los cuatro archivos versionados.
    #>
    $lista = New-Object System.Collections.Generic.List[string]

    foreach ($nombre in @('MEMORY.md', 'DREAMS.md')) {
        $ruta = Join-Path $Workspace $nombre
        if (Test-Path -LiteralPath $ruta -PathType Leaf) {
            $lista.Add($ruta)
        }
    }

    $carpetaMemoria = Join-Path $Workspace 'memory'
    if (Test-Path -LiteralPath $carpetaMemoria -PathType Container) {
        Get-ChildItem -LiteralPath $carpetaMemoria -Recurse -File -Force |
            Where-Object {
                $_.Name -notlike '*.example' -and
                ($_.Extension -eq '.md' -or $_.Extension -eq '.txt')
            } |
            ForEach-Object { $lista.Add($_.FullName) }
    }

    $limpias = New-Object System.Collections.Generic.List[string]
    foreach ($ruta in $lista) {
        $nombre = Split-Path -Leaf $ruta
        if ($ArchivosVersionados -contains $nombre) { continue }
        if ($nombre -like '*.example') { continue }
        $limpias.Add($ruta)
    }
    return $limpias
}

function Get-RutaCorta {
    <#
        Acorta una ruta del workspace para mostrarla en el resumen.
    #>
    param([string]$Ruta)

    if ($Ruta.StartsWith($Workspace, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $Ruta.Substring($Workspace.Length).TrimStart('\')
    }
    return $Ruta
}

Write-Host ''
Write-Host 'Limpieza de los datos de los invitados (agente pana)'
if ($Confirmar) {
    Write-Host 'Modo: BORRADO REAL (-Confirmar)' -ForegroundColor Yellow
} else {
    Write-Host 'Modo: PRUEBA (no se borra nada; usa -Confirmar para borrar)' -ForegroundColor Cyan
}
Write-Host "Distribucion WSL: $Distro"
Write-Host "Agente: $Agente"
Write-Host ''

# ---------------------------------------------------------------------------
#  1. Sesiones del agente
# ---------------------------------------------------------------------------

Write-Host '1. Sesiones del agente'
if (-not (Test-GatewayArriba)) {
    Write-Host '   El gateway no responde. Enciendelo y vuelve a intentarlo:' -ForegroundColor Red
    Write-Host "   wsl -d $Distro -- openclaw daemon start"
    exit 1
}

$sesiones = @(Get-Sesiones)
$todasLasClaves = @($sesiones | ForEach-Object { [string]$_.key })
$clavePrincipal = "agent:${Agente}:main"
$claves = @($todasLasClaves | Where-Object { $_ -ne $clavePrincipal })

$protegidas = $todasLasClaves.Count - $claves.Count
Write-Host "   Sesiones encontradas: $($todasLasClaves.Count)"
if ($protegidas -gt 0) {
    Write-Host "   Sesion principal protegida por OpenClaw (no se borra): $protegidas"
}

$SesionesBorradas = 0
$LotesConError = 0

if ($claves.Count -gt 0) {
    for ($inicio = 0; $inicio -lt $claves.Count; $inicio += $LoteSesiones) {
        $fin = [Math]::Min($inicio + $LoteSesiones, $claves.Count) - 1
        $lote = @($claves[$inicio..$fin])
        $numeroLote = [int]($inicio / $LoteSesiones) + 1
        $totalLotes = [Math]::Ceiling($claves.Count / $LoteSesiones)

        $argumentos = @('sessions', 'delete') + $lote + @(
            '--agent', $Agente, '--yes', '--json'
        )
        if (-not $Confirmar) { $argumentos += '--dry-run' }

        $resultado = Invoke-OpenClaw -Argumentos $argumentos

        $contadas = 0
        $fallidas = 0
        $datos = $null
        try {
            $datos = $resultado.Texto | ConvertFrom-Json
        } catch {
            $datos = $null
        }

        if ($null -ne $datos -and $null -ne $datos.results) {
            if ($Confirmar) {
                $contadas = @($datos.results | Where-Object { $_.ok -eq $true }).Count
            } else {
                $contadas = @($datos.results | Where-Object {
                    $_.status -eq 'would_delete'
                }).Count
            }
            $fallidas = @($datos.results | Where-Object {
                $_.ok -eq $false -and $_.key -ne $clavePrincipal
            }).Count
        } elseif ($resultado.Codigo -eq 0) {
            # Version sin "results": el lote exitoso cuenta completo.
            $contadas = $lote.Count
        }

        if ($fallidas -gt 0) {
            Write-Host "   Lote ${numeroLote}: $fallidas clave(s) no se pudieron procesar" -ForegroundColor Yellow
            $Fallos.Add("sessions delete lote $numeroLote ($fallidas claves)")
        }

        if ($resultado.Codigo -ne 0 -and $contadas -eq 0) {
            Write-Host "   Lote ${numeroLote}: error (codigo $($resultado.Codigo))" -ForegroundColor Red
            $LotesConError++
            $Fallos.Add("sessions delete lote $numeroLote")
            continue
        }

        $SesionesBorradas += $contadas
        if ($Confirmar) {
            Write-Host "   Lote $numeroLote/$totalLotes`: $contadas sesiones borradas"
        } else {
            Write-Host "   Lote $numeroLote/$totalLotes`: $contadas sesiones se borrarian"
        }
    }
} else {
    Write-Host '   No hay sesiones que borrar.'
}

# ---------------------------------------------------------------------------
#  2. Memorias derivadas
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host '2. Memorias derivadas'

$SesionesOlvidadas = 0
$IndiceLimpiado = $false

if ($claves.Count -eq 0) {
    Write-Host '   No hay sesiones de las que olvidar memorias.'
} elseif (-not $Confirmar) {
    Write-Host "   Se olvidarian las memorias derivadas de $($claves.Count) sesiones."
    Write-Host '   openclaw memory forget es offline-only: con -Confirmar el script'
    Write-Host '   detiene el gateway, olvida, limpia el indice y lo vuelve a levantar.'
} else {
    Write-Host '   Deteniendo el gateway para tener propiedad exclusiva del estado...'
    $parada = Invoke-OpenClaw -Argumentos @('daemon', 'stop')
    if ($parada.Codigo -ne 0) {
        Write-Host '   No se pudo detener el gateway.' -ForegroundColor Red
        $Fallos.Add('daemon stop')
    } elseif (-not (Esperar-Gateway -Arriba $false -Segundos 45)) {
        Write-Host '   El gateway sigue respondiendo; no se toca la memoria.' -ForegroundColor Red
        $Fallos.Add('gateway no se detuvo')
    } else {
        try {
            for ($inicio = 0; $inicio -lt $claves.Count; $inicio += $LoteMemorias) {
                $fin = [Math]::Min($inicio + $LoteMemorias, $claves.Count) - 1
                $lote = @($claves[$inicio..$fin])

                $argumentos = @('memory', 'forget', '--agent', $Agente)
                foreach ($clave in $lote) {
                    $argumentos += @('--session', $clave)
                }

                $resultado = Invoke-OpenClaw -Argumentos $argumentos
                if ($resultado.Codigo -eq 0) {
                    $SesionesOlvidadas += $lote.Count
                } else {
                    $Fallos.Add("memory forget lote $([int]($inicio / $LoteMemorias) + 1)")
                    Write-Host "   Olvido: fallo el lote $([int]($inicio / $LoteMemorias) + 1) (codigo $($resultado.Codigo))" -ForegroundColor Red
                }
            }

            Write-Host '   Limpiando el indice derivado y la cache de embeddings...'
            $limpieza = Invoke-OpenClaw -Argumentos @(
                'memory', 'reset', '--agent', $Agente, '--yes'
            )
            if ($limpieza.Codigo -eq 0) {
                $IndiceLimpiado = $true
            } else {
                Write-Host "   No se pudo limpiar el indice (codigo $($limpieza.Codigo))." -ForegroundColor Yellow
            }
        } finally {
            Write-Host '   Volviendo a levantar el gateway...'
            $arranque = Invoke-OpenClaw -Argumentos @('daemon', 'start')
            if ($arranque.Codigo -ne 0) {
                Write-Host '   No se pudo arrancar el gateway: revisalo a mano.' -ForegroundColor Red
                $Fallos.Add('daemon start')
            } elseif (-not (Esperar-Gateway -Arriba $true -Segundos 60)) {
                Write-Host '   El gateway no responde todavia: revisalo a mano.' -ForegroundColor Red
                $Fallos.Add('gateway no volvio')
            } else {
                Write-Host '   Gateway arriba.'
            }
        }
    }
}

# ---------------------------------------------------------------------------
#  3. Workspace de WSL
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host '3. Workspace de Pana en WSL'

$ArchivosWorkspace = @(Get-ArchivosWorkspace)
$ArchivosWorkspaceBorrados = 0

if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
    Write-Host "   No existe el workspace: $Workspace" -ForegroundColor Yellow
} elseif ($ArchivosWorkspace.Count -eq 0) {
    Write-Host '   No hay archivos de memoria que borrar.'
} else {
    foreach ($ruta in $ArchivosWorkspace) {
        $corta = Get-RutaCorta -Ruta $ruta
        if ($Confirmar) {
            try {
                Remove-Item -LiteralPath $ruta -Force
                $ArchivosWorkspaceBorrados++
                Write-Host "   Borrado: $corta"
            } catch {
                Write-Host "   No se pudo borrar: $corta" -ForegroundColor Red
                $Fallos.Add("workspace $corta")
            }
        } else {
            Write-Host "   Se borraria: $corta"
            $ArchivosWorkspaceBorrados++
        }
    }
}

# ---------------------------------------------------------------------------
#  4. Archivos de Windows
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host '4. Archivos locales de Windows'

$ArchivosWindowsBorrados = 0
foreach ($ruta in $ArchivosWindows) {
    $relativa = $ruta.Substring($RaizRepo.Length).TrimStart('\')
    if (-not (Test-Path -LiteralPath $ruta -PathType Leaf)) {
        Write-Host "   No existe: $relativa"
        continue
    }

    if ($Confirmar) {
        try {
            Remove-Item -LiteralPath $ruta -Force
            $ArchivosWindowsBorrados++
            Write-Host "   Borrado: $relativa"
        } catch {
            Write-Host "   No se pudo borrar: $relativa" -ForegroundColor Red
            $Fallos.Add("windows $relativa")
        }
    } else {
        Write-Host "   Se borraria: $relativa"
        $ArchivosWindowsBorrados++
    }
}

# ---------------------------------------------------------------------------
#  5. Resumen
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host 'RESUMEN'
if ($Confirmar) {
    Write-Host "  Sesiones borradas:              $SesionesBorradas de $($claves.Count)"
    Write-Host "  Sesiones con memoria olvidada:  $SesionesOlvidadas"
    Write-Host "  Indice derivado limpiado:       $(if ($IndiceLimpiado) { 'si' } else { 'no' })"
    Write-Host "  Archivos borrados en WSL:       $ArchivosWorkspaceBorrados"
    Write-Host "  Archivos borrados en Windows:   $ArchivosWindowsBorrados"
} else {
    Write-Host "  Sesiones que se borrarian:      $SesionesBorradas de $($claves.Count)"
    Write-Host "  Memorias que se olvidarian:     $($claves.Count) sesiones"
    Write-Host "  Archivos de WSL que se borrarian: $ArchivosWorkspaceBorrados"
    Write-Host "  Archivos de Windows que se borrarian: $ArchivosWindowsBorrados"
    Write-Host ''
    Write-Host '  No se borro nada. Para borrar de verdad:'
    Write-Host '    make limpiar-evento CONFIRMAR=1'
}
Write-Host ''
Write-Host 'Nota 1: los archivos archivados de las sesiones borradas quedan en la'
Write-Host 'base SQLite del agente dentro de WSL (session_transcript_archives y'
Write-Host 'session_transcript_cold_archives). memory forget borra lo derivado y'
Write-Host 'memory reset limpia el indice; OpenClaw 2026.11.6 no expone un comando'
Write-Host 'para purgar el blob archivado. Queda local y no sale del equipo; el'
Write-Host 'procedimiento manual esta en la cabecera del script.'
Write-Host ''
Write-Host 'Nota 2: el canal de WhatsApp no se toca. Los perfiles, consentimientos'
Write-Host 'y casos son de Darley y se borran aparte.'
Write-Host ''

if ($Fallos.Count -gt 0) {
    Write-Host "Termino con $($Fallos.Count) fallo(s):" -ForegroundColor Red
    foreach ($fallo in $Fallos) { Write-Host "  - $fallo" }
    exit 1
}

if (-not $Confirmar) {
    Write-Host 'Modo de prueba terminado.'
}
exit 0
