# {{ title }}

**Дата:** {{ date }}
**Воркспейс:** {{ workspace }}
**Фича:** {{ feature_slug }}
**Статус:** {{ status or 'draft' }}

## Проблема / зачем
{{ problem_statement }}

## Решение
{{ solution }}

## Метрики успеха
{% for metric in metrics %}
- {{ metric }}
{% else %}
_не определены_
{% endfor %}

## Ограничения / non-goals
{{ constraints or '_нет_' }}

## Связанные решения
{{ linked_decisions or '_нет_' }}
