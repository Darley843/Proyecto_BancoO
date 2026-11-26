# Bitácora — {{FECHA}}

> Operación del día, sin datos de invitados. La fecha del título se completa al
> sembrar. El archivo real vive en el workspace de WSL y se borra con
> `make limpiar-evento`; esta semilla se conserva en el repositorio.

## Resumen

- Motor: OpenClaw, con el respaldo al grafo probado al apagar el gateway.
- Herramientas ejercitadas: diagnóstico de capacidad, cálculo y comparación del
  gota a gota, verificación de usura, negociación, ficha y consulta de tasa.
- Atención: pruebas internas y recorridos de ensayo; sin conteo por persona.

## Pruebas hechas

- `make check` y el pipeline sin red: el repositorio queda en verde.
- Recorrido de la entrevista completa: preguntas con sus letras, monto exacto
  aparte, perfil, comparación, negociación y ficha.
- Consulta de tasa contra el Tablero y auditoría de las respuestas con cifras.
- Limpieza del evento en modo de prueba: se revisó qué archivos se borrarían.

## Ajustes

- Se sembraron `MEMORY.md` y esta bitácora desde las semillas versionadas.
- Se documentó cómo se leen y se editan, y cómo se regeneran tras el borrado.
- Se protegió la semilla de la limpieza y de la sincronización: solo viajan y se
  borran los archivos reales.
- Se reforzó el guion: pedir el monto exacto aparte y confirmar la opción cuando
  la respuesta no corresponde a la pregunta.

## Decisiones

- Congelar esta versión para los ensayos completos.
- Mantener la memoria y la bitácora como archivos locales, en texto plano y
  editables a mano; la memoria guarda solo aprendizajes anónimos.
- El borrado del evento toca únicamente los archivos reales; las semillas se
  conservan para poder regenerarlos.

## Incidencias

- Un invitado de prueba respondió con una letra de otra pregunta; se pidió
  confirmar la opción y la entrevista siguió sin reiniciarse.

## Sin datos personales

No se registran nombres, teléfonos, documentos, correos, montos, deudas ni
textos de invitados. Solo conteos agregados y aprendizajes generales.
