# Plantilla de pull request

## Descripción

<!-- Qué cambia este PR y por qué. -->

## Tipo de cambio

- [ ] `feat`: nueva funcionalidad
- [ ] `fix`: corrección de bug
- [ ] `docs`: cambios solo en documentación
- [ ] `test`: cambios en tests
- [ ] `refactor`: cambios de código sin alterar comportamiento

## ¿Cómo se ha probado?

<!-- Comandos ejecutados, capturas del dashboard si aplica, etc. -->

```bash
pytest tests/unitario
pytest tests/integracion
cd dbt_project && dbt test
```

## Checklist

- [ ] El código sigue las convenciones de [`reglas de seguridad/coding-rules.md`](../reglas%20de%20seguridad/coding-rules.md) (formateo con `black`, linting con `ruff`).
- [ ] No se han añadido claves, tokens ni credenciales al código.
- [ ] Los tests unitarios y de integración pasan en local.
- [ ] `dbt test` pasa sin errores sobre los modelos afectados.
- [ ] Si el cambio afecta a una decisión de arquitectura ya documentada, se ha añadido una entrada nueva en [`docs/decisions.md`](../docs/decisions.md).
- [ ] La documentación relevante (`README.md`, `docs/architecture.md`) está actualizada si el cambio lo requiere.

## Issues relacionados

Closes #