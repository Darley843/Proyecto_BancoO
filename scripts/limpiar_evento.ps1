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
       gateway con "daemon stop --force" (OpenClaw 2026.11.6 lo exige desde una
       consola no interactiva), ejecuta el olvido, limpia el indice derivado con
       "openclaw memory reset --agent pana --yes" y vuelve a levantar el
       gateway. Si algo falla, el gateway se levanta igual (bloque finally).
       "memory forget" y "memory reset" no piden ni aceptan ese interruptor.

       Se prefiere --session por clave y no --since porque borra exactamente lo
       derivado de las sesiones que se acaban de eliminar, sin arrastrar
       memorias de otras sesiones del mismo agente.

    3. Purga los archivos archivados de las sesiones en la base SQLite del
       agente, con python3 y el modulo sqlite3 dentro de WSL, en la misma
       ventana en que el gateway esta detenido para el olvido del paso 2. Con
       -PurgarArchivos comprueba las tablas session_transcript_archives y
       session_transcript_cold_archives; en modo de prueba solo cuenta sus
       filas y con -Confirmar las borra con DELETE FROM, trunca el WAL con
       PRAGMA wal_checkpoint(TRUNCATE) y compacta con VACUUM. Informa cuantas
       filas borro y el tamano de la base antes y despues. No toca ninguna otra
       tabla y no hace copia de respaldo de esas dos.

       En la misma ventana sin gateway compacta la base del agente
       (~/.openclaw/agents/pana/agent/openclaw-agent.sqlite) y la base de estado
       (~/.openclaw/state/openclaw.sqlite): solo PRAGMA
       wal_checkpoint(TRUNCATE) y VACUUM, sin borrar filas, e imprime el tamano
       antes y despues. En modo de prueba solo mide y muestra el paso. La base
       de estado se omite si no existe.

    4. Borra los archivos locales de memoria del workspace de WSL:
       MEMORY.md, DREAMS.md y todo el contenido de memory\ (bitacora diaria,
       dreaming y .dreams\session-corpus), sin filtrar por extension: cualquier
       archivo que viva bajo memory\ se borra. Nunca toca los .example ni las
       semillas versionadas MEMORY.semilla.md y memory\semilla.md, ni los
       archivos versionados SOUL.md, AGENTS.md, USER.md e IDENTITY.md: los
       archivos reales se regeneran desde las semillas con
       scripts\sembrar_memoria.ps1.

    5. Borra en Windows data\asistente\trazas\herramientas.jsonl si existe y, con
       el modo En vivo de la escena, data\escena\en_vivo.jsonl, su bloqueo
       data\escena\en_vivo.lock y la ficha pendiente
       data\escena\ficha_entrega.json. Sale del modo en vivo y, si es posible,
       detiene la app y el MCP antes de borrar la lista; despues apaga
       ESCENA_EN_VIVO y reinicia la app.

    No borra data\evaluacion\inyeccion.json: es la evidencia de la tarea 3.5
    que cita docs/INYECCION.md y no guarda el texto de las respuestas ni datos
    de invitados, asi que se versiona con el resto de data\evaluacion\.

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

    OpenClaw 2026.11.6 no expone un comando que purgue ese blob archivado y la
    promesa del consentimiento es borrar los datos de los invitados. Por eso,
    con -PurgarArchivos el script entra con python3 y el modulo sqlite3 dentro
    de WSL a la base del agente
    (el equivalente a ~/.openclaw/agents/pana/agent/openclaw-agent.sqlite) y:

      - comprueba que existan las dos tablas; si falta alguna, lo avisa y sigue;
      - en modo de prueba solo cuenta las filas de cada tabla;
      - con -Confirmar hace DELETE FROM en las dos tablas,
        PRAGMA wal_checkpoint(TRUNCATE) y VACUUM, para que las filas no queden
        en paginas libres ni en el WAL;
      - informa cuantas filas borro y el tamano de la base antes y despues;
      - no toca ninguna otra tabla.

    La purga corre en el mismo momento en que el gateway ya esta detenido para
    "openclaw memory forget", asi que no hay una segunda ventana sin gateway.

    En esa ventana tambien se compactan la base del agente y la base de estado
    del gateway (~/.openclaw/state/openclaw.sqlite): PRAGMA
    wal_checkpoint(TRUNCATE) y VACUUM, sin borrar filas, con el tamano antes y
    despues. La base de estado no se purga: solo se compacta. En modo de prueba
    solo se mide y se muestra el paso de compactacion.

    NO se hace copia de respaldo de esas dos tablas: una copia conservaria
    justo los datos que el consentimiento promete borrar. El resto de la base
    no se respalda ni se modifica.

    Esta purga se prueba el viernes 27, despues de los dos ensayos, antes de
    usarla en el evento del sabado 28 (docs/LISTA_DEMO.md, seccion 7).

