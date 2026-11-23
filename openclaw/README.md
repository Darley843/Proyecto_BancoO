# Workspace de Pana en OpenClaw

OpenClaw es el gateway local del agente `pana` (ver el cambio OpenSpec
`agente-openclaw`). El workspace es la carpeta que el agente lee en cada turno:
identidad, reglas, público, memoria y bitácora. **El repositorio es la fuente
de verdad**; el workspace que usa el gateway vive en WSL y se actualiza con el
script de sincronización.

## Qué es cada archivo

| Archivo | Qué es | ¿Se versiona? |
|---|---|---|
| `SOUL.md` | Identidad y tono de Pana. | Sí |
| `AGENTS.md` | Reglas, límites, datos, herramientas y guion de la escena. | Sí |
| `USER.md` | Público genérico de la demo, sin personas reales. | Sí |
| `IDENTITY.md` | Nombre y emoji de Pana. | Sí |
| `MEMORY.md.example` | Plantilla de la memoria local. | Sí |
| `memory/AAAA-MM-DD.md.example` | Plantilla de la bitácora diaria. | Sí |
| `MEMORY.md` | Memoria local de la ejecución. | No: `.gitignore` |
| `memory/*.md` | Bitácora local por día. | No: `.gitignore` |

`SOUL.md`, `AGENTS.md`, `USER.md` e `IDENTITY.md` se envían al modelo en cada
turno: mantenlos cortos (2.500 caracteres cada uno; `AGENTS.md` hasta 4.000).

- **SOUL.md** responde a «quién soy y cómo hablo».
- **AGENTS.md** responde a «qué puedo y qué no puedo hacer». Si hay conflicto,
  manda `AGENTS.md`.
- **USER.md** describe a quién le hablo, siempre en genérico. Nunca escribas
  datos de una persona real.
- **IDENTITY.md** es la ficha mínima del personaje.

`MEMORY.md` y la bitácora son locales, se crean desde las plantillas `.example`
y se borran al terminar el evento. No guardan nombres, números, montos, deudas,
documentos ni textos de invitados; solo aprendizajes generales y conteos
agregados. `AGENTS.md` lo prohíbe de forma explícita.

## Cómo se sincroniza

El gateway corre dentro de WSL y lee el workspace en:

```text
\\wsl$\OpenClawGateway\home\openclaw\.openclaw\workspaces\pana
```

Desde la raíz del repositorio, en PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sincronizar_workspace.ps1
```

El script:

1. Copia `openclaw/workspace/pana/` al workspace de WSL.
2. **No borra ni sobrescribe** `MEMORY.md` ni la bitácora real (`memory/*.md`
   que no sean `.example`); solo viajan las plantillas.
3. Elimina `BOOTSTRAP.md` del destino: es el archivo de arranque de OpenClaw y
   no debe quedar como una tarea pendiente del agente.
4. Falla con un mensaje claro si WSL o el destino no están disponibles.

Para usar otra ruta (por ejemplo, una copia de ensayo), pasa `-Destino`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sincronizar_workspace.ps1 `
  -Destino "C:\ruta\de\ensayo\pana"
```

### Orden recomendado

1. Edita y revisa los archivos en el repositorio.
2. Ejecuta `make check` y `uv run ruff format --check .`.
3. Haz el commit.
4. Sincroniza el workspace.
5. Si es la primera vez, copia `MEMORY.md.example` a `MEMORY.md` en el destino
   (o deja que OpenClaw lo cree al arrancar).
6. Al terminar el evento, borra `MEMORY.md` y `memory/*.md` del destino.

No edites el workspace de WSL a mano: el siguiente `sincronizar_workspace.ps1`
sobrescribe lo versionado. La única excepción son `MEMORY.md` y la bitácora,
que el script respeta.
