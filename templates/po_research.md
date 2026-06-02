# {{ title }}

**Дата:** {{ date }}
**Источник:** {{ source_url or 'не указан' }}
**Воркспейс:** {{ workspace }}

## Ключевые тезисы
{% for thesis in key_theses %}
- {{ thesis }}
{% else %}
_нет_
{% endfor %}

## Применимо к нам
{{ applicability }}

## Цитаты / данные
{{ quotes or '_нет_' }}

## Следующие шаги
{{ next_steps or '_нет_' }}
