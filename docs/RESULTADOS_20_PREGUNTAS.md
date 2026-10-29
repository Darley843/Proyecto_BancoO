# Resultados de las 20 preguntas del alcance

Fecha: 2026-10-29 (respuestas del modelo: 2026-10-27). Modelo: `deepseek-flash`. Prompt: `qa_v1`. Contexto completo (`data/contexto/contexto_banco.md`).

Generado con `make evaluar`. Las preguntas y su cobertura esperada están en `config/evaluacion/preguntas_alcance.toml` (ver `docs/ALCANCE.md`). El detalle, con la respuesta cruda del modelo, queda en `data/evaluacion/resultados.jsonl`.

## Resumen

| Clasificación automática | Preguntas |
|---|---:|
| Correcta | 19 |
| Rechazo correcto | 1 |
| **Total** | **20** |

Comportamiento esperado (correctas, rechazos correctos y remisiones): **20 de 20**.

Cómo se clasifica: si el corpus no tiene el dato, lo esperado es la frase fija con el canal oficial (*rechazo correcto*). Si lo tiene, se buscan en la respuesta los términos esperados: todos (*correcta*), algunos (*incompleta*) o ninguno (*revisar*). Una respuesta sin datos cuando el corpus sí los tiene es un *falso negativo*. La clasificación es una heurística; la columna de revisión humana es la que vale para el informe.

Revisión humana (20 de 20 preguntas, en `config/evaluacion/revision_humana.toml`). **20 son propuestas pendientes de confirmar por el grupo.**

| Veredicto humano | Preguntas |
|---|---:|
| Correcta | 15 |
| Parcial | 3 |
| Incorrecta | 1 |
| Rechazo correcto | 1 |

## Tabla

