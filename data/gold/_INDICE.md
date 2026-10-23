# Indice del corpus

**Empresa:** Banco de Occidente  
**Fuente:** https://www.bancodeoccidente.com.co  
**Documentos Gold:** 0  
**Tokens totales:** 0 (promedio 0)  
**Cobertura del checklist:** 0/24 (0%)

## Documentos por seccion

| Seccion | Documentos |
|---|---:|

## Checklist del Taller 1

### Identidad corporativa — 0/6

- [ ] Mision y vision
- [ ] Valores y proposito
- [ ] Historia (fundacion, hitos)
- [ ] Fundador / dueno y junta
- [ ] Gerente y equipo directivo
- [ ] Sedes y ubicaciones

### Productos y servicios — 0/6

- [ ] Productos y servicios
- [ ] Fichas tecnicas y especificaciones
- [ ] Precios y planes
- [ ] Catalogos en PDF
- [ ] Casos de exito y clientes
- [ ] Certificaciones

### Presencia digital / noticias — 0/6

- [ ] Noticias y sala de prensa
- [ ] Blog y articulos
- [ ] Videos de YouTube
- [ ] Entrevistas del gerente
- [ ] Redes sociales
- [ ] Vacantes de empleo

### Datos duros e informes — 0/6

- [ ] Informes financieros / memoria anual
- [ ] NIT y Camara de Comercio
- [ ] Indicadores de sostenibilidad
- [ ] Precios publicos y tarifas
- [ ] Datos abiertos (Superfinanciera, SECOP)
- [ ] Rankings sectoriales

## Como se genero

```
make all      # discover -> fetch -> extract -> gold -> stats
```

Capas: `data/raw/` (Bronze, crudo) -> `data/processed/` (Silver, limpio) -> `data/gold/` (Gold, con metadatos). Solo Gold alimenta al RAG.