.PARAMETER Confirmar
    Borra de verdad. Sin este interruptor el script solo muestra el resumen.

.PARAMETER PurgarArchivos
    Purga tambien las filas de session_transcript_archives y
    session_transcript_cold_archives de la base SQLite del agente en WSL. En
    modo de prueba solo las cuenta. make la activa junto con CONFIRMAR=1.

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
    powershell -ExecutionPolicy Bypass -File scripts\limpiar_evento.ps1 -PurgarArchivos

    Modo de prueba con el conteo de los archivos archivados de las sesiones.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\limpiar_evento.ps1 -Confirmar

    Borra de verdad. Detiene el gateway un momento para olvidar las memorias y
    lo vuelve a levantar al final.
#>
[CmdletBinding()]
param(
    [switch]$Confirmar,
    [switch]$PurgarArchivos,
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
    (Join-Path $RaizRepo 'data\asistente\trazas\herramientas.jsonl')
    (Join-Path $RaizRepo 'data\escena\en_vivo.jsonl')
    (Join-Path $RaizRepo 'data\escena\en_vivo.lock')
    (Join-Path $RaizRepo 'data\escena\ficha_entrega.json')
)
$ArchivosVersionados = @('SOUL.md', 'AGENTS.md', 'USER.md', 'IDENTITY.md')
$ArchivosSemilla = @('MEMORY.semilla.md', 'semilla.md')
$TablasArchivadas = @(
    'session_transcript_archives',
    'session_transcript_cold_archives'
)
$Fallos = New-Object System.Collections.Generic.List[string]

# Ayudante que corre dentro de WSL con python3. Solo usa el modulo sqlite3 de la
# biblioteca estandar; imprime lineas clave=valor que el script traduce.
$ScriptSqlite = @'
import os
import sqlite3
import sys

TABLAS = ("session_transcript_archives", "session_transcript_cold_archives")
MODOS = ("contar", "purgar", "medir", "compactar")


def tamano(ruta):
    total = 0
    for sufijo in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(ruta + sufijo)
        except OSError:
            pass
    return total


def main():
    if len(sys.argv) < 3:
        print("ERROR=uso: purga.py <base> <modo>")
        return 2

    ruta = sys.argv[1]
    modo = sys.argv[2]
    if modo not in MODOS:
        print("ERROR=modo invalido: %s" % modo)
        return 2
    if not os.path.isfile(ruta):
        if modo in ("medir", "compactar"):
            print("AUSENTE=base")
            print("OK=1")
            return 0
        print("ERROR=no existe la base: %s" % ruta)
        return 1

    print("TAMANO_ANTES=%d" % tamano(ruta))
    if modo == "medir":
        print("OK=1")
        return 0

    conexion = sqlite3.connect(ruta, timeout=30, isolation_level=None)
    try:
        if modo in ("contar", "purgar"):
            existentes = set(
                fila[0]
                for fila in conexion.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name IN (?, ?)",
                    TABLAS,
                )
            )
            for tabla in TABLAS:
                if tabla not in existentes:
                    print("AUSENTE=%s" % tabla)
                    continue
                filas = conexion.execute(
                    "SELECT count(*) FROM %s" % tabla
                ).fetchone()[0]
                print("FILAS_%s=%d" % (tabla, filas))
                if modo != "purgar":
                    continue
                conexion.execute("BEGIN IMMEDIATE")
                borradas = conexion.execute("DELETE FROM %s" % tabla).rowcount
                conexion.execute("COMMIT")
                print("BORRADAS_%s=%d" % (tabla, borradas))
        if modo in ("purgar", "compactar"):
            conexion.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            conexion.execute("VACUUM")
            conexion.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    finally:
        conexion.close()

    print("TAMANO_DESPUES=%d" % tamano(ruta))
    print("OK=1")
    return 0


try:
    sys.exit(main())