| # | Pregunta | Cobertura | Clasificación | Términos | Fuente citada | Avisos | Revisión humana |
|---:|---|---|---|---:|---|---|---|
| 1 | ¿Cuál es el horario de atención de las oficinas? | no | Rechazo correcto | - | https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente | sin_datos | Rechazo correcto: El corpus no tiene horarios; remite a la linea de servicio. (propuesta) |
| 2 | ¿Dónde hay una oficina en Cali? | parcial | Correcta | 1/1 | https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente | - | Parcial: Sin listado de oficinas; da la sede de Cali (pagina de accionistas) y la linea de Cali, pero cita solo la pagina de lineas. (propuesta) |
| 3 | ¿Cuál es la línea de atención telefónica? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente | - | Correcta: Lineas por ciudad, nacional y EE. UU. coinciden con la fuente. (propuesta) |
| 4 | ¿Cómo presento una petición, queja o reclamo? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/ayuda | - | Correcta: Formulario digital PQRS, lineas, oficinas y Defensor. (propuesta) |
| 5 | ¿Quién es el Defensor del Consumidor Financiero y cómo lo contacto? | si | Correcta | 2/2 | https://www.bancodeoccidente.com.co/quienes-somos/defensor-consumidor-financiero | - | Parcial: Explica la funcion; el corpus no trae telefono ni correo del Defensor y lo dice. (propuesta) |
| 6 | ¿Cuál es el propósito o misión del banco? | parcial | Correcta | 1/1 | https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco | - | Correcta: Proposito literal y cuatro pilares; aclara que no es una mision. (propuesta) |
| 7 | ¿Cuándo y dónde se fundó el banco? | si | Correcta | 2/2 | https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco | - | Correcta: 3 de mayo de 1965, Cali. (propuesta) |
| 8 | ¿A qué grupo empresarial pertenece? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/quienes-somos/filiales | - | Correcta: Grupo Aval, desde 1998. (propuesta) |
| 9 | ¿Quién es el presidente del banco? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/quienes-somos/informacion-inversionistas | - | Correcta: Gerardo Silva Castro, presidente desde agosto de 2023. (propuesta) |
| 10 | ¿Qué tipos de cuentas de ahorro ofrece? | si | Correcta | 2/2 | https://www.bancodeoccidente.com.co/cuenta-de-ahorros | - | Correcta: Seis tipos de cuenta, todos en el corpus. (propuesta) |
| 11 | ¿Qué requisitos necesito para abrir una cuenta? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/ayuda/preguntas-frecuentes | - | Correcta: Documentos de persona natural; aclara que varian por producto. (propuesta) |
| 12 | ¿Puedo abrir una cuenta en línea? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/sistema-kubo | - | Correcta: Apertura digital, entrega de tarjeta en 5 a 7 dias. (propuesta) |
| 13 | ¿Qué tarjetas de crédito ofrece y cuál es su cuota de manejo? | si | Correcta | 2/2 | https://www.bancodeoccidente.com.co/tarjetas-credito | parcial | Parcial: Lista las tarjetas; el valor de la cuota solo esta publicado para RIGO y lo dice. (propuesta) |
| 14 | ¿Qué es un CDT y cuál es su tasa? | parcial | Correcta | 1/1 | https://www.bancodeoccidente.com.co/inversion/cdt | parcial | Incorrecta: Error: dice $500.000 con plazo minimo de 30 dias; la fuente dice $500.000 desde 90 dias y $1.000.000 desde 30. La tasa no esta en el corpus y lo dice. (propuesta) |
| 15 | ¿Qué créditos de vivienda ofrece? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/creditos/vivienda | - | Correcta: Hipotecario, leasing, compra de cartera y exterior. (propuesta) |
| 16 | ¿Ofrece crédito de vehículo? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/creditos/carros | - | Correcta: Occiauto: hasta 100 %, 84 meses, 2,5 SMLMV, 18 a 74 anos. (propuesta) |
| 17 | ¿Qué hago si pierdo mi tarjeta o me la roban? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/ayuda/preguntas-frecuentes | - | Correcta: Bloqueo por app o linea 24/7, ambos en la fuente. (propuesta) |
| 18 | ¿Cómo uso la banca móvil o la app? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/canales-digitales/banca-movil | - | Correcta: Funciones de la app y seguridad. (propuesta) |
| 19 | ¿Qué acciones de sostenibilidad realiza? | si | Correcta | 1/1 | https://www.bancodeoccidente.com.co/sostenibilidad | - | Correcta: Ejes ambiental, social y de gobierno; Pacto Global, GHG y GRI. (propuesta) |
| 20 | ¿Cuáles son las noticias recientes del banco? | si | Correcta | 1/1 | https://www.portafolio.co/energia/banco-de-occidente-financiara-con-200-000-millones-parque-solar-en-santander-que-generara-500-gwh-al-ano-504747 | - | Correcta: Seis noticias de 2026, pero cita una sola fuente para todas. (propuesta) |

## Respuestas

### 1. ¿Cuál es el horario de atención de las oficinas?

Cobertura esperada: **no** · Clasificación: **Rechazo correcto** · 5.3 s

> No encuentro esa información en las fuentes públicas del banco
> Puedes consultar la Línea de Servicio al Cliente 018000514652 o los canales oficiales en https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente
> Fuente: https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente

### 2. ¿Dónde hay una oficina en Cali?

Cobertura esperada: **parcial** · Clasificación: **Correcta** · 5.4 s

> No encuentro en las fuentes públicas un listado de oficinas del Banco en Cali. Lo que sí aparece es la dirección Carrera 3 No. 8-13, Piso 4, en la ciudad de Cali, usada para las Asambleas de Accionistas, y la línea de atención en Cali (602) 4851113, además de la línea nacional 018000514652 (solo teléfonos fijos).
>
> Para conocer la ubicación y horarios de la red de oficinas puedes consultar la sección de oficinas del sitio del banco o comunicarte a las líneas de servicio al cliente; allí te orientan sobre la sucursal más cercana.
>
> Fuente: https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente

### 3. ¿Cuál es la línea de atención telefónica?

Cobertura esperada: **si** · Clasificación: **Correcta** · 2.9 s

> Estas son las líneas de Servicio al Cliente del Banco de Occidente:
>
> - Bogotá: (601) 390 2058
> - Cali: (602) 485 1113
> - Medellín: (604) 605 2020
> - Barranquilla: (605) 386 9772
> - Nivel nacional: 018000514652 (solo teléfonos fijos)
> - EE. UU.: 018004538044
>
> También cuentas con líneas de respuesta automática para transacciones y consultas de cuentas, tarjeta de crédito, préstamo personal o crédito rotativo, y servicios como bloqueo o cambio de clave de tus tarjetas.
>
> Fuente: https://www.bancodeoccidente.com.co/ayuda/linea-servicio-cliente

