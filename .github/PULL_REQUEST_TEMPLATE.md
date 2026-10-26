## Qué cambia

<!-- Describe el cambio en una o dos frases. -->

## Por qué

<!-- Problema, issue o decisión que motiva el cambio. -->

## Cómo se verificó

- [ ] `make check` (ruff + ty + pytest)
- [ ] `make demo` (pipeline offline)
- [ ] `make status` si se tocó el corpus

## Checklist

- [ ] Actualicé `CONSTITUTION.md` si cambió alcance, stack o formato de Gold.
- [ ] No hay `pip` ni `requirements.txt` (`uv` es el único gestor).
- [ ] No toqué `data/raw/` a mano.
- [ ] Respeté `robots.txt`, el ritmo de cortesía de 1,5 s entre peticiones y el header `From`.
- [ ] El commit sigue Conventional Commits en español.

Closes #
