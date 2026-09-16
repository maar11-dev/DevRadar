with

ofertas as (
    select
        id_oferta,
        fecha_publicacion,
        tecnologias
    from {{ ref('stg_ofertas') }}
    where tecnologias is not null
),

tecnologias_detectadas as (
    select
        id_oferta,
        fecha_publicacion,
        unnest(tecnologias) as tecnologia_detectada
    from ofertas
),

catalogo as (
    select
        variante,
        nombre_canonico
    from {{ ref('catalogo_tecnologias') }}
)

select distinct
    tecnologias_detectadas.id_oferta || '|' || catalogo.nombre_canonico as id_oferta_tecnologia,
    tecnologias_detectadas.id_oferta,
    catalogo.nombre_canonico as tecnologia,
    tecnologias_detectadas.fecha_publicacion
from tecnologias_detectadas
inner join catalogo
    on lower(trim(tecnologias_detectadas.tecnologia_detectada)) = catalogo.variante