### 4. ¿Cómo presento una petición, queja o reclamo?

Cobertura esperada: **si** · Clasificación: **Correcta** · 5.7 s

> Puedes radicar tus peticiones, quejas o reclamos (PQRS) por estos canales oficiales:
>
> - **Formulario Digital PQRS** en https://contactenos.bancodeoccidente.com.co, donde seleccionas la opción "Formulario Digital PQRS", eliges el producto, diligencias los datos y adjuntas documentos en PDF, JPG o JPEG.
> - **Líneas de Servicio al Cliente:** Bogotá (601) 3902058, Cali (602) 4851113, Medellín (604) 6052020, Barranquilla (605) 3869772, nacional 018000514652 (solo teléfonos fijos) y EE. UU. 018004538044.
> - **Oficinas** del Banco a nivel nacional.
> - Si tu queja está relacionada con un incumplimiento de normas legales o contractuales, también puedes acudir al **Defensor del Consumidor Financiero**.
>
> Fuente: https://www.bancodeoccidente.com.co/ayuda

### 5. ¿Quién es el Defensor del Consumidor Financiero y cómo lo contacto?

Cobertura esperada: **si** · Clasificación: **Correcta** · 5.7 s

> El Defensor del Consumidor Financiero es un representante del banco encargado de atender y resolver quejas relacionadas con incumplimientos de las normas legales y contractuales de productos y servicios; también recibe recomendaciones y propuestas. Puede actuar como conciliador y es una instancia adicional de servicio.
>
> Puedes presentar tu queja o reclamo sin costo mediante un documento escrito, enviándolo directamente al Defensor por cualquiera de los canales disponibles o en las oficinas del banco, que deben remitirlo dentro de los 3 días hábiles siguientes.
>
> En las fuentes consultadas no aparece un teléfono o correo específico del Defensor. Para orientación puedes usar las Líneas de Servicio al Cliente: Bogotá (601) 3902058, Cali (602) 4851113, Medellín (604) 6052020, Barranquilla (605) 3869772 y nacional 018000514652.
>
> Fuente: https://www.bancodeoccidente.com.co/quienes-somos/defensor-consumidor-financiero

### 6. ¿Cuál es el propósito o misión del banco?

Cobertura esperada: **parcial** · Clasificación: **Correcta** · 2.4 s

> El propósito del Banco de Occidente es: «Hacer realidad el desarrollo de las personas, el crecimiento de los negocios y la transformación del país».
>
> Este propósito se acompaña de cuatro pilares declarados: ser líderes en sus segmentos core, ser sostenibles (actuando con responsabilidad y ética), ser digitales (optimizando operaciones y servicio con tecnología) y ser deseados (creando experiencias memorables para clientes, colaboradores y proveedores).
>
> Fuente: https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco

### 7. ¿Cuándo y dónde se fundó el banco?

Cobertura esperada: **si** · Clasificación: **Correcta** · 1.9 s

> El Banco de Occidente nació el 3 de mayo de 1965 en la ciudad de Cali, bajo la administración del Doctor Alfonso Díaz Viana, con el slogan "el banco que lo conoce a usted".
>
> Fuente: https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco

### 8. ¿A qué grupo empresarial pertenece?

Cobertura esperada: **si** · Clasificación: **Correcta** · 3.1 s

> El Banco de Occidente hace parte del **Grupo Aval**. Así se indica en la página de Filiales y Vinculadas, donde el Grupo Aval se describe como conformado por entidades de reconocida solidez en el país.
>
> Adicionalmente, en la historia del banco se señala que en 1998 entró a formar parte del Grupo AVAL, conformado por los bancos AVVillas, Bogotá, Occidente y Popular.
>
> Fuente: https://www.bancodeoccidente.com.co/quienes-somos/filiales

### 9. ¿Quién es el presidente del banco?

