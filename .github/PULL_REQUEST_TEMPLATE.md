## Qué cambia

<!-- Describe el cambio en una o dos frases. -->

## Por qué

<!-- Problema, issue o decisión que motiva el cambio. -->

Closes #
Tarea del cambio de OpenSpec `sucursal-1965`:

## Parte de la sucursal

- [ ] Bóveda (embeddings y RAG)
- [ ] Digiturno (router)
- [ ] Ventanilla (agente con memoria)
- [ ] Tablero de tasas (datos estructurados)
- [ ] Cámara de compensación (pipeline e indexación)
- [ ] Arqueo (evaluación)
- [ ] Pantallas (frontend)
- [ ] Infraestructura, documentación o CI

## Cómo se verificó

- [ ] `make check` (ruff + ty + pytest), número de pruebas:
- [ ] `make demo` (pipeline offline)
- [ ] `make status` si se tocó el corpus
- [ ] GGA aprobó los commits (si hubo rebase: `gga run --pr-mode --diff-only`)
- [ ] Capturas, si cambia una pantalla

<!-- Otros comandos para probarlo y lo que debe salir. -->

## Costo

<!-- Embeddings, indexación y experimentos de recuperación corren con Ollama: US$ 0. El gasto de DeepSeek sale de platform.deepseek.com → Usage, filtrando por tu clave. -->

| Concepto | Valor |
| --- | --- |
| Llamadas a DeepSeek durante el desarrollo | |
| Tokens (entrada / salida / desde caché) | |
| Costo estimado (USD) | |
| ¿Cambia el costo por pregunta en la app? | No / Sí: |
| ¿Respeta caché, modo demo y tope de gasto diario? | Sí / No aplica |

## Seguridad

- [ ] Sin claves, `.env` ni datos personales en el código o los datos.
- [ ] Peticiones al sitio del banco solo por `net.py`: `robots.txt`, ritmo de cortesía de 1,5 s y header `From`.
- [ ] Los fragmentos recuperados se tratan como datos, nunca como instrucciones.
- [ ] El índice vectorial no se versiona.
- [ ] No toqué `data/raw/` ni `data/gold/` a mano.

## Arquitectura y decisiones

- [ ] No cambia la arquitectura.
- [ ] Cambia la arquitectura y actualicé el diagrama de Archify en el README.
- [ ] Actualicé `CONSTITUTION.md` si cambió alcance, stack o formato de Gold.
- [ ] Registré la decisión en Engram y en el cambio de OpenSpec (si aplica).

## Estándar

- [ ] No hay `pip` ni `requirements.txt` (`uv` es el único gestor).
- [ ] El commit sigue Conventional Commits en español.

## Revisión

<!-- Asigna a otra persona del grupo. Nadie aprueba su propio PR. -->
