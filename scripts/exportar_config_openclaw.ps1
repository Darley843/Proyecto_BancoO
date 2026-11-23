<#
.SYNOPSIS
    Exporta la configuracion del gateway de OpenClaw al repositorio, sin secretos.

.DESCRIPTION
    Origen:  \\wsl$\OpenClawGateway\home\openclaw\.openclaw\openclaw.json
    Destino: openclaw\openclaw.json del repositorio.

    Lee el JSON del gateway, redacta los valores sensibles y escribe una copia
    legible que se pueda revisar y versionar.

    Secretos: toda clave llamada token, apiKey, password o secret, en
    cualquier nivel. `token` pasa a "${OPENCLAW_GATEWAY_TOKEN}" y el resto a
    "<SECRETO>".

    Datos personales: los telefonos en formato E.164 (canal de WhatsApp)
    pasan a "<TELEFONO_REDACTADO>". Usa -ConservarDatosPersonales solo si la
    copia no va a versionarse.

    Despues de redactar, el script recorre el resultado y, si queda un valor
    con pinta de clave (empieza por "sk-" o tiene mas de 40 caracteres
    alfanumericos seguidos), falla sin escribir nada. El mensaje nombra la
    ruta del valor, nunca el valor.

.PARAMETER Origen
    Ruta del openclaw.json dentro de WSL.

.PARAMETER Destino
    Archivo a escribir. Por defecto, openclaw\openclaw.json del repositorio.

.PARAMETER ConservarDatosPersonales
    No redacta los telefonos. No usar en copias versionadas.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\exportar_config_openclaw.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\exportar_config_openclaw.ps1 `
        -Origen "C:\ruta\de\ensayo\openclaw.json"
#>
[CmdletBinding()]
param(
    [string]$Origen = '\\wsl$\OpenClawGateway\home\openclaw\.openclaw\openclaw.json',
    [string]$Destino,
    [switch]$ConservarDatosPersonales
)

$ErrorActionPreference = 'Stop'

# Marcadores: nunca se escribe el valor real en el repositorio.
$MarcadoresSecretos = @{
    'token'    = '${OPENCLAW_GATEWAY_TOKEN}'
    'apikey'   = '<SECRETO>'
    'password' = '<SECRETO>'
    'secret'   = '<SECRETO>'
}
$PatronTelefono = '^\+\d{7,15}$'
$TelefonoRedactado = '<TELEFONO_REDACTADO>'
# Heuristica de la comprobacion final: "sk-..." o mas de 40 alfanumericos seguidos.
$PatronesDeClave = @('(?i)\bsk-[A-Za-z0-9_\-]{8,}', '[A-Za-z0-9]{41,}')

function Redactar {
    <#
        Recorre el arbol y sustituye secretos y telefonos en el sitio.
        Anota en la bitacora la ruta de lo que toco, nunca el valor.
    #>
    param(
        [AllowNull()]$Nodo,
        [string]$Ruta = '',
        [System.Collections.ArrayList]$Bitacora
    )

    if ($null -eq $Nodo) { return }

    if ($Nodo -is [System.Management.Automation.PSCustomObject]) {
        foreach ($prop in @($Nodo.PSObject.Properties)) {
            $rutaHija = if ($Ruta) { "$Ruta.$($prop.Name)" } else { $prop.Name }
            if ($MarcadoresSecretos.ContainsKey($prop.Name)) {
                $Nodo.($prop.Name) = $MarcadoresSecretos[$prop.Name]
                [void]$Bitacora.Add("$rutaHija (secreto)")
                continue
            }
            if (-not $ConservarDatosPersonales -and $prop.Value -is [string] -and
                $prop.Value -match $PatronTelefono) {
                $Nodo.($prop.Name) = $TelefonoRedactado
                [void]$Bitacora.Add("$rutaHija (telefono)")
                continue
            }
            Redactar -Nodo $prop.Value -Ruta $rutaHija -Bitacora $Bitacora
        }
        return
    }

    if ($Nodo -is [System.Collections.IList]) {
        for ($i = 0; $i -lt $Nodo.Count; $i++) {
            $rutaHija = "$Ruta[$i]"
            if (-not $ConservarDatosPersonales -and $Nodo[$i] -is [string] -and
                $Nodo[$i] -match $PatronTelefono) {
                $Nodo[$i] = $TelefonoRedactado
                [void]$Bitacora.Add("$rutaHija (telefono)")
                continue
            }
            Redactar -Nodo $Nodo[$i] -Ruta $rutaHija -Bitacora $Bitacora
        }
    }
}

function BuscarClaves {
    <#
        Devuelve las rutas de los valores que aun parecen una clave.
    #>
    param(
        [AllowNull()]$Nodo,
        [string]$Ruta = '',
        [System.Collections.ArrayList]$Hallazgos
    )

    if ($null -eq $Nodo) { return }

    if ($Nodo -is [string]) {
        foreach ($patron in $PatronesDeClave) {
            if ($Nodo -match $patron) {
                [void]$Hallazgos.Add($Ruta)
                return
            }
        }
        return
    }

    if ($Nodo -is [System.Management.Automation.PSCustomObject]) {
        foreach ($prop in @($Nodo.PSObject.Properties)) {
            $rutaHija = if ($Ruta) { "$Ruta.$($prop.Name)" } else { $prop.Name }
            BuscarClaves -Nodo $prop.Value -Ruta $rutaHija -Hallazgos $Hallazgos
        }
        return
    }

    if ($Nodo -is [System.Collections.IList]) {
        for ($i = 0; $i -lt $Nodo.Count; $i++) {
            BuscarClaves -Nodo $Nodo[$i] -Ruta "$Ruta[$i]" -Hallazgos $Hallazgos
        }
    }
}

function Convertir-JsonTexto {
    <#
        Escapa un texto como cadena JSON. Deja el UTF-8 legible (emoji incluidos).
    #>
    param([string]$Texto)

    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    for ($i = 0; $i -lt $Texto.Length; $i++) {
        $caracter = $Texto[$i]
        $codigo = [int]$caracter
        if ($caracter -eq '"') {
            [void]$sb.Append('\"')
        } elseif ($caracter -eq '\') {
            [void]$sb.Append('\\')
        } elseif ($codigo -lt 0x20) {
            switch ($codigo) {
                8 { [void]$sb.Append('\b') }
                9 { [void]$sb.Append('\t') }
                10 { [void]$sb.Append('\n') }
                12 { [void]$sb.Append('\f') }
                13 { [void]$sb.Append('\r') }
                default { [void]$sb.Append(('\u{0:x4}' -f $codigo)) }
            }
        } else {
            [void]$sb.Append($caracter)
        }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Convertir-JsonNodo {
    <#
        Serializa con dos espacios de sangria, en el orden original de las
        claves y con finales de linea LF (el repositorio los normaliza a LF).
    #>
    param(
        [AllowNull()]$Nodo,
        [int]$Nivel = 0
    )

    if ($null -eq $Nodo) { return 'null' }

    if ($Nodo -is [bool]) {
        if ($Nodo) { return 'true' }
        return 'false'
    }

    if ($Nodo -is [string]) {
        return (Convertir-JsonTexto -Texto $Nodo)
    }

    if ($Nodo -is [System.ValueType]) {
        return [string]::Format(
            [System.Globalization.CultureInfo]::InvariantCulture, '{0}', $Nodo)
    }

    $sangria = '  ' * $Nivel
    $sangriaHija = '  ' * ($Nivel + 1)

    if ($Nodo -is [System.Management.Automation.PSCustomObject]) {
        $props = @($Nodo.PSObject.Properties)
        if ($props.Count -eq 0) { return '{}' }
        $lineas = foreach ($prop in $props) {
            $valor = Convertir-JsonNodo -Nodo $prop.Value -Nivel ($Nivel + 1)
            "$sangriaHija$(Convertir-JsonTexto -Texto $prop.Name): $valor"
        }
        return "{`n" + ($lineas -join ",`n") + "`n$sangria}"
    }

    if ($Nodo -is [System.Collections.IList]) {
        if ($Nodo.Count -eq 0) { return '[]' }
        $lineas = foreach ($item in $Nodo) {
            $valor = Convertir-JsonNodo -Nodo $item -Nivel ($Nivel + 1)
            "$sangriaHija$valor"
        }
        return "[`n" + ($lineas -join ",`n") + "`n$sangria]"
    }

    throw "No se pudo serializar un nodo de tipo $($Nodo.GetType().FullName)."
}

