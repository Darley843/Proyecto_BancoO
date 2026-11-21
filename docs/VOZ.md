# Voces de la escena «Pana vs. el gota a gota»

Cada personaje de la escena habla con su propia voz, generada **en el computador**
con [Piper](https://github.com/OHF-Voice/piper1-gpl) (GPL-3.0). El texto no sale a
ningún servicio. Si falta una voz, la pantalla usa la del navegador y los
subtítulos siguen visibles.

## Una vez por computador

```powershell
make voz-modelo     # descarga los modelos que nombra config/voz.toml (~300 MB, con timeout, User-Agent y From)
make voces-prueba   # escribe data/modelos/voz/muestras/<personaje>.ogg
```

Abre los `.ogg` de `data/modelos/voz/muestras/` y comprueba que cada personaje se
distingue. `data/modelos/` está en `.gitignore`: los modelos no se versionan.

## Escoger las voces (Piper o voz del navegador)

Cada personaje puede usar uno de dos motores:

- **`piper`**: voz local del proyecto. Suena igual en cualquier computador.
- **`navegador`**: una voz instalada en el computador o en el navegador, por
  ejemplo una voz de Windows con acento colombiano. Cambia según el equipo, así
  que hay que probarla en el computador de la demo.

Para escoger:

1. `make app` y abre http://127.0.0.1:8000/voces.html.
2. Por personaje, elige motor, voz del navegador, tono y velocidad, y dale
   «Escuchar». «Escuchar a todos en orden» prueba la escena completa.
3. Copia las líneas de abajo y pégalas en `config/voz.toml`, en la sección de
   cada personaje. Reinicia `make app`.

La voz del navegador también es el respaldo cuando Piper falla.

## Quién suena cómo (`config/voz.toml`)

| Personaje | Modelo | Ajuste |
|---|---|---|
| `pana` | `es_MX-ald-medium` | voz de hombre, base, clara |
| `don_gota` | `es_ES-davefx-medium` | más grave (tono 0,85) y algo más lento |
| `joven` | `es_ES-sharvard-medium`, hablante 1 | no habla en la escena (es la persona voluntaria); solo respaldo |
| `agente_joven` | `es_ES-sharvard-medium`, hablante 0 | algo más lento |
| `agente_banco` | `es_AR-daniela-high` | voz de mujer |
| `auditor` | `es_MX-claude-high` | un poco más grave (tono 0,95) |

- `velocidad` es el `length_scale` de Piper: más de 1 habla más lento.
- `tono` va de 0,7 a 1,4: menos de 1 suena más grave. El tono se cambia sin
  cambiar la duración.
- Para probar otra voz, cambia `modelo`, corre `make voz-modelo` y
  `make voces-prueba`.

## API

| Ruta | Qué hace |
|---|---|
| `GET /api/voz/personajes` | por personaje: `motor`, `piper` (modelo listo) y `navegador` (`voz`, `tono`, `velocidad`) |
| `POST /api/voz` | `{"texto": "...", "personaje": "don_gota"}` → `audio/ogg`; 503 si no hay voz |
| `GET /api/pana/presentacion` | texto fijo con que Pana se presenta |

## En la web (`app/web/voz.js`)

- `decirComo(personaje, texto, {alTerminar, soloSubtitulos})`: pide el audio a
  la API y, si no hay, usa la voz del navegador con un tono y una velocidad por
  personaje. Con `soloSubtitulos: true` no suena nada (modo de respaldo en vivo).
- `detenerVoz()` corta lo que esté sonando.
- `decirComoPana(texto)` es lo mismo con `personaje = "pana"`.

Las pruebas viven en `test/test_voz.py` (con un sintetizador falso: no necesitan
los modelos).

## Licencia

`piper-tts` es GPL-3.0. El código del proyecto sigue con licencia MIT; quien
distribuya el proyecto junto con `piper-tts` debe cumplir la GPL-3.0. La
decisión está en la tabla de decisiones de `CONSTITUTION.md`. Cada
modelo de voz trae su propia licencia en su `MODEL_CARD` del repositorio de
voces de Piper.
