-- Una fila por oferta. La clasificación del LLM se une aquí porque, a efectos
-- de análisis, los campos extraídos son atributos de la propia oferta.
{% set salario_anual_min = 15000 %}
{% set salario_anual_max = 300000 %}

with

ofertas as (
    select
        cast(id as varchar) as id_oferta,
        trim(titulo) as titulo,
        descripcion,
        try_cast(left(cast(fecha_publicacion as varchar), 10) as date) as fecha_publicacion,
        trim(empresa) as empresa,
        -- Salario publicado por Adzuna: mezcla importes por hora, mensuales y
        -- anuales, así que solo se aceptan valores en un rango anual plausible (ADR-010).
        case
            when salario_min_anunciado between {{ salario_anual_min }} and {{ salario_anual_max }}
                then salario_min_anunciado
        end as salario_min_adzuna,
        case
            when salario_max_anunciado between {{ salario_anual_min }} and {{ salario_anual_max }}
                then salario_max_anunciado
        end as salario_max_adzuna
    from {{ source('raw', 'raw_ofertas') }}
    where id is not null
    qualify row_number() over (
        partition by cast(id as varchar)
        order by try_cast(left(cast(fecha_publicacion as varchar), 10) as date) desc nulls last
    ) = 1
),

clasificaciones as (
    select
        cast(id_oferta as varchar) as id_oferta,
        -- Lista cruda del LLM, para que dbt la normalice contra el catálogo y los
        -- cambios del seed se apliquen también a ofertas ya clasificadas (ADR-009).
        -- Si la respuesta guardada no fuera JSON válido, se usa la lista ya
        -- normalizada en Python.
        coalesce(
            try_cast(json_extract(try_cast(respuesta_llm as json), '$.tecnologias') as varchar[]),
            tecnologias
        ) as tecnologias,
        nullif(lower(trim(seniority)), '') as seniority,
        replace(nullif(lower(trim(modalidad)), ''), 'í', 'i') as modalidad,
        try_cast(salario_min as double) as salario_min,
        try_cast(salario_max as double) as salario_max
    from {{ source('raw', 'raw_ofertas_clasificadas') }}
    where error is null
    qualify row_number() over (
        partition by cast(id_oferta as varchar)
        order by fecha_extraccion desc
    ) = 1
),

ofertas_clasificadas as (
    select
        ofertas.id_oferta,
        ofertas.titulo,
        ofertas.descripcion,
        ofertas.fecha_publicacion,
        ofertas.empresa,
        clasificaciones.tecnologias,
        clasificaciones.seniority,
        clasificaciones.modalidad,
        -- El salario explícito en el texto (LLM) tiene prioridad sobre el de Adzuna.
        case
            when coalesce(clasificaciones.salario_min, clasificaciones.salario_max) is not null
                then 'llm'
            when coalesce(ofertas.salario_min_adzuna, ofertas.salario_max_adzuna) is not null
                then 'adzuna'
        end as fuente_salario,
        case
            when coalesce(clasificaciones.salario_min, clasificaciones.salario_max) is not null
                then clasificaciones.salario_min
            else ofertas.salario_min_adzuna
        end as salario_min,
        case
            when coalesce(clasificaciones.salario_min, clasificaciones.salario_max) is not null
                then clasificaciones.salario_max
            else ofertas.salario_max_adzuna
        end as salario_max
    from ofertas
    left join clasificaciones
        on ofertas.id_oferta = clasificaciones.id_oferta
)

select *
from ofertas_clasificadas
-- Una misma oferta suele publicarse en varias ciudades con distinto id: se deja
-- una por (título, empresa, mes), priorizando la que tiene tecnologías (ADR-011).
qualify row_number() over (
    partition by
        case
            when titulo is not null and empresa is not null
                then lower(titulo) || '|' || lower(empresa) || '|'
                    || coalesce(strftime(date_trunc('month', fecha_publicacion), '%Y-%m'), '')
            else id_oferta
        end
    order by
        coalesce(len(tecnologias), -1) desc,
        fecha_publicacion desc nulls last,
        id_oferta
) = 1
