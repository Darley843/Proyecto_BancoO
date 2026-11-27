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

## La escena (`escena.html`)

La escena se abre como página aparte, fuera de la Sucursal:
http://127.0.0.1:8000/escena.html (con `make app` corriendo). Cada turno se dice
con la voz de su personaje y sale en subtítulos. El **modo solo subtítulos**
(tecla S) no pide audio a `/api/voz` ni usa la voz del navegador: muestra el
texto y avanza con Espacio. Es el respaldo si falla el sonido. Ver
[`ESCENA.md`](./ESCENA.md).

## Preflight de voces (el día de la demo)

En el computador de la demo, con internet y en **Microsoft Edge**:

1. `make voces-prueba`: debe escribir un `.ogg` por personaje en
   `data/modelos/voz/muestras/`. Si falla, falta `make voz-modelo`.
2. `make app` y abrir http://127.0.0.1:8000/voces.html: «Escuchar a todos en
   orden». Pana debe sonar con «Microsoft Gonzalo Online (Natural)» y el agente
   del joven con «Microsoft Juan Online (Natural)». Si no aparecen (sin
   internet), suenan con su Piper de respaldo: sirve igual.
3. Abrir http://127.0.0.1:8000/escena.html, F11, y pasar dos o tres turnos con
   voz. Probar la tecla S (solo subtítulos) y volver.

Si nada suena, la escena se presenta en solo subtítulos.

## Quién suena cómo (`config/voz.toml`)

| Personaje | Modelo | Ajuste |
|---|---|---|
| `pana` | navegador: «Microsoft Gonzalo Online (Natural)» (Edge, Colombia); respaldo `es_MX-ald-medium` | voz colombiana de hombre, tono 1,15 |
| `don_gota` | `es_ES-davefx-medium` | más grave (tono 0,85) y algo más lento |
| `joven` | `es_ES-sharvard-medium`, hablante 1 | no habla en la escena (es la persona voluntaria); solo respaldo |
| `agente_joven` | navegador: «Microsoft Juan Online (Natural)» (Edge); respaldo `es_ES-sharvard-medium`, hablante 0 | velocidad 1,1 |
| `agente_banco` | `es_AR-daniela-high` | voz de mujer |
| `auditor` | `es_ES-carlfm-x_low` | voz de hombre, un poco más grave (tono 0,95), como su retrato |

- Con `motor = "navegador"` la voz sale de Edge. Las voces «Online (Natural)»
  necesitan internet; si la voz nombrada no está, la web usa la voz de Piper
  del personaje (por eso `make voz-modelo` también la descarga). Para la demo,
  abrir la escena en **Microsoft Edge**.
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
- Todo texto que llega a la voz pasa una sola vez por `paraVoz`
  (`app/web/escena/voz_cifras.js`), venga de la escena guionada o de la lista en
  vivo: quita emojis, anuncia las letras de las opciones sin leer su texto y dice
  las cifras en pesos. Los subtítulos no cambian.
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
