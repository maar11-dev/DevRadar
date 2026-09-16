-- Las variantes deben estar en minúsculas y sin espacios sobrantes; si no, ni el
-- join de int_tecnologias_por_oferta ni load_catalog() las encontrarían.
select variante
from {{ ref('catalogo_tecnologias') }}
where variante <> lower(regexp_replace(trim(variante), '\s+', ' ', 'g'))
