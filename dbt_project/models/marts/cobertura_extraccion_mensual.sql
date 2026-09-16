-- Ofertas clasificadas por mes y cuántas de ellas no tienen ninguna tecnología
-- detectada (ADR-007). Una oferta está clasificada si su última extracción con
-- el LLM terminó sin error, aunque devolviera la lista de tecnologías vacía.
with

ofertas_clasificadas as (
    select
        id_oferta,
        cast(date_trunc('month', fecha_publicacion) as date) as mes
    from {{ ref('stg_ofertas') }}
    where tecnologias is not null
        and fecha_publicacion is not null
),

ofertas_con_tecnologia as (
    select distinct id_oferta
    from {{ ref('int_tecnologias_por_oferta') }}
)

select
    ofertas_clasificadas.mes,
    count(*) as total_ofertas_clasificadas,
    count(*) filter (where ofertas_con_tecnologia.id_oferta is null) as ofertas_sin_tecnologia,
    round(
        100.0 * count(*) filter (where ofertas_con_tecnologia.id_oferta is null) / count(*), 2
    ) as pct_sin_tecnologia
from ofertas_clasificadas
left join ofertas_con_tecnologia
    on ofertas_clasificadas.id_oferta = ofertas_con_tecnologia.id_oferta
group by ofertas_clasificadas.mes