Cobertura esperada: **si** · Clasificación: **Correcta** · 3.0 s

> Según la información pública del banco, **Gerardo Silva Castro** es el Presidente del Banco de Occidente. Es Ingeniero Civil de la Universidad Javeriana de Bogotá, con máster en Administración de Empresas de Babson College (Estados Unidos), y cuenta con amplia experiencia en el sector financiero. Trabaja en el Banco desde 1994, donde se desempeñó como vicepresidente de Banca Empresarial, Oficial e Intermedia; en abril de 2014 fue nombrado Vicepresidente de Empresas y en agosto de 2023 fue nombrado Presidente del Banco de Occidente. Actualmente pertenece a las juntas directivas de Corficolombiana, el Consejo Directivo de Anif y Asobancaria.
>
> Fuente: https://www.bancodeoccidente.com.co/quienes-somos/informacion-inversionistas

### 10. ¿Qué tipos de cuentas de ahorro ofrece?

Cobertura esperada: **si** · Clasificación: **Correcta** · 3.7 s

> El Banco de Occidente ofrece, según la información pública disponible:
>
> - **Cuenta de Ahorros Digital**: apertura en línea, con respaldo FOGAFÍN y opción de exoneración del 4x1000.
> - **Cuenta AFC**: especializada para ahorrar para vivienda, con beneficios tributarios y sin cuota de manejo de la tarjeta débito.
> - **Cuenta de Ahorros para Pensionados**: para pensionados de Colpensiones, Fonpecar o Cremil, con intereses diarios y tarjeta débito sin cuota de manejo.
> - **Cuenta de Nómina**: con modalidades Cuenta Plata, Cuenta Oro y Cuenta Platinum, según el nivel de ingresos.
> - **Cuenta Activa** y **Cuenta Activa Básica**: portafolio de ahorro y crédito.
> - **KUBO**: sistema de ahorro e inversión que parte de tu cuenta de ahorros.
>
> Fuente: https://www.bancodeoccidente.com.co/cuenta-de-ahorros

### 11. ¿Qué requisitos necesito para abrir una cuenta?

Cobertura esperada: **si** · Clasificación: **Correcta** · 4.0 s

> Para una cuenta de ahorros o corriente como persona natural, las preguntas frecuentes indican estos documentos:
>
> - Fotocopia ampliada al 150% del documento de identidad del cliente y/o terceros autorizados, con huella.
> - Certificado laboral que detalle salario, antigüedad y cargo, con fecha de expedición no mayor a 60 días.
> - Cámara de comercio y/o RUT.
>
> Ten en cuenta que los requisitos varían según el producto: por ejemplo, la Cuenta Activa pide documentación específica para empleados e independientes, y la Cuenta AFC no exige monto mínimo de apertura.
>
> Si me dices qué tipo de cuenta te interesa (ahorros, corriente, nómina, AFC o Activa), te comparto los requisitos de ese producto.
>
> Fuente: https://www.bancodeoccidente.com.co/ayuda/preguntas-frecuentes

### 12. ¿Puedo abrir una cuenta en línea?

Cobertura esperada: **si** · Clasificación: **Correcta** · 3.5 s

> Sí. El Banco de Occidente permite solicitar la cuenta de ahorros de forma digital: puedes crearla en cualquier momento, incluso por fuera del horario laboral, y se pueden solicitar máximo dos cuentas del mismo tipo por esta vía. La tarjeta débito se envía al domicilio (el proceso puede tardar entre 5 y 7 días según la ciudad) y la oficina quedará asignada según tu ciudad de residencia. También puedes iniciar la solicitud en línea desde la página de la Cuenta de Nómina, con aprobación en minutos.
>
> Si prefieres acompañamiento, puedes usar la línea nacional 018000514652 (solo teléfonos fijos).
>
> Fuente: https://www.bancodeoccidente.com.co/sistema-kubo

### 13. ¿Qué tarjetas de crédito ofrece y cuál es su cuota de manejo?

Cobertura esperada: **si** · Clasificación: **Correcta** · 6.2 s

