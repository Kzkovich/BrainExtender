# {{ title }}

**Дата:** {{ date }}
**Стороны:** {{ people | join(', ') if people else 'не указано' }}
**Воркспейс:** {{ workspace }}
**Статус:** {{ status or 'active' }}

## Суть договорённости
{{ narrative }}

## Условия
{% for condition in conditions %}
- {{ condition }}
{% else %}
_не указаны_
{% endfor %}

## Дедлайн / срок действия
{{ deadline or 'не ограничено' }}