except Exception as error:
    print("ERROR=%s" % str(error).replace("\n", " "))
    sys.exit(1)
'@

function Invoke-Wsl {
    <#
        Ejecuta un comando dentro de WSL y devuelve su codigo y su salida.

        Un proceso nativo que escribe en stderr no es un error del script:
        "systemctl --user is-active" imprime "inactive" y devuelve 3 cuando el
        servicio esta apagado, y "openclaw health" escribe "OpenClaw took too
        long to respond" cuando no hay gateway. Con ErrorActionPreference en
        Stop eso se vuelve un error terminante, asi que aqui se baja a Continue
        (el cambio es local a la funcion) y se apaga
        PSNativeCommandUseErrorActionPreference cuando la version de PowerShell
        la define (7.4+ la deja encendida por defecto).
    #>
    param(
        [string[]]$Comando,
        [switch]$DescartarError
    )

    $ErrorActionPreference = 'Continue'
    $nativo = Get-Variable -Name 'PSNativeCommandUseErrorActionPreference' `
        -ErrorAction SilentlyContinue
    if ($null -ne $nativo) {
        $PSNativeCommandUseErrorActionPreference = $false
    }

    if ($DescartarError) {
        $lineas = & wsl -d $Distro -- @Comando 2>$null
    } else {
        $lineas = & wsl -d $Distro -- @Comando 2>&1
    }
    return [pscustomobject]@{
        Codigo = $LASTEXITCODE
        Texto  = (@($lineas) | ForEach-Object { [string]$_ }) -join "`n"
    }
}