> El banco ofrece varias tarjetas Credencial: Clásicas (Visa y Mastercard), Gold, Platinum, Black, Visa Infinite, Free, OcciFlex digital, LATAM Pass (Clásica, Gold, Platinum y Signature), Santafé, Visa Mascotas, Mastercard Unicef y la Tarjeta RIGO.
>
> Sobre la cuota de manejo, el contexto indica:
> - Credencial Free: $0, exoneración permanente.
> - OcciFlex: exoneración si factura compras mensuales por $160.000.
> - Clásica y RIGO: exoneración por 6 meses para clientes nuevos.
> - Gold, Platinum, Black e Infinite: 12 meses para clientes nuevos.
> - LATAM Pass: 3 meses sin cuota de manejo.
>
> El valor mensual solo aparece para la Tarjeta RIGO ($31.800 anticipado); para las demás no encuentro esa información en las fuentes públicas del banco. Puedes consultar tarifas o llamar a la Línea Nacional 018000514652.
>
> Fuente: https://www.bancodeoccidente.com.co/tarjetas-credito

### 14. ¿Qué es un CDT y cuál es su tasa?

Cobertura esperada: **parcial** · Clasificación: **Correcta** · 5.3 s

> Un CDT (Certificado de Depósito a Término) es un producto de inversión con el que haces crecer tu dinero a un plazo determinado. Según la información pública:
>
> - Apertura desde $500.000 (plazo mínimo de 30 días).
> - Tú eliges el plazo según tu planificación financiera.
> - Los intereses pueden pagarse de forma mensual, bimestral, trimestral, semestral o anual, abonados en tu cuenta del banco o retirados en efectivo en oficinas.
> - Puedes renovarlo automáticamente, endosarlo o negociar sus condiciones.
> - Cuenta con seguro de depósitos Fogafín.
> - Si tienes cuenta de ahorros, puedes abrir tu CDT Digital desde el portal.
>
> Sobre la tasa: No encuentro esa información en las fuentes públicas del banco. Puedes consultar las tasas vigentes en la sección de tarifas y tasas del sitio, o comunicarte con la Línea Nacional 01 8000 514652 (solo teléfonos fijos).
>
> Fuente: https://www.bancodeoccidente.com.co/inversion/cdt

### 15. ¿Qué créditos de vivienda ofrece?

Cobertura esperada: **si** · Clasificación: **Correcta** · 3.4 s

> El Banco de Occidente ofrece estas opciones de vivienda:
>
> - **Crédito Hipotecario**: para compra de vivienda nueva o usada, con cuotas fijas y plazos flexibles; también para remodelación, ampliación o subdivisión (RAS). Financia hasta el 70% del valor comercial, con montos desde $50.000.000 y disponible para asalariados e independientes.
> - **Leasing Habitacional**: para compra de vivienda nueva o usada y para construcción de vivienda propia, pagando cuotas fijas y con opción de compra al final del contrato.
> - **Compra de cartera hipotecaria**: para mejorar las condiciones de un crédito de vivienda existente.
> - **Crédito de vivienda para colombianos en el exterior**, con plazos de 5 a 20 años en pesos y 30 años en UVR.
>
> Puedes consultar requisitos y simular en el sitio web o con un asesor.
>
> Fuente: https://www.bancodeoccidente.com.co/creditos/vivienda

### 16. ¿Ofrece crédito de vehículo?

Cobertura esperada: **si** · Clasificación: **Correcta** · 2.7 s

> Sí. El Banco de Occidente ofrece crédito de vehículo a través de **Occiauto**, para carro nuevo o usado. Según la información publicada:
>
> - Financiación hasta el 100% del valor del vehículo, sin cuota inicial.
> - Plazos de financiación hasta 84 meses.
> - Aplica para independientes y asalariados.
> - Ingresos mínimos desde 2.5 SMLMV; edad de 18 a 74 años.
> - Se puede simular y solicitar en línea.
> - También hay líneas para vehículos híbridos/eléctricos, motos y vehículos productivos de carga y pasajeros.
>
> Fuente: https://www.bancodeoccidente.com.co/creditos/carros

### 17. ¿Qué hago si pierdo mi tarjeta o me la roban?

Cobertura esperada: **si** · Clasificación: **Correcta** · 4.4 s

