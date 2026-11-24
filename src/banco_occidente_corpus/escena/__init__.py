"""Escena demo «Pana vs. el gota a gota» (OpenSpec demo-gota-a-gota).

El paquete separa el contrato que comparten la pantalla, la voz y el auditor
(`contratos`) de la aritmética determinista de Don Gota (`gota`), de la
comparación de Pana con el motor del diagnóstico y la usura (`comparacion`) y
del núcleo de las preguntas del público (`pregunta` y `proyecto`). Los módulos
que usan un modelo lo reciben inyectado: la escena no crea clientes ni abre
conexiones de red propias.
"""
