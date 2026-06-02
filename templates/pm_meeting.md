# {{ title }}

**Дата:** {{ date }}
**Участники:** {{ people | join(', ') if people else 'не указано' }}
**Проект:** {{ workspace }}

## Статус проекта
{{ project_status or '_не обсуждался_' }}

## Блокеры
{% for blocker in blockers %}
- {{ blocker }}
{% else %}
_нет_
{% endfor %}

## Решения
{% for decision in key_decisions %}
- {{ decision }}
{% else %}
_нет_
{% endfor %}

## Next steps
{% for item in action_items %}
- [ ] {{ item.task }} — {{ item.owner or '?' }} — {{ item.deadline or 'без срока' }}
{% else %}
_нет_
{% endfor %}