> Si pierdes o te roban tu Tarjeta de Crédito Credencial, debes bloquearla de inmediato: puedes hacerlo por medio de la App o comunicándote con las Líneas de Servicio al Cliente:
>
> - Nacional: 01 800 05 14652
> - Bogotá: 390 20 58
> - Cali: 485 11 13
> - Medellín: 605 20 20
> - Barranquilla: 386 97 72
>
> Si te encuentras en el exterior, acércate a cualquier banco afiliado a Mastercard. Recuerda que ante robo o extravío también puedes solicitar el reemplazo de emergencia con la franquicia (Visa o Mastercard) usando los números internacionales publicados en las preguntas frecuentes.
>
> Además, las líneas de atención al cliente están disponibles los 7 días de la semana, las 24 horas.
>
> Fuente: https://www.bancodeoccidente.com.co/ayuda/preguntas-frecuentes

### 18. ¿Cómo uso la banca móvil o la app?

Cobertura esperada: **si** · Clasificación: **Correcta** · 4.4 s

> Con la App Banco de Occidente Móvil puedes enviar dinero, pagar facturas y recargar desde cualquier lugar; consultar saldos, movimientos y administrar tu dinero; solicitar créditos, tarjetas y cuentas sin ir a una oficina; e iniciar sesión con huella o reconocimiento facial para mayor seguridad.
>
> La app incluye un asistente virtual con inteligencia artificial que te ayuda a gestionar tus finanzas, y usa un dato seguro enviado al número de celular registrado o la generación a través del Token Mobile. También puedes generar certificados de productos y extractos a costo $0.
>
> Para aprender a usarla, la página indica que hay tutoriales paso a paso y consejos de seguridad para proteger tu información.
>
> Fuente: https://www.bancodeoccidente.com.co/canales-digitales/banca-movil

### 19. ¿Qué acciones de sostenibilidad realiza?

Cobertura esperada: **si** · Clasificación: **Correcta** · 4.7 s

> El Banco de Occidente actúa con responsabilidad ambiental, social y corporativa, con estos frentes:
>
> - **Ambiental:** mitigar el cambio climático y ser responsables con los recursos naturales, con asuntos materiales como gestión del cambio climático.
> - **Social:** fortalecer habilidades financieras de clientes y comunidades, contribuir al desarrollo de las regiones, crear experiencias de valor, impulsar el talento y respetar los Derechos Humanos.
> - **Gobierno corporativo:** impulsar negocios sostenibles, actuar de forma ética, generar crecimiento rentable, gestionar riesgos, ser guardianes de la información y transformarse digitalmente.
>
> Además, publica su Informe de Gestión y Sostenibilidad, cuenta con iniciativas como el Premio Nacional de Ecología Planeta Azul (agua) y, según la historia del banco, se adhirió a Pacto Global, midió sus emisiones de gases de efecto invernadero bajo el referente GHG Protocol y elaboró su informe bajo estándares GRI.
>
> Fuente: https://www.bancodeoccidente.com.co/sostenibilidad

### 20. ¿Cuáles son las noticias recientes del banco?

Cobertura esperada: **si** · Clasificación: **Correcta** · 6.0 s

> Algunas noticias recientes publicadas sobre el Banco de Occidente:
>
> - **19 de octubre de 2026:** financiará con $200.000 millones un parque solar en Santander que generará 500 GWh al año (Portafolio).
> - **19 de octubre de 2026:** la SFC autorizó clasificar en el Patrimonio Adicional el crédito subordinado con DEG por USD 150 MM.
> - **9 de octubre de 2026:** logró una tasa de aprobación superior a 90% en compras con tarjeta (La República).
> - **7 de octubre de 2026:** creció 23% en el primer semestre de 2026 y apuesta por la digitalización (Valora Analitik).
> - **3 de septiembre de 2026:** completó la absorción por adquisición de Fiduciaria de Occidente (La República).
> - **27 de agosto de 2026:** junto con CAF destinarán hasta USD 50 millones a la reactivación tras el terremoto.
>
> Fuente: https://www.portafolio.co/energia/banco-de-occidente-financiara-con-200-000-millones-parque-solar-en-santander-que-generara-500-gwh-al-ano-504747
