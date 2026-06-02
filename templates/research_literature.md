# {{ title }}

**Дата:** {{ date }}
**Автор:** {{ author or 'не указан' }}
**Год:** {{ year or 'не указан' }}
**Источник:** {{ source_url or '_нет_' }}

## Ключевые тезисы
{% for thesis in key_theses %}
- {{ thesis }}
{% else %}
_нет_
{% endfor %}

## Цитаты
{{ quotes or '_нет_' }}

## Применимо к моим исследованиям
{{ applicability }}
