# {{ title }}

**Дата:** {{ date }}
**Исполнитель:** {{ assignee or 'не назначен' }}
**Дедлайн:** {{ deadline or 'не указан' }}
**Приоритет:** {{ priority or 'medium' }}
**Воркспейс:** {{ workspace }}

## Описание
{{ narrative }}

## Критерии готовности
{% for criterion in done_criteria %}
- [ ] {{ criterion }}
{% else %}
_не указаны_
{% endfor %}
