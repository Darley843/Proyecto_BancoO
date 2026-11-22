# Pantalla de la escena «Pana vs. el gota a gota»

Pantalla para el proyector del viernes: los agentes hablan con voz y subtítulos,
y un panel muestra el escenario, el semáforo, las cifras con su fuente y el
veredicto del auditor.

```powershell
make app
# abrir http://127.0.0.1:8000/escena.html
```

## De dónde salen los turnos

1. `GET /api/escena/turnos` (el orquestador de la escena, cuando exista).
2. Si no responde: `app/web/escena/turnos-ejemplo.json`, y la pantalla muestra
   el sello «Turnos de ejemplo».

Ambos devuelven `{"turnos": [...]}`. Cada turno sigue el contrato del plan de
cierre (sección 6), validado en `app/web/escena/contrato.js`:

| Campo | Valores |
|---|---|
| `personaje` | `pana`, `don_gota`, `joven`, `agente_joven`, `agente_banco`, `auditor` |
| `texto` | lo que se dice en voz y en subtítulos |
| `cifras` | lista de `{nombre, valor, fuente}`; `fuente` es `motor`, `simulador` o `Tablero`; las tasas van como fracción (0,24 = 24 %) |
| `escenario` | `{monto, plazo, semaforo}`; `semaforo` vacío si aún no se calcula |
| `origen` | `guion`, `motor`, `modelo` o `reglas` |
| `hallazgos` | objeciones del auditor (vacía si está conforme) |

Un turno que no cumple el contrato no se dice: la pantalla muestra el error.
El paso de la escena (1 a 6) se deduce de quién habla.

## Los rostros

Cada personaje sale con un **retrato en 3D** (`app/web/escena/rostros/<personaje>.webp`,
384 × 384, menos de 20 KB cada uno) dentro de un círculo con borde de su color; el
que habla brilla. Los retratos se **generaron con IA** a partir de una descripción
escrita por el equipo: son personajes inventados, no fotos de personas reales.

Si un retrato no carga, la pantalla usa el dibujo plano de respaldo de
`app/web/escena/rostros.js` (solo figuras SVG). En el dibujo la boca se mueve
mientras el personaje habla; el voluntario no tiene voz, así que la suya no.

Para cambiar un retrato basta con reemplazar el `.webp` con el mismo nombre
(cuadrado, de los hombros hacia arriba, fondo liso del color del personaje).

| Personaje | Cómo se ve |
|---|---|
| Pana | el mismo joven de buzo gris de las tarjetas (`pana/personaje.py`) |
| Don Gota | prestamista con gorra, bigote, cadena dorada y diente de oro |
| Joven (voluntario) | pelo crespo, chaqueta de jean y audífonos al cuello |
| Agente del joven | robot amable de pantalla azul con gorra al revés |
| Agente del banco | robot formal con diadema de atención y corbatín |
| Auditor | persona mayor con gafas redondas y corbata |

## Cómo se maneja

| Control | Qué hace |
|---|---|
| Empezar / Pausar (tecla P) | reproduce los turnos seguidos, cada uno con la voz de su personaje |
| Siguiente turno (Espacio o →) | pasa al siguiente sin esperar |
| Solo subtítulos (tecla S) | **modo de respaldo**: no suena nada y avanza de a un turno por clic |
| Reiniciar (tecla R) | vuelve al inicio |

El joven es la persona voluntaria: habla en persona, así que su turno solo se
muestra en subtítulos. Las voces vienen de `app/web/voz.js` (ver
[`VOZ.md`](./VOZ.md)); si Piper falla, se usa la voz del navegador y los
subtítulos siguen visibles.

Las cifras del ejemplo son inventadas para un millón de pesos a seis meses, con
la tasa máxima de libre inversión y la usura de noviembre de 2026 de
`config/tasas.toml`. `test/test_web_escena.py` comprueba que cumplen el contrato
y que cuadran con las fórmulas.
