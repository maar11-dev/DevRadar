-- Una fila por oferta. La clasificación del LLM se une aquí porque, a efectos
-- de análisis, los campos extraídos son atributos de la propia oferta.
with

ofertas as (
    select
        cast(id as varchar) as id_oferta,
        trim(titulo) as titulo,
        descripcion,
        try_cast(left(cast(fecha_publicacion as varchar), 10) as date) as fecha_publicacion,
        trim(empresa) as empresa
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
        tecnologias,
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
)

select
    ofertas.id_oferta,
    ofertas.titulo,
    ofertas.descripcion,
    ofertas.fecha_publicacion,
    ofertas.empresa,
    clasificaciones.tecnologias,
    clasificaciones.seniority,
    clasificaciones.modalidad,
    clasificaciones.salario_min,
    clasificaciones.salario_max
from ofertas
left join clasificaciones
    on ofertas.id_oferta = clasificaciones.id_oferta
