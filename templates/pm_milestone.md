# {{ title }}

**Дата:** {{ date }}
**Дедлайн:** {{ deadline }}
**Проект:** {{ workspace }}
**Статус:** {{ status or 'planned' }}

## Описание
{{ narrative }}

## Критерии достижения
{% for criterion in done_criteria %}
- [ ] {{ criterion }}
{% else %}
_не указаны_
{% endfor %}