try {
    if ([string]::IsNullOrWhiteSpace($Destino)) {
        $Destino = Join-Path (Split-Path -Parent $PSScriptRoot) 'openclaw\openclaw.json'
    }

    if (-not (Test-Path -LiteralPath $Origen -PathType Leaf)) {
        throw "No existe el origen: $Origen. Inicia WSL y OpenClaw, o pasa -Origen."
    }

    $texto = [System.IO.File]::ReadAllText($Origen)
    try {
        $config = $texto | ConvertFrom-Json
    } catch {
        throw "El origen no es JSON valido: $Origen"
    }

    $bitacora = New-Object System.Collections.ArrayList
    Redactar -Nodo $config -Bitacora $bitacora

    $hallazgos = New-Object System.Collections.ArrayList
    BuscarClaves -Nodo $config -Hallazgos $hallazgos
    if ($hallazgos.Count -gt 0) {
        $rutas = ($hallazgos | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
        throw ("Quedaron valores con pinta de clave y no se escribio nada." +
            [Environment]::NewLine + "Revisa estas rutas:" + [Environment]::NewLine + $rutas)
    }

    $carpeta = Split-Path -Parent $Destino
    if (-not (Test-Path -LiteralPath $carpeta -PathType Container)) {
        New-Item -ItemType Directory -Path $carpeta -Force | Out-Null
    }

    $json = Convertir-JsonNodo -Nodo $config
    $utf8SinBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Destino, $json + "`n", $utf8SinBom)

    if ($bitacora.Count -eq 0) {
        Write-Host 'No habia nada que redactar.'
    } else {
        Write-Host "Valores redactados: $($bitacora.Count)"
        foreach ($linea in $bitacora) { Write-Host "  - $linea" }
    }
    Write-Host "Origen:  $Origen"
    Write-Host "Destino: $Destino"
    Write-Host 'Comprobacion final: ninguna clave expuesta.'
    exit 0
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
