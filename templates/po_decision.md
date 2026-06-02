# {{ title }}

**Дата:** {{ date }}
**Статус:** {{ status or 'accepted' }}
**Воркспейс:** {{ workspace }}
**Участники:** {{ people | join(', ') if people else 'не указано' }}

## Контекст
{{ context }}

## Решение
{{ decision }}

## Альтернативы которые рассматривались
{% for alt in alternatives %}
- {{ alt }}
{% else %}
_нет_
{% endfor %}

## Последствия
{{ consequences }}
