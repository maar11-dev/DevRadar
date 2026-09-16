# Reglas de seguridad y convenciones de código

## 🔐 Gestión de secretos

- **Nunca** se sube al repositorio ninguna API key, token o credencial, ni siquiera en commits antiguos o ramas de prueba.
- Todas las claves (p. ej. `GROQ_API_KEY`) se gestionan como **GitHub Secrets** y se inyectan como variables de entorno en el workflow de Actions.
- En local, las credenciales se cargan desde un archivo `.env` (nunca versionado — ver `.gitignore`), siguiendo el ejemplo de `.env.example`.
- Antes de cada commit, revisar que no se ha pegado accidentalmente ninguna clave en código, notebooks o logs.

## 🕸️ Buenas prácticas de scraping

- Respetar siempre `robots.txt` de la fuente de datos.
- Limitar la frecuencia de peticiones (rate limiting) para no sobrecargar el servidor de origen.
- Usar un `User-Agent` identificable y honesto.
- Cachear en disco las respuestas ya obtenidas para evitar peticiones redundantes.
- Implementar reintentos con backoff exponencial ante fallos de red, nunca reintentos inmediatos en bucle.

## ✅ Calidad y validación de datos

- Toda tabla nueva en dbt debe incluir al menos tests de `not_null` y `unique` sobre su clave primaria.
- Las tecnologías extraídas por el LLM se normalizan siempre contra un catálogo controlado (`seeds/catalogo_tecnologias.csv`) antes de llegar a los marts, para evitar duplicados por variantes de escritura (`"React"` vs `"ReactJS"` vs `"react.js"`).
- Ningún modelo de `marts` se considera válido si no pasa `dbt test` sin errores; el workflow de CI está configurado para fallar en ese caso.

## 🧹 Convenciones de código

- Formateo con `black`, linting con `ruff`. Ambos se ejecutan como pre-commit hook.
- Nombres de funciones y variables en `snake_case`, en inglés, siguiendo el estilo del resto del ecosistema Python/dbt.
- Los modelos dbt siguen la convención de prefijos estándar: `stg_`, `int_`, y nombres descriptivos sin prefijo para `marts`.
- Cada función pública lleva docstring explicando propósito, parámetros y valor de retorno.

## 📝 Convenciones de commits

- Se sigue el formato de [Conventional Commits](https://www.conventionalcommits.org/):
  - `feat: ...` nueva funcionalidad
  - `fix: ...` corrección de bug
  - `docs: ...` cambios solo en documentación
  - `test: ...` cambios en tests
  - `refactor: ...` cambios de código sin alterar comportamiento
- Los mensajes se escriben en imperativo y en minúsculas (`feat: añade extracción de rango salarial`, no `Feat: Added...`).

## 🔍 Revisión de cambios

- Ningún cambio en los modelos `marts` se fusiona sin haber ejecutado `dbt test` localmente.
- Los cambios en prompts del LLM (`src/extract.py`) deben documentarse en `docs/decisions.md` si alteran de forma significativa el esquema de salida.