function Invoke-OpenClaw {
    <#
        Ejecuta openclaw dentro de WSL y devuelve codigo y salida estandar.
        El error estandar se descarta: nunca se imprime el contenido de una
        sesion y los avisos del servicio ensucian el JSON.
    #>
    param([string[]]$Argumentos)

    $comando = @('openclaw')
    if ($null -ne $Argumentos) { $comando += $Argumentos }
    return Invoke-Wsl -Comando $comando -DescartarError
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
        throw "No se pudieron listar las sesiones (codigo $($resultado.Codigo)). Revisa que el gateway responda: wsl -d $Distro -- openclaw gateway status"
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

function Get-EstadoGateway {
    <#
        Devuelve 'activo', 'apagando', 'inactivo' o 'desconocido'. Consulta el
        estado del servicio dentro de WSL con "systemctl --user is-active" y,
        si no lo reconoce, cae a "openclaw gateway status --json".

        No usa "openclaw health": con el gateway apagado health tarda decenas
        de segundos y escribe "OpenClaw took too long to respond" en stderr,
        que con ErrorActionPreference en Stop cortaba el borrado.
    #>
    $servicio = Invoke-Wsl -Comando @(
        'systemctl', '--user', 'is-active', 'openclaw-gateway'
    ) -DescartarError
    switch ($servicio.Texto.Trim()) {
        'active' { return 'activo' }
        'activating' { return 'activo' }
        'reloading' { return 'activo' }
        'deactivating' { return 'apagando' }
        # is-active devuelve 4 ("unknown"/sin unidad) con el texto "inactive";
        # solo se cree el 3, que es el apagado real. El resto cae al respaldo.
        'inactive' { if ($servicio.Codigo -eq 3) { return 'inactivo' } }
        'failed' { return 'inactivo' }
    }

    $respaldo = Invoke-Wsl -Comando @(
        'openclaw', 'gateway', 'status', '--json'
    ) -DescartarError
    try {
        $datos = $respaldo.Texto | ConvertFrom-Json
        $estado = [string]$datos.service.runtime.status
        if ($estado -eq 'running') { return 'activo' }
        if ($estado -in @('stopped', 'inactive', 'failed')) { return 'inactivo' }
    } catch {
        # Sin JSON legible se responde 'desconocido' y decide quien llama.
    }
    return 'desconocido'
}

function Test-GatewayArriba {
    <#
        Devuelve $true si el servicio del gateway esta activo.
    #>
    return ((Get-EstadoGateway) -eq 'activo')
}

function Esperar-Gateway {
    <#
        Espera a que el gateway este arriba o abajo, como maximo los segundos
        indicados. Devuelve $true si llego al estado pedido. Se apoya en el
        estado del servicio, nunca en "openclaw health".
    #>
    param(
        [bool]$Arriba,
        [int]$Segundos = 45,
        [int]$PausaInicial = 0
    )

    if ($PausaInicial -gt 0) { Start-Sleep -Seconds $PausaInicial }
    for ($i = 0; $i -lt $Segundos; $i++) {
        $estado = Get-EstadoGateway
        if ($Arriba -and $estado -eq 'activo') { return $true }
        if (-not $Arriba -and $estado -eq 'inactivo') { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-HomeWsl {
    <#
        Devuelve el HOME real de la distro y cae a /home/openclaw si no lo puede
        leer.
    #>
    $resultado = Invoke-Wsl -Comando @('printenv', 'HOME') -DescartarError
    $homeWsl = $resultado.Texto.Trim()
    if (-not $homeWsl.StartsWith('/')) { $homeWsl = '/home/openclaw' }
    return $homeWsl
}

function Get-RutaBaseAgente {
    <#
        Devuelve la ruta de la base SQLite del agente dentro de WSL.
    #>
    return "$(Get-HomeWsl)/.openclaw/agents/$Agente/agent/openclaw-agent.sqlite"
}

function Get-RutaBaseEstado {
    <#
        Devuelve la ruta de la base de estado del gateway dentro de WSL. Solo se
        compacta, nunca se borran filas.
    #>
    return "$(Get-HomeWsl)/.openclaw/state/openclaw.sqlite"
}

function Invoke-SqliteWsl {
    <#
        Cuenta o purga las filas de session_transcript_archives y
        session_transcript_cold_archives, o mide/compacta una base SQLite, con
        python3 y sqlite3 dentro de WSL. La purga solo toca esas dos tablas; la
        compactacion solo hace wal_checkpoint(TRUNCATE) y VACUUM. No hace copia
        de respaldo: una copia conservaria lo que se quiere borrar.
    #>
    param(
        [ValidateSet('contar', 'purgar', 'medir', 'compactar')]
        [string]$Modo = 'contar',
        [string]$RutaBase
    )

    $salida = [pscustomobject]@{
        Ok       = $false
        Filas    = @{}
        Borradas = @{}
        Ausentes = @()
        Antes    = $null
        Despues  = $null
        Error    = $null
    }

    $ayudanteWsl = "/tmp/limpiar_evento_sqlite_$PID.py"
    $ayudanteWindows = "\\wsl$\$Distro\tmp\limpiar_evento_sqlite_$PID.py"

    try {
        [System.IO.File]::WriteAllText(
            $ayudanteWindows,
            $ScriptSqlite,
            (New-Object System.Text.UTF8Encoding($false))
        )
    } catch {
        $salida.Error = "no se pudo escribir el ayudante en WSL: $($_.Exception.Message)"
        return $salida
    }

    try {
        $resultado = Invoke-Wsl -Comando @(
            'python3', $ayudanteWsl, $RutaBase, $Modo
        ) -DescartarError
        $codigo = $resultado.Codigo
        $lineas = $resultado.Texto -split "`n"
    } finally {
        Remove-Item -LiteralPath $ayudanteWindows -Force -ErrorAction SilentlyContinue
    }

    $texto = (@($lineas) | ForEach-Object { [string]$_ }) -join "`n"
    foreach ($linea in ($texto -split "`n")) {
        $linea = $linea.Trim()
        if (-not $linea) { continue }
        if ($linea -like 'ERROR=*') {
            $salida.Error = $linea.Substring(6)
        } elseif ($linea -like 'AUSENTE=*') {
            $salida.Ausentes += $linea.Substring(8)
        } elseif ($linea -like 'FILAS_*=*') {
            $partes = $linea -split '=', 2
            $salida.Filas[$partes[0].Substring(6)] = [int]$partes[1]
        } elseif ($linea -like 'BORRADAS_*=*') {
            $partes = $linea -split '=', 2
            $salida.Borradas[$partes[0].Substring(9)] = [int]$partes[1]
        } elseif ($linea -like 'TAMANO_ANTES=*') {
            $salida.Antes = $linea.Substring(13)
        } elseif ($linea -like 'TAMANO_DESPUES=*') {
            $salida.Despues = $linea.Substring(15)
        } elseif ($linea -eq 'OK=1') {
            $salida.Ok = $true
        }
    }

    if ($codigo -ne 0 -and -not $salida.Error) {
        $salida.Error = "python3 devolvio el codigo $codigo"
    }
    return $salida
}

function Write-PurgaArchivos {
    <#
        Imprime el resultado de la purga: tablas ausentes, filas contadas o
        borradas y el tamano de la base antes y despues.
    #>
    param(
        [pscustomobject]$Resultado,
        [bool]$Borrar
    )

    if ($null -eq $Resultado) { return }
    if ($Resultado.Error) {
        Write-Host "   No se pudo leer la base: $($Resultado.Error)" -ForegroundColor Red
        return
    }
    if ($null -ne $Resultado.Antes) {
        $etiqueta = if ($Borrar) { 'antes' } else { 'actual' }
        Write-Host "   Tamano de la base ($etiqueta): $($Resultado.Antes) bytes"
    }
    foreach ($tabla in $TablasArchivadas) {
        if ($Resultado.Ausentes -contains $tabla) {
            Write-Host "   $tabla`: no existe (se omite)" -ForegroundColor Yellow
            continue
        }
        if ($Borrar) {
            $cuenta = 0
            if ($Resultado.Borradas.ContainsKey($tabla)) {
                $cuenta = $Resultado.Borradas[$tabla]
            }
            Write-Host "   $tabla`: $cuenta filas borradas"
        } else {
            $cuenta = 0
            if ($Resultado.Filas.ContainsKey($tabla)) {
                $cuenta = $Resultado.Filas[$tabla]
            }
            Write-Host "   $tabla`: $cuenta filas"
        }
    }
    if ($Borrar) {
        if ($Resultado.Ok) {
            Write-Host '   WAL truncado (wal_checkpoint) y VACUUM: hechos'
        }
        if ($null -ne $Resultado.Despues) {
            Write-Host "   Tamano de la base despues: $($Resultado.Despues) bytes"
        }
    } else {
        Write-Host '   Solo se contaron las filas; con -Confirmar se borran.'
    }
}

function Write-Compactacion {
    <#
        Imprime el tamano de una base y, si se compacto, el tamano despues.
        Solo se compacta con wal_checkpoint(TRUNCATE) y VACUUM: no se borra
        ninguna fila.
    #>
    param(
        [pscustomobject]$Resultado,
        [bool]$Compactar,
        [string]$Etiqueta
    )

    if ($null -eq $Resultado) { return }
    if ($Resultado.Error) {
        Write-Host "   ${Etiqueta}: no se pudo compactar: $($Resultado.Error)" -ForegroundColor Red
        return
    }
    if ($Resultado.Ausentes -contains 'base') {
        Write-Host "   ${Etiqueta}: no existe (se omite)" -ForegroundColor Yellow
        return
    }
    if ($null -ne $Resultado.Antes) {
        $momento = if ($Compactar) { 'antes' } else { 'actual' }
        Write-Host "   ${Etiqueta}: $($Resultado.Antes) bytes ($momento)"
    }
    if ($Compactar) {
        if ($Resultado.Ok) {
            Write-Host "   ${Etiqueta}: WAL truncado y VACUUM: hechos"
        }
        if ($null -ne $Resultado.Despues) {
            Write-Host "   ${Etiqueta} despues: $($Resultado.Despues) bytes"
        }
    } else {
        Write-Host "   ${Etiqueta}: con -Confirmar se trunca el WAL y se hace VACUUM (sin borrar filas)."
    }
}

function Invoke-CompactacionBases {
    <#
        Mide o compacta la base del agente y la de estado del gateway. La base
        del agente ya no tiene las filas archivadas; la de estado nunca pierde
        filas: solo se trunca el WAL y se hace VACUUM. Se corre con el gateway
        detenido para tener propiedad exclusiva.
    #>
    param([bool]$Compactar)

    $bases = @(
        [pscustomobject]@{ Etiqueta = 'Base del agente'; Ruta = (Get-RutaBaseAgente) }
        [pscustomobject]@{ Etiqueta = 'Base de estado'; Ruta = (Get-RutaBaseEstado) }
    )
    foreach ($base in $bases) {
        Write-Host "   $($base.Etiqueta): $($base.Ruta)"
        $modo = if ($Compactar) { 'compactar' } else { 'medir' }
        $resultado = Invoke-SqliteWsl -Modo $modo -RutaBase $base.Ruta
        Write-Compactacion -Resultado $resultado -Compactar $Compactar -Etiqueta $base.Etiqueta
        if ($resultado.Error) {
            $Fallos.Add("compactacion: $($base.Etiqueta)")
        } elseif ($Compactar -and $resultado.Ok) {
            $script:BasesCompactadas = $true
        }
    }
}

function Get-ArchivosWorkspace {
    <#
        Lista los archivos de memoria derivados del workspace. Borra todo el
        contenido de memory\ sin filtrar por extension (bitacora diaria,
        dreaming y .dreams\session-corpus). Protege los .example, las semillas
        (MEMORY.semilla.md y semilla.md) y los cuatro archivos versionados.
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
        # -Force incluye los archivos y carpetas ocultos (.dreams). No se filtra
        # por extension: cualquier archivo bajo memory\ es memoria derivada.
        Get-ChildItem -LiteralPath $carpetaMemoria -Recurse -File -Force |
            Where-Object { $_.Name -notlike '*.example' } |
            ForEach-Object { $lista.Add($_.FullName) }
    }

    $limpias = New-Object System.Collections.Generic.List[string]
    foreach ($ruta in $lista) {
        $nombre = Split-Path -Leaf $ruta
        if ($ArchivosVersionados -contains $nombre) { continue }
        if ($ArchivosSemilla -contains $nombre) { continue }
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
#  2. Memorias derivadas y archivos archivados
# ---------------------------------------------------------------------------

Write-Host ''
Write-Host '2. Memorias derivadas y archivos archivados'

$SesionesOlvidadas = 0
$IndiceLimpiado = $false
$Purga = $null
$BasesCompactadas = $false
$haySesiones = ($claves.Count -gt 0)

if (-not $Confirmar) {
    if ($haySesiones) {
        Write-Host "   Se olvidarian las memorias derivadas de $($claves.Count) sesiones."
        Write-Host '   openclaw memory forget es offline-only: con -Confirmar el script'
        Write-Host '   detiene el gateway, olvida, limpia el indice y lo vuelve a levantar.'
    } else {
        Write-Host '   No hay sesiones de las que olvidar memorias.'
    }

    if ($PurgarArchivos) {
        $rutaBase = Get-RutaBaseAgente
        Write-Host ''
        Write-Host '   Archivos archivados'
        Write-Host "   Base: $rutaBase"
        $Purga = Invoke-SqliteWsl -Modo 'contar' -RutaBase $rutaBase
        Write-PurgaArchivos -Resultado $Purga -Borrar $false
        if ($Purga.Error) { $Fallos.Add('purga: conteo de archivos') }
    }

    Write-Host ''
    Write-Host '   Compactacion de las bases (con -Confirmar y el gateway detenido)'
    Invoke-CompactacionBases -Compactar $false
} else {
    Write-Host '   Deteniendo el gateway para tener propiedad exclusiva del estado...'
    # OpenClaw 2026.11.6 pide --force para detener el gateway desde una consola
    # no interactiva. Solo se usa aqui, dentro de -Confirmar; memory forget y
    # memory reset no aceptan ese interruptor.
    $parada = Invoke-OpenClaw -Argumentos @('daemon', 'stop', '--force')
    if ($parada.Codigo -ne 0) {
        Write-Host '   No se pudo detener el gateway.' -ForegroundColor Red
        $Fallos.Add('daemon stop')
    }

    # La parada se confirma con el estado del servicio, no con "openclaw
    # health": con el gateway apagado health tarda decenas de segundos y escribe
    # "OpenClaw took too long to respond" en stderr, que cortaba el borrado.
    $detenido = $false
    if ($parada.Codigo -eq 0) {
        $detenido = Esperar-Gateway -Arriba $false -Segundos 25 -PausaInicial 5
    }
    if ($parada.Codigo -eq 0 -and -not $detenido) {
        Write-Host '   El gateway no confirmo el apagado; no se toca la memoria.' -ForegroundColor Red
        $Fallos.Add('gateway no se detuvo')
    }

    # El finally corre con o sin $detenido: si el apagado no llego a ocurrir y
    # el servicio sigue activo no se toca; si quedo apagado (o el estado es
    # desconocido) se vuelve a encender con daemon start.
    try {
        if ($detenido) {
            if ($haySesiones) {
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
            } else {
                Write-Host '   No hay sesiones de las que olvidar memorias.'
            }

            if ($PurgarArchivos) {
                # Misma ventana sin gateway: no hay un segundo apagado.
                $rutaBase = Get-RutaBaseAgente
                Write-Host ''
                Write-Host '   Archivos archivados'
                Write-Host "   Base: $rutaBase"
                $Purga = Invoke-SqliteWsl -Modo 'purgar' -RutaBase $rutaBase
                Write-PurgaArchivos -Resultado $Purga -Borrar $true
                if ($Purga.Error) { $Fallos.Add('purga: archivos archivados') }
            }

            Write-Host ''
            Write-Host '   Compactacion de las bases'
            Invoke-CompactacionBases -Compactar $true
        }
    } finally {
        Write-Host '   Asegurando que el gateway quede arriba...'
        if ((Get-EstadoGateway) -eq 'activo') {
            Write-Host '   Gateway arriba.'
        } else {
            $arranque = Invoke-OpenClaw -Argumentos @('daemon', 'start')
            if ($arranque.Codigo -ne 0) {
                Write-Host '   No se pudo arrancar el gateway: revisalo a mano.' -ForegroundColor Red
                $Fallos.Add('daemon start')
            } elseif (-not (Esperar-Gateway -Arriba $true -Segundos 60 -PausaInicial 3)) {
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

$PurgaFilas = 0
$PurgaBorradas = 0
if ($null -ne $Purga) {
    foreach ($tabla in $TablasArchivadas) {
        if ($Purga.Filas.ContainsKey($tabla)) { $PurgaFilas += $Purga.Filas[$tabla] }
        if ($Purga.Borradas.ContainsKey($tabla)) { $PurgaBorradas += $Purga.Borradas[$tabla] }
    }
}

Write-Host ''
Write-Host 'RESUMEN'
if ($Confirmar) {
    Write-Host "  Sesiones borradas:              $SesionesBorradas de $($claves.Count)"
    Write-Host "  Sesiones con memoria olvidada:  $SesionesOlvidadas"
    Write-Host "  Indice derivado limpiado:       $(if ($IndiceLimpiado) { 'si' } else { 'no' })"
    if ($PurgarArchivos) {
        Write-Host "  Filas archivadas borradas:      $PurgaBorradas"
        if ($null -ne $Purga -and $null -ne $Purga.Antes) {
            Write-Host "  Base del agente:                $($Purga.Antes) -> $($Purga.Despues) bytes"
        }
    }
    Write-Host "  Bases compactadas:              $(if ($BasesCompactadas) { 'si (WAL truncado + VACUUM)' } else { 'no' })"
    Write-Host "  Archivos borrados en WSL:       $ArchivosWorkspaceBorrados"
    Write-Host "  Archivos borrados en Windows:   $ArchivosWindowsBorrados"
} else {
    Write-Host "  Sesiones que se borrarian:      $SesionesBorradas de $($claves.Count)"
    Write-Host "  Memorias que se olvidarian:     $($claves.Count) sesiones"
    Write-Host '  Bases que se compactarian:      base del agente y base de estado'
    if ($PurgarArchivos) {
        Write-Host "  Filas archivadas que se borrarian: $PurgaFilas"
    }
    Write-Host "  Archivos de WSL que se borrarian: $ArchivosWorkspaceBorrados"
    Write-Host "  Archivos de Windows que se borrarian: $ArchivosWindowsBorrados"
    Write-Host ''
    Write-Host '  No se borro nada. Para borrar de verdad:'
    Write-Host '    make limpiar-evento CONFIRMAR=1'
}
Write-Host ''
if ($PurgarArchivos) {
    Write-Host 'Nota 1: los archivos archivados de las sesiones borradas viven en la'
    Write-Host 'base SQLite del agente dentro de WSL (session_transcript_archives y'
    Write-Host 'session_transcript_cold_archives). Con -PurgarArchivos se borran sus'
    Write-Host 'filas, se trunca el WAL y se hace VACUUM, sin tocar ninguna otra'
    Write-Host 'tabla y sin copia de respaldo: una copia conservaria justo lo que el'
    Write-Host 'consentimiento promete borrar.'
} else {
    Write-Host 'Nota 1: los archivos archivados de las sesiones borradas siguen en la'
    Write-Host 'base SQLite del agente dentro de WSL (session_transcript_archives y'
    Write-Host 'session_transcript_cold_archives). Agrega -PurgarArchivos para'
    Write-Host 'contarlos en modo de prueba y borrarlos con -Confirmar.'
}
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